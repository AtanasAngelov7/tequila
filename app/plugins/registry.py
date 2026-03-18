"""In-memory plugin registry + health polling loop (Sprint 12, §8.0, §8.7).

``PluginRegistry`` is a singleton that:
- Holds live ``PluginBase`` instances keyed by ``plugin_id``.
- Loads persisted ``PluginRecord``s from the ``plugins`` table on startup.
- Activates all plugins whose ``status == "active"``.
- Runs a periodic health-check loop (every 5 minutes) and auto-disables
  plugins that report unhealthy three times in a row.

Usage (inside FastAPI lifespan)::

    registry = await init_plugin_registry(db)
    await registry.start()
    ...
    await registry.stop()
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import aiosqlite

from app.plugins.base import PluginBase
from app.plugins.models import PluginHealthResult, PluginRecord
from app.plugins.store import (
    delete_plugin,
    load_all_plugins,
    load_plugin,
    make_auth_store,
    save_plugin,
    update_plugin_config,
    update_plugin_status,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_HEALTH_INTERVAL_SECONDS = 300  # 5 minutes
_HEALTH_FAILURE_THRESHOLD = 3   # consecutive failures before auto-disable

# ── Module-level singleton ────────────────────────────────────────────────────

_plugin_registry: PluginRegistry | None = None


def get_plugin_registry() -> PluginRegistry:
    """Return the initialised ``PluginRegistry``.

    Raises ``RuntimeError`` if ``init_plugin_registry()`` hasn't been called.
    """
    if _plugin_registry is None:
        raise RuntimeError("PluginRegistry not initialised. Call init_plugin_registry() first.")
    return _plugin_registry


async def init_plugin_registry(db: aiosqlite.Connection) -> PluginRegistry:
    """Create (or reset) the singleton ``PluginRegistry`` with *db*.

    If the existing singleton holds a different (closed) connection, it is
    replaced so that each app lifespan gets a fresh, correctly-wired registry.
    """
    global _plugin_registry  # noqa: PLW0603
    if _plugin_registry is None or _plugin_registry._db is not db:
        _plugin_registry = PluginRegistry(db)
    return _plugin_registry


# ── Registry class ────────────────────────────────────────────────────────────


class PluginRegistry:
    """Central manager for all plugin instances."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db
        # plugin_id → live PluginBase instance
        self._instances: dict[str, PluginBase] = {}
        # plugin_id → persisted PluginRecord (authoritative DB state)
        self._records: dict[str, PluginRecord] = {}
        # consecutive health-check failure count per plugin
        self._health_failures: dict[str, int] = {}
        self._health_task: asyncio.Task[None] | None = None
        self._started = False
        # TD-186: Initialize _gateway so attribute is always present
        self._gateway: Any | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self, gateway: Any = None) -> None:
        """Load DB state, re-activate 'active' plugins, start health loop."""
        if self._started:
            return
        self._started = True
        self._gateway = gateway

        # Register all built-ins (noop if already registered)
        _register_builtins(self)

        # Load persisted records
        records = await load_all_plugins(self._db)
        for rec in records:
            self._records[rec.plugin_id] = rec

        # Re-activate plugins that were active before restart
        auth_store = make_auth_store(self._db)
        for rec in records:
            if rec.status == "active" and rec.plugin_id in self._instances:
                instance = self._instances[rec.plugin_id]
                try:
                    await instance.initialize(gateway)
                    await instance.configure(rec.config, auth_store)
                    await instance.activate()
                    logger.info("Plugin %r reactivated on startup.", rec.plugin_id)
                except Exception as exc:
                    logger.exception("Failed to reactivate plugin %r: %s", rec.plugin_id, exc)
                    await update_plugin_status(self._db, rec.plugin_id, "error", str(exc))
                    self._records[rec.plugin_id] = rec.model_copy(
                        update={"status": "error", "error_message": str(exc)}
                    )

        self._health_task = asyncio.create_task(self._health_loop(), name="plugin-health-loop")
        logger.info("PluginRegistry started (%d plugins loaded).", len(records))

    async def stop(self) -> None:
        """Gracefully deactivate all plugins and cancel the health loop."""
        if not self._started:
            return
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        for plugin_id, instance in list(self._instances.items()):
            rec = self._records.get(plugin_id)
            if rec and rec.status == "active":
                try:
                    await instance.deactivate()
                    logger.info("Plugin %r deactivated on shutdown.", plugin_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Error deactivating plugin %r: %s", plugin_id, exc)

        self._started = False
        logger.info("PluginRegistry stopped.")
        # Reset the module-level singleton so the next lifespan gets a fresh registry.
        global _plugin_registry  # noqa: PLW0603
        if _plugin_registry is self:
            _plugin_registry = None

    # ── Plugin class registration (called at import time by builtins) ─────────

    def register_class(self, plugin_class: type[PluginBase]) -> None:
        """Register a built-in plugin class (NOT a live instance).

        If a persisted record exists for this plugin_id, the instance will
        be activated when ``start()`` is called (if status == 'active').
        """
        plugin_id = plugin_class.plugin_id
        if plugin_id not in self._instances:
            self._instances[plugin_id] = plugin_class()  # type: ignore[call-arg]
            logger.debug("Registered plugin class %r.", plugin_id)

    # ── Install / configure / activate / deactivate ───────────────────────────

    async def install(self, plugin_class: type[PluginBase]) -> PluginRecord:
        """Register a plugin class and persist a new DB record (status='installed')."""
        plugin_id = plugin_class.plugin_id
        self._instances[plugin_id] = plugin_class()  # type: ignore[call-arg]

        now = datetime.now(UTC)
        record = PluginRecord(
            plugin_id=plugin_id,
            name=plugin_class.name,
            description=plugin_class.description,
            version=plugin_class.version,
            plugin_type=plugin_class.plugin_type,
            connector_type=getattr(plugin_class, "connector_type", None),
            config={},
            status="installed",
            created_at=now,
            updated_at=now,
        )
        await save_plugin(self._db, record)
        self._records[plugin_id] = record
        logger.info("Plugin %r installed.", plugin_id)
        return record

    async def configure_plugin(
        self,
        plugin_id: str,
        config: dict[str, Any],
    ) -> PluginRecord:
        """Persist new config and attempt a configure() cycle."""
        instance = self._get_instance(plugin_id)
        await update_plugin_config(self._db, plugin_id, config)
        auth_store = make_auth_store(self._db)
        try:
            await instance.configure(config, auth_store)
            await update_plugin_status(self._db, plugin_id, "configured")
            self._records[plugin_id] = self._records[plugin_id].model_copy(
                update={"config": config, "status": "configured", "error_message": None}
            )
        except Exception as exc:
            await update_plugin_status(self._db, plugin_id, "error", str(exc))
            self._records[plugin_id] = self._records[plugin_id].model_copy(
                update={"status": "error", "error_message": str(exc)}
            )
            raise
        return self._records[plugin_id]

    async def activate_plugin(self, plugin_id: str) -> PluginRecord:
        """Call ``activate()`` and update DB status to 'active'."""
        instance = self._get_instance(plugin_id)
        rec = self._records.get(plugin_id)
        if rec is None:
            raise KeyError(f"Plugin {plugin_id!r} not found in registry.")

        auth_store = make_auth_store(self._db)
        try:
            await instance.initialize(getattr(self, "_gateway", None))
            await instance.configure(rec.config, auth_store)
            await instance.activate()
            await update_plugin_status(self._db, plugin_id, "active")
            self._records[plugin_id] = rec.model_copy(update={"status": "active", "error_message": None})
            self._health_failures[plugin_id] = 0
        except Exception as exc:
            await update_plugin_status(self._db, plugin_id, "error", str(exc))
            self._records[plugin_id] = rec.model_copy(update={"status": "error", "error_message": str(exc)})
            raise
        return self._records[plugin_id]

    async def deactivate_plugin(self, plugin_id: str) -> PluginRecord:
        """Call ``deactivate()`` and update DB status to 'configured' (or 'installed')."""
        instance = self._get_instance(plugin_id)
        await instance.deactivate()
        rec = self._records.get(plugin_id)
        new_status = "configured" if rec and rec.config else "installed"
        await update_plugin_status(self._db, plugin_id, new_status)
        if rec:
            self._records[plugin_id] = rec.model_copy(update={"status": new_status})
        return self._records[plugin_id]

    async def uninstall(self, plugin_id: str) -> None:
        """Deactivate (if active), delete DB record, and remove instance."""
        if plugin_id in self._instances:
            rec = self._records.get(plugin_id)
            if rec and rec.status == "active":
                try:
                    await self._instances[plugin_id].deactivate()
                except Exception:  # noqa: BLE001
                    pass
            del self._instances[plugin_id]
        self._records.pop(plugin_id, None)
        self._health_failures.pop(plugin_id, None)
        await delete_plugin(self._db, plugin_id)
        logger.info("Plugin %r uninstalled.", plugin_id)

    # ── Read helpers ──────────────────────────────────────────────────────────

    def list_records(self) -> list[PluginRecord]:
        """Return all in-memory plugin records (in insertion order)."""
        return list(self._records.values())

    def refresh_records(self, records: list[PluginRecord]) -> None:
        """Replace in-memory plugin records (TD-173: public API for refresh_plugins)."""
        for rec in records:
            self._records[rec.plugin_id] = rec

    def get_record(self, plugin_id: str) -> PluginRecord | None:
        return self._records.get(plugin_id)

    def get_instance(self, plugin_id: str) -> PluginBase | None:
        return self._instances.get(plugin_id)

    def list_tools(self) -> list[Any]:
        """Collect tools from all active plugins (synchronous view).

        .. deprecated:: Use ``get_all_active_tools()`` for a complete list.
        """
        logger.debug("list_tools() is synchronous and returns cached data; "
                     "prefer get_all_active_tools() for an up-to-date view.")
        return self._cached_tools
    _cached_tools: list[Any] = []

    async def get_all_active_tools(self) -> list[Any]:
        """Gather tools from all active plugin instances."""
        tools: list[Any] = []
        for plugin_id, instance in self._instances.items():
            rec = self._records.get(plugin_id)
            if rec and rec.status == "active":
                try:
                    tools.extend(await instance.get_tools())
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Error getting tools from plugin %r: %s", plugin_id, exc)
        self._cached_tools = tools  # TD-185: Update synchronous cache
        return tools

    # ── Health loop ───────────────────────────────────────────────────────────

    async def _health_loop(self) -> None:
        """Run health checks every ``_HEALTH_INTERVAL_SECONDS``."""
        while True:
            try:
                await asyncio.sleep(_HEALTH_INTERVAL_SECONDS)
                await self._run_health_checks()
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("Health loop error: %s", exc)

    async def _run_health_checks(self) -> None:
        """Check health of all active plugins; auto-disable on repeated failure.

        TD-169: Runs checks concurrently with a per-check timeout.
        """
        async def _check_one(plugin_id: str, instance: Any) -> None:
            try:
                result: PluginHealthResult = await asyncio.wait_for(
                    instance.health_check(), timeout=10.0
                )
                if result.healthy:
                    self._health_failures[plugin_id] = 0
                else:
                    await self._record_failure(plugin_id, result.message or "unhealthy")
            except asyncio.TimeoutError:
                await self._record_failure(plugin_id, "health check timed out")
            except Exception as exc:  # noqa: BLE001
                await self._record_failure(plugin_id, str(exc))

        checks = []
        for plugin_id, instance in list(self._instances.items()):
            rec = self._records.get(plugin_id)
            if not rec or rec.status != "active":
                continue
            checks.append(_check_one(plugin_id, instance))
        if checks:
            await asyncio.gather(*checks, return_exceptions=True)

    async def _record_failure(self, plugin_id: str, reason: str) -> None:
        count = self._health_failures.get(plugin_id, 0) + 1
        self._health_failures[plugin_id] = count
        logger.warning("Plugin %r health failure #%d: %s", plugin_id, count, reason)
        if count >= _HEALTH_FAILURE_THRESHOLD:
            logger.error(
                "Plugin %r exceeded %d consecutive health failures — disabling.",
                plugin_id,
                _HEALTH_FAILURE_THRESHOLD,
            )
            await update_plugin_status(self._db, plugin_id, "error", f"Health check failed: {reason}")
            rec = self._records.get(plugin_id)
            if rec:
                self._records[plugin_id] = rec.model_copy(
                    update={"status": "error", "error_message": f"Health check failed: {reason}"}
                )
            try:
                await self._instances[plugin_id].deactivate()
            except Exception:  # noqa: BLE001
                pass

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_instance(self, plugin_id: str) -> PluginBase:
        instance = self._instances.get(plugin_id)
        if instance is None:
            raise KeyError(f"Plugin {plugin_id!r} is not registered.")
        return instance


# ── Built-in plugin auto-registration ────────────────────────────────────────


def _register_builtins(registry: PluginRegistry) -> None:
    """Register all built-in plugin classes with *registry*."""
    # Import here to avoid circular imports at module load time.
    try:
        from app.plugins.builtin.telegram.plugin import TelegramPlugin
        registry.register_class(TelegramPlugin)
    except ImportError as exc:
        if exc.name and "telegram" not in exc.name:
            raise

    try:
        from app.plugins.builtin.gmail.plugin import GmailPlugin
        registry.register_class(GmailPlugin)
    except ImportError as exc:
        if exc.name and "gmail" not in exc.name:
            raise

    try:
        from app.plugins.builtin.smtp_imap.plugin import SmtpImapPlugin
        registry.register_class(SmtpImapPlugin)
    except ImportError as exc:
        if exc.name and "smtp_imap" not in exc.name:
            raise

    try:
        from app.plugins.builtin.google_calendar.plugin import GoogleCalendarPlugin
        registry.register_class(GoogleCalendarPlugin)
    except ImportError as exc:
        if exc.name and "google_calendar" not in exc.name:
            raise

    try:
        from app.plugins.builtin.webhooks.plugin import WebhooksPlugin
        registry.register_class(WebhooksPlugin)
    except ImportError as exc:
        if exc.name and "webhooks" not in exc.name:
            raise

    try:
        from app.plugins.builtin.documents.plugin import DocumentsPlugin
        registry.register_class(DocumentsPlugin)
    except ImportError as exc:
        if exc.name and "documents" not in exc.name:
            raise

    try:
        from app.plugins.builtin.browser.plugin import BrowserPlugin
        registry.register_class(BrowserPlugin)
    except ImportError as exc:
        if exc.name and "browser" not in exc.name:
            raise

    try:
        from app.plugins.mcp.plugin import MCPPlugin
        registry.register_class(MCPPlugin)
    except ImportError as exc:
        if exc.name and "mcp" not in exc.name:
            raise
