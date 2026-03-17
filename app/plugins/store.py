"""Database persistence layer for the plugin registry (Sprint 12, §8.0).

All mutations go through ``write_transaction()`` to serialise SQLite writes.
Credentials are stored in ``plugin_credentials`` with the plugin's own
``plugin_id`` (distinct from the ``__auth__`` sentinel used by LLM providers).
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from app.auth.encryption import decrypt_credential, encrypt_credential
from app.db.connection import write_transaction
from app.plugins.models import PluginRecord

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_record(row: aiosqlite.Row) -> PluginRecord:
    """Convert a ``plugin_credentials``-joined or plain ``plugins`` row to a ``PluginRecord``."""
    config_raw = dict(row).get("config") or "{}"
    config: dict[str, Any] = json.loads(config_raw) if isinstance(config_raw, str) else (config_raw or {})
    return PluginRecord(
        plugin_id=row["plugin_id"],
        name=row["name"],
        description=row["description"] or "",
        version=row["version"] or "1.0.0",
        plugin_type=row["plugin_type"],
        connector_type=row["connector_type"],
        config=config,
        status=row["status"],
        error_message=row["error_message"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


# ── Read operations ───────────────────────────────────────────────────────────


async def load_all_plugins(db: aiosqlite.Connection) -> list[PluginRecord]:
    """Return all plugin records from the database."""
    async with db.execute(
        "SELECT plugin_id, name, description, version, plugin_type, connector_type, "
        "config, status, error_message, created_at, updated_at FROM plugins"
    ) as cur:
        rows = await cur.fetchall()
    return [_row_to_record(r) for r in rows]


async def load_plugin(db: aiosqlite.Connection, plugin_id: str) -> PluginRecord | None:
    """Return a single plugin record, or ``None`` if not found."""
    async with db.execute(
        "SELECT plugin_id, name, description, version, plugin_type, connector_type, "
        "config, status, error_message, created_at, updated_at "
        "FROM plugins WHERE plugin_id = ?",
        (plugin_id,),
    ) as cur:
        row = await cur.fetchone()
    return _row_to_record(row) if row else None


# ── Write operations ──────────────────────────────────────────────────────────


async def save_plugin(db: aiosqlite.Connection, record: PluginRecord) -> None:
    """Insert or replace a plugin record (upsert)."""
    now = _now()
    async with write_transaction(db):
        await db.execute(
            """
            INSERT INTO plugins
              (plugin_id, name, description, version, plugin_type, connector_type,
               config, status, error_message, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (plugin_id) DO UPDATE SET
              name          = excluded.name,
              description   = excluded.description,
              version       = excluded.version,
              plugin_type   = excluded.plugin_type,
              connector_type= excluded.connector_type,
              config        = excluded.config,
              status        = excluded.status,
              error_message = excluded.error_message,
              updated_at    = excluded.updated_at
            """,
            (
                record.plugin_id,
                record.name,
                record.description,
                record.version,
                record.plugin_type,
                record.connector_type,
                json.dumps(record.config),
                record.status,
                record.error_message,
                record.created_at.isoformat(),
                now,
            ),
        )


async def update_plugin_config(
    db: aiosqlite.Connection,
    plugin_id: str,
    config: dict[str, Any],
) -> None:
    """Overwrite the config JSON for an existing plugin."""
    async with write_transaction(db):
        await db.execute(
            "UPDATE plugins SET config = ?, updated_at = ? WHERE plugin_id = ?",
            (json.dumps(config), _now(), plugin_id),
        )


async def update_plugin_status(
    db: aiosqlite.Connection,
    plugin_id: str,
    status: str,
    error_message: str | None = None,
) -> None:
    """Update ``status`` (and optionally ``error_message``) for a plugin."""
    async with write_transaction(db):
        await db.execute(
            "UPDATE plugins SET status = ?, error_message = ?, updated_at = ? WHERE plugin_id = ?",
            (status, error_message, _now(), plugin_id),
        )


async def delete_plugin(db: aiosqlite.Connection, plugin_id: str) -> bool:
    """Delete a plugin record and its credentials.  Returns ``True`` if deleted."""
    async with write_transaction(db):
        await db.execute(
            "DELETE FROM plugin_credentials WHERE plugin_id = ?",
            (plugin_id,),
        )
        cur = await db.execute(
            "DELETE FROM plugins WHERE plugin_id = ?",
            (plugin_id,),
        )
    return (cur.rowcount or 0) > 0


# ── Credential helpers ────────────────────────────────────────────────────────


async def save_credential(
    db: aiosqlite.Connection,
    plugin_id: str,
    credential_key: str,
    raw_value: str,
) -> None:
    """Encrypt *raw_value* and persist it for ``(plugin_id, credential_key)``."""
    encrypted = encrypt_credential(raw_value)
    now = _now()
    async with write_transaction(db):
        await db.execute(
            """
            INSERT INTO plugin_credentials
              (plugin_id, credential_key, encrypted_value, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (plugin_id, credential_key) DO UPDATE SET
              encrypted_value = excluded.encrypted_value,
              updated_at      = excluded.updated_at
            """,
            (plugin_id, credential_key, encrypted, now, now),
        )


async def get_credential(
    db: aiosqlite.Connection,
    plugin_id: str,
    credential_key: str,
) -> str | None:
    """Return the decrypted credential, or ``None`` if not stored."""
    async with db.execute(
        "SELECT encrypted_value FROM plugin_credentials WHERE plugin_id = ? AND credential_key = ?",
        (plugin_id, credential_key),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    try:
        return decrypt_credential(row["encrypted_value"])
    except Exception:
        logger.warning("Failed to decrypt credential for %s/%s", plugin_id, credential_key)
        return None


async def delete_credential(
    db: aiosqlite.Connection,
    plugin_id: str,
    credential_key: str,
) -> None:
    """Remove a single credential."""
    async with write_transaction(db):
        await db.execute(
            "DELETE FROM plugin_credentials WHERE plugin_id = ? AND credential_key = ?",
            (plugin_id, credential_key),
        )


# ── Auth-store callable (passed to PluginBase.configure()) ────────────────────


def make_auth_store(db: aiosqlite.Connection):
    """Return an async callable ``(plugin_id, key) -> str | None`` for use by plugins.

    Usage inside ``PluginBase.configure()``::

        token = await auth_store("telegram", "bot_token")
    """

    async def _auth_store(plugin_id: str, credential_key: str) -> str | None:
        return await get_credential(db, plugin_id, credential_key)

    return _auth_store
