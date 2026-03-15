"""Two-tier configuration system for Tequila v2 (§14.4, §15, §28.4).

### Tier 1 — ``ServerSettings`` (Pydantic-Settings, read-only at runtime)

Loaded once from environment variables (prefix ``TEQUILA_``) or a ``.env``
file before the database opens.  Fields that require a restart to take effect
(``host``, ``port``, ``gateway_token``) live here so they cannot be hot-edited.

### Tier 2 — ``ConfigStore`` (SQLite-backed, hot-reloadable)

Wraps the ``config`` table.  Keys are dot-namespaced strings like
``"memory.extraction.trigger_interval_messages"``.  Values are JSON-encoded
and typed by the ``value_type`` column.  Non-restart-required keys take effect
immediately after ``set()``; restart-required keys raise an error if changed at
runtime.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.constants import DEFAULT_HOST, DEFAULT_PORT
from app.db.connection import write_transaction
from app.exceptions import ConfigKeyNotFoundError, ConfigValidationError

logger = logging.getLogger(__name__)

# ── Tier 1: ServerSettings ────────────────────────────────────────────────────


class ServerSettings(BaseSettings):
    """Process-level settings loaded from the environment / ``.env`` file.

    These settings are read before the database opens and are never modified
    at runtime.  Changes require a process restart.
    """

    model_config = SettingsConfigDict(
        env_prefix="TEQUILA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(default=DEFAULT_HOST)
    """HTTP server bind address (``TEQUILA_HOST``)."""

    port: int = Field(default=DEFAULT_PORT)
    """HTTP server port (``TEQUILA_PORT``)."""

    gateway_token: str = Field(default="")
    """Gateway authentication token (``TEQUILA_GATEWAY_TOKEN``).

    Empty string means no token is required (local development mode).
    """

    debug: bool = Field(default=False)
    """Enable debug mode — verbose logging, auto-reload (``TEQUILA_DEBUG``)."""


# ── ServerSettings singleton ──────────────────────────────────────────────────

_settings: ServerSettings | None = None


def get_settings() -> ServerSettings:
    """Return the cached ``ServerSettings`` singleton.

    Creates it on first call.  Safe to call from anywhere after the process
    starts; the value never changes at runtime.
    """
    global _settings  # noqa: PLW0603
    if _settings is None:
        _settings = ServerSettings()
    return _settings


# ── Tier 2: ConfigStore ───────────────────────────────────────────────────────

#: Keys that cannot be changed at runtime — changing them silently has no effect.
_RESTART_REQUIRED_KEYS: frozenset[str] = frozenset(
    {"server.host", "server.port", "server.gateway_token"}
)

#: Sentinel object for optional ``default`` parameter on ``ConfigStore.get``.
_SENTINEL = object()

#: Mapping from value_type string to a Python converter callable.
_TYPE_CONVERTERS: dict[str, Any] = {
    "int": int,
    "float": float,
    "bool": lambda v: v if isinstance(v, bool) else str(v).lower() in ("true", "1", "yes"),
    "str": str,
    "json": lambda v: v,  # already parsed from JSON
}


class ConfigStore:
    """SQLite-backed runtime configuration store.

    All public methods are ``async``.  A single ``ConfigStore`` instance is
    created during ``create_app()`` lifespan startup and injected into routes
    via ``app.api.deps.get_config_dep``.
    """

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db
        self._cache: dict[str, Any] = {}
        """In-memory cache keyed by config key.  Populated on ``hydrate()``."""

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def hydrate(self) -> None:
        """Load all config rows from the database into the in-memory cache.

        Called once during application startup after the DB is ready.
        """
        cursor = await self._db.execute("SELECT key, value, value_type FROM config")
        rows = await cursor.fetchall()
        self._cache = {}
        for row in rows:
            try:
                self._cache[row["key"]] = self._decode(row["value"], row["value_type"])
            except Exception:
                logger.warning(
                    "Failed to decode config value",
                    extra={"key": row["key"], "raw": row["value"]},
                )
        logger.info("ConfigStore hydrated", extra={"key_count": len(self._cache)})

    async def reload(self) -> None:
        """Re-hydrate the cache from the database (hot-reload)."""
        await self.hydrate()
        logger.info("ConfigStore reloaded.")

    def key_count(self) -> int:
        """Return the number of config keys currently in the in-memory cache."""
        return len(self._cache)

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = _SENTINEL) -> Any:
        """Return the value for *key* from the in-memory cache.

        Args:
            key: Dot-namespaced config key, e.g. ``"session.idle_timeout_days"``.
            default: Value to return when *key* is absent.  If omitted and the
                key is not present, raises ``ConfigKeyNotFoundError``.

        Returns:
            The typed Python value (int, float, bool, str, or dict/list for JSON).

        Raises:
            ConfigKeyNotFoundError: When the key is absent and no default given.
        """
        if key in self._cache:
            return self._cache[key]
        if default is not _SENTINEL:
            return default
        raise ConfigKeyNotFoundError(key)

    async def all(self, category: str | None = None) -> list[dict[str, Any]]:
        """Return all config rows, optionally filtered by *category*.

        Each row is a dict with keys: ``key``, ``value``, ``value_type``,
        ``category``, ``description``, ``default_val``, ``requires_restart``.
        """
        if category:
            cursor = await self._db.execute(
                "SELECT * FROM config WHERE category = ? ORDER BY key",
                (category,),
            )
        else:
            cursor = await self._db.execute("SELECT * FROM config ORDER BY key")
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["requires_restart"] = bool(d.get("requires_restart", 0))
            result.append(d)
        return result

    # ── Write ─────────────────────────────────────────────────────────────────

    async def set(self, key: str, value: Any) -> bool:
        """Persist *key* = *value* and update the in-memory cache.

        Args:
            key: Dot-namespaced config key.
            value: Python value to persist (will be JSON-encoded).

        Returns:
            ``True`` if the update succeeded and the new value is live.
            ``False`` if the key requires a restart (value persisted but
            cannot take effect until the process restarts).

        Raises:
            ConfigKeyNotFoundError: When *key* does not exist in the table.
            ConfigValidationError: When *value* fails type/range validation.
        """
        # Fetch metadata row so we can validate the type.
        cursor = await self._db.execute(
            "SELECT value_type, requires_restart, version FROM config WHERE key = ?",
            (key,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ConfigKeyNotFoundError(key)

        value_type: str = row["value_type"]
        requires_restart: bool = bool(row["requires_restart"])
        current_version: int = row["version"]

        # Validate and encode.
        try:
            encoded = self._encode(value, value_type)
        except (TypeError, ValueError) as exc:
            raise ConfigValidationError(key, str(exc)) from exc

        # OCC update.
        async with write_transaction(self._db):
            await self._db.execute(
                """
                UPDATE config
                SET    value = ?, updated_at = datetime('now'), version = version + 1
                WHERE  key = ? AND version = ?
                """,
                (encoded, key, current_version),
            )

        # Update cache.
        self._cache[key] = self._decode(encoded, value_type)
        logger.info("Config updated", extra={"key": key, "requires_restart": requires_restart})
        return not requires_restart

    # ── Encoding / decoding ───────────────────────────────────────────────────

    @staticmethod
    def _encode(value: Any, value_type: str) -> str:
        """Encode *value* as a JSON string for storage in the ``config`` table."""
        if value_type == "bool":
            return "true" if value else "false"
        return json.dumps(value)

    @staticmethod
    def _decode(raw: str, value_type: str) -> Any:
        """Decode a raw JSON string from the ``config`` table to its Python type."""
        parsed = json.loads(raw)
        converter = _TYPE_CONVERTERS.get(value_type)
        if converter is not None:
            return converter(parsed)
        return parsed
