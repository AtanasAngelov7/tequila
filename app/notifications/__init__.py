"""Notification system for Tequila v2 (§24.1–24.5).

Provides:
  - ``Notification`` model and store (CRUD).
  - ``NotificationPreference`` model and preference store.
  - ``NotificationDispatcher`` — subscribes to gateway events and dispatches
    to enabled channels (in-app, system, email, telegram).
  - Proactive session injection (§24.5): some notification types inject a
    system message into the active webchat session so the main agent is aware.

Usage::

    # At startup (called by app.py lifespan):
    notif_store = init_notification_store(db)
    dispatcher = init_notification_dispatcher(db, router)

    # When an event fires, the dispatcher auto-handles it via router.on()
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

import aiosqlite
from pydantic import BaseModel, Field

from app.db.connection import write_transaction

logger = logging.getLogger(__name__)


# ── Models ────────────────────────────────────────────────────────────────────


class Notification(BaseModel):
    """A user-facing notification (§24.1)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    notification_type: str
    """Matches §24.1 type strings (e.g. ``"agent.run.error"``)."""
    title: str
    body: str
    severity: Literal["info", "warning", "error"] = "info"
    action_url: str | None = None
    source_session_key: str | None = None
    read: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "notification_type": self.notification_type,
            "title": self.title,
            "body": self.body,
            "severity": self.severity,
            "action_url": self.action_url,
            "source_session_key": self.source_session_key,
            "read": int(self.read),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Notification":
        d = dict(row)
        d["read"] = bool(d.get("read", 0))
        if d.get("created_at") and isinstance(d["created_at"], str):
            d["created_at"] = datetime.fromisoformat(d["created_at"])
        return cls.model_validate(d)


class NotificationPreference(BaseModel):
    """Per-type channel preference (§24.3)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    notification_type: str
    """Notification type string, or ``"*"`` for default fallback."""
    channels: list[Literal["in_app", "system", "email", "telegram"]] = Field(
        default_factory=lambda: ["in_app"]
    )
    enabled: bool = True

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "notification_type": self.notification_type,
            "channels": json.dumps(self.channels),
            "enabled": int(self.enabled),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "NotificationPreference":
        d = dict(row)
        if isinstance(d.get("channels"), str):
            try:
                d["channels"] = json.loads(d["channels"])
            except Exception:
                d["channels"] = ["in_app"]
        d["enabled"] = bool(d.get("enabled", 1))
        return cls.model_validate(d)


# ── Default preferences ───────────────────────────────────────────────────────

DEFAULT_PREFERENCES: list[dict[str, Any]] = [
    {"notification_type": "*", "channels": ["in_app"], "enabled": True},
    {"notification_type": "agent.run.error", "channels": ["in_app", "system"], "enabled": True},
    {"notification_type": "budget.warning", "channels": ["in_app", "system"], "enabled": True},
    {"notification_type": "budget.exceeded", "channels": ["in_app", "system"], "enabled": True},
    {"notification_type": "backup.complete", "channels": ["in_app"], "enabled": True},
    {"notification_type": "backup.failed", "channels": ["in_app", "system"], "enabled": True},
    {"notification_type": "plugin.error", "channels": ["in_app", "system"], "enabled": True},
    {"notification_type": "plugin.deactivated", "channels": ["in_app"], "enabled": True},
    {"notification_type": "inbound.message", "channels": ["in_app", "system"], "enabled": True},
    {"notification_type": "scheduler.skipped", "channels": ["in_app"], "enabled": False},
]

# Notification types that inject a system message into the active session (§24.5)
SESSION_INJECT_TEMPLATES: dict[str, str] = {
    "agent.run.complete": "[Background task completed] {body}",
    "inbound.message": "[New message] {body}",
    "budget.exceeded": "[Budget alert] {body}",
    "backup.failed": "[Backup alert] {body}",
    "plugin.deactivated": "[Plugin alert] {body}",
}


# ── NotificationStore ─────────────────────────────────────────────────────────


class NotificationStore:
    """CRUD for the ``notifications`` and ``notification_preferences`` tables."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # -- Notifications ---------------------------------------------------------

    async def create(self, notification: Notification) -> Notification:
        row = notification.to_row()
        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT INTO notifications
                    (id, notification_type, title, body, severity,
                     action_url, source_session_key, read, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (row["id"], row["notification_type"], row["title"], row["body"],
                 row["severity"], row["action_url"], row["source_session_key"],
                 row["read"], row["created_at"]),
            )
        return notification

    async def list(
        self,
        *,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Notification]:
        where = "WHERE read = 0" if unread_only else ""
        cursor = await self._db.execute(
            f"""
            SELECT id, notification_type, title, body, severity,
                   action_url, source_session_key, read, created_at
            FROM notifications
            {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [Notification.from_row(dict(r)) for r in rows]

    async def mark_read(self, notification_id: str) -> bool:
        async with write_transaction(self._db):
            await self._db.execute(
                "UPDATE notifications SET read = 1 WHERE id = ?",
                (notification_id,),
            )
        return True

    async def mark_all_read(self) -> int:
        async with write_transaction(self._db):
            cursor = await self._db.execute(
                "UPDATE notifications SET read = 1 WHERE read = 0"
            )
            return cursor.rowcount

    async def count_unread(self) -> int:
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM notifications WHERE read = 0"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    # -- Preferences -----------------------------------------------------------

    async def seed_default_preferences(self) -> None:
        """Insert default preferences if not already present."""
        for pref_data in DEFAULT_PREFERENCES:
            pref = NotificationPreference(**pref_data)
            row = pref.to_row()
            async with write_transaction(self._db):
                await self._db.execute(
                    """
                    INSERT OR IGNORE INTO notification_preferences
                        (id, notification_type, channels, enabled, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (row["id"], row["notification_type"], row["channels"],
                     row["enabled"], row["updated_at"]),
                )

    async def get_preference(self, notification_type: str) -> NotificationPreference | None:
        """Get preference for exact type, then fall back to ``"*"``."""
        cursor = await self._db.execute(
            "SELECT id, notification_type, channels, enabled, updated_at "
            "FROM notification_preferences WHERE notification_type = ?",
            (notification_type,),
        )
        row = await cursor.fetchone()
        if row:
            return NotificationPreference.from_row(dict(row))
        # Try wildcard
        cursor = await self._db.execute(
            "SELECT id, notification_type, channels, enabled, updated_at "
            "FROM notification_preferences WHERE notification_type = '*'",
        )
        row = await cursor.fetchone()
        return NotificationPreference.from_row(dict(row)) if row else None

    async def list_preferences(self) -> list[NotificationPreference]:
        cursor = await self._db.execute(
            "SELECT id, notification_type, channels, enabled, updated_at "
            "FROM notification_preferences ORDER BY notification_type"
        )
        rows = await cursor.fetchall()
        return [NotificationPreference.from_row(dict(r)) for r in rows]

    async def upsert_preference(self, pref: NotificationPreference) -> NotificationPreference:
        row = pref.to_row()
        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT INTO notification_preferences
                    (id, notification_type, channels, enabled, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(notification_type) DO UPDATE SET
                    channels = excluded.channels,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (row["id"], row["notification_type"], row["channels"],
                 row["enabled"], row["updated_at"]),
            )
        return pref


# ── NotificationDispatcher ────────────────────────────────────────────────────


class NotificationDispatcher:
    """Listens to gateway events and dispatches notifications (§24.5).

    Subscribes to all notification-relevant gateway events through the router.
    For each event, builds a ``Notification``, looks up delivery preferences,
    and dispatches to enabled channels.
    """

    # Mapping from gateway event type → (notification_type, severity, title_template)
    _EVENT_MAP: dict[str, tuple[str, str, str]] = {
        "agent.run.error": ("agent.run.error", "error", "Agent error"),
        "agent.run.complete": ("agent.run.complete", "info", "Agent task complete"),
        "budget.warning": ("budget.warning", "warning", "Budget warning"),
        "budget.exceeded": ("budget.exceeded", "error", "Budget limit reached"),
        "plugin.error": ("plugin.error", "error", "Plugin error"),
        "plugin.deactivated": ("plugin.deactivated", "warning", "Plugin deactivated"),
        "scheduler.skipped": ("scheduler.skipped", "warning", "Scheduler job skipped"),
        "notification.push": ("_passthrough", "info", ""),  # internal passthrough
        "inbound.message": ("inbound.message", "info", "Incoming message"),
    }

    def __init__(self, store: NotificationStore, router: Any) -> None:
        self._store = store
        self._router = router

    def register(self) -> None:
        """Subscribe to relevant gateway events."""
        for event_type in self._EVENT_MAP:
            if event_type != "notification.push":
                try:
                    self._router.on(event_type, self._handle_event)
                except Exception:
                    pass  # Router may reject unknown event types in strict mode

    async def _handle_event(self, event: Any) -> None:
        """Gateway event handler — converts to Notification and dispatches."""
        event_type = getattr(event, "event_type", None) or (event.get("event_type") if isinstance(event, dict) else None)
        if not event_type:
            return

        mapping = self._EVENT_MAP.get(event_type)
        if not mapping:
            return

        notification_type, severity, title_template = mapping
        payload = getattr(event, "payload", {}) or (event.get("payload", {}) if isinstance(event, dict) else {})

        # Build body from payload
        body = payload.get("error", payload.get("body", payload.get("message", str(payload)[:200] if payload else "")))
        title = title_template or notification_type

        await self.dispatch(
            notification_type=notification_type,
            title=title,
            body=str(body),
            severity=severity,
            source_session_key=payload.get("session_key"),
        )

    async def dispatch(
        self,
        *,
        notification_type: str,
        title: str,
        body: str,
        severity: Literal["info", "warning", "error"] = "info",
        action_url: str | None = None,
        source_session_key: str | None = None,
    ) -> Notification:
        """Create and dispatch a notification through all enabled channels."""
        # Persist notification
        notif = Notification(
            notification_type=notification_type,
            title=title,
            body=body,
            severity=severity,
            action_url=action_url,
            source_session_key=source_session_key,
        )
        await self._store.create(notif)

        # Look up delivery preference
        pref = await self._store.get_preference(notification_type)
        if not pref or not pref.enabled:
            return notif

        # Dispatch to each channel
        for channel in pref.channels:
            try:
                await self._dispatch_channel(channel, notif)
            except Exception as exc:
                logger.warning("Failed to dispatch notification via %s: %s", channel, exc, exc_info=True)

        # Proactive session injection (§24.5)
        if notification_type in SESSION_INJECT_TEMPLATES:
            await self._inject_session(notif)

        return notif

    async def _dispatch_channel(
        self, channel: str, notif: Notification
    ) -> None:
        if channel == "in_app":
            # Push to frontend via gateway notification.push event
            from app.gateway.events import GatewayEvent, EventSource, ET
            event = GatewayEvent(
                event_type=ET.NOTIFICATION_PUSH,
                source=EventSource(kind="system", id="notifications"),
                session_key="*",  # broadcast to all connected clients
                payload={
                    "notification_id": notif.id,
                    "notification_type": notif.notification_type,
                    "title": notif.title,
                    "body": notif.body,
                    "severity": notif.severity,
                    "action_url": notif.action_url,
                    "created_at": notif.created_at.isoformat(),
                },
            )
            try:
                await self._router.emit(event)
            except Exception as exc:
                logger.debug("Could not emit in-app notification: %s", exc)
        elif channel == "system":
            # System notifications are handled client-side when the frontend
            # receives the notification.push event with a system flag.
            # Nothing extra needed server-side.
            pass
        # email / telegram: would call respective plugin send tools here
        # Deferred to Phase 7 deep plugin integration

    async def _inject_session(self, notif: Notification) -> None:
        """Inject a system message into the active webchat session."""
        template = SESSION_INJECT_TEMPLATES.get(notif.notification_type, "")
        if not template:
            return
        inject_text = template.format(title=notif.title, body=notif.body)
        try:
            from app.sessions.store import get_session_store
            from app.sessions.messages import get_message_store
            ss = get_session_store()
            ms = get_message_store()
            # Find the most recently active webchat session
            sessions = await ss.list_sessions(kind="webchat", limit=1)
            if not sessions:
                return
            active = sessions[0]
            await ms.insert(
                session_id=active.session_id,
                role="system",
                content=inject_text,
                provenance="notification_injection",
                active=True,
            )
        except Exception as exc:
            logger.debug("Proactive session injection failed: %s", exc)


# ── Singletons ────────────────────────────────────────────────────────────────

_store: NotificationStore | None = None
_dispatcher: NotificationDispatcher | None = None


def init_notification_store(db: aiosqlite.Connection) -> NotificationStore:
    global _store
    _store = NotificationStore(db)
    return _store


def get_notification_store() -> NotificationStore:
    if _store is None:
        raise RuntimeError("NotificationStore not initialised — call init_notification_store() first")
    return _store


def init_notification_dispatcher(db: aiosqlite.Connection, router: Any) -> NotificationDispatcher:
    global _dispatcher
    store = get_notification_store()
    _dispatcher = NotificationDispatcher(store=store, router=router)
    _dispatcher.register()
    return _dispatcher


def get_notification_dispatcher() -> NotificationDispatcher:
    if _dispatcher is None:
        raise RuntimeError("NotificationDispatcher not initialised")
    return _dispatcher
