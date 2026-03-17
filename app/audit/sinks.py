"""Audit sinks and retention management for Tequila v2 (§12.1–12.3 Sprint 14b).

Extends the existing audit foundation from Sprint 01 (``app.audit.log``) with:
  - Configurable sinks: SQLite (default), file (JSON-lines), webhook (POST)
  - Retention policies: per-sink days/max-events pruning
  - ``AuditSinkManager`` — routes ``write_audit_event`` calls to registered sinks
    and applies retention on startup.

Usage::

    manager = init_audit_sink_manager(db)
    await manager.apply_retention()
    # All future write_audit_event() calls are automatically routed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import aiosqlite
from pydantic import BaseModel, Field

from app.db.connection import write_transaction

logger = logging.getLogger(__name__)


# ── Models ────────────────────────────────────────────────────────────────────


class AuditSink(BaseModel):
    """Configuration for one audit sink (§12.1)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: Literal["sqlite", "file", "webhook"]
    name: str
    config: dict[str, Any] = Field(default_factory=dict)
    """Kind-specific config:
      - file: ``{"path": "data/logs/audit.jsonl"}``
      - webhook: ``{"url": "https://...", "headers": {...}}``
      - sqlite: no extra config needed.
    """
    enabled: bool = True
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "config": json.dumps(self.config),
            "enabled": int(self.enabled),
            "created_at": self.created_at,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "AuditSink":
        d = dict(row)
        if isinstance(d.get("config"), str):
            try:
                d["config"] = json.loads(d["config"])
            except Exception:
                d["config"] = {}
        d["enabled"] = bool(d.get("enabled", 1))
        return cls.model_validate(d)


class AuditRetention(BaseModel):
    """Retention policy for a sink (§12.3)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sink_id: str
    retain_days: int = 90
    max_events: int | None = None


# ── AuditSinkManager ──────────────────────────────────────────────────────────


class AuditSinkManager:
    """Manages multiple audit sinks and applies retention policies.

    After ``init_audit_sink_manager()`` is called the singleton is used by
    ``app.audit.log.write_audit_event`` (via monkey-patching at startup) to
    fan-out audit events to all enabled sinks.
    """

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db
        # TD-166: Shared httpx client for webhook sinks
        self._http_client: Any | None = None
        # TD-167: In-memory cache for sink list (invalidated on create/update/delete)
        self._sink_cache: list[AuditSink] | None = None

    def _get_http_client(self) -> Any:
        """Return (creating if necessary) a shared httpx.AsyncClient."""
        if self._http_client is None:
            import httpx
            self._http_client = httpx.AsyncClient(timeout=5.0)
        return self._http_client

    def _get_cached_sinks(self) -> list[AuditSink] | None:
        """Return cached sink list or None if cache is empty."""
        return self._sink_cache

    def _invalidate_sink_cache(self) -> None:
        """Clear the cached sink list so it's refreshed on next route_event."""
        self._sink_cache = None

    async def close(self) -> None:
        """Close shared resources (call during shutdown)."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    # ── Sink CRUD ─────────────────────────────────────────────────────────

    async def seed_default_sinks(self) -> None:
        """Ensure the default SQLite sink exists."""
        existing = await self.list_sinks()
        names = {s.name for s in existing}
        if "sqlite_default" not in names:
            await self.create_sink(AuditSink(
                name="sqlite_default",
                kind="sqlite",
                config={},
                enabled=True,
            ))
            # Add a default retention policy: 90 days
            sinks = await self.list_sinks()
            for s in sinks:
                if s.name == "sqlite_default":
                    await self.set_retention(AuditRetention(sink_id=s.id, retain_days=90))
                    break

    async def create_sink(self, sink: AuditSink) -> AuditSink:
        row = sink.to_row()
        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT OR IGNORE INTO audit_sinks
                    (id, kind, name, config, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (row["id"], row["kind"], row["name"], row["config"],
                 row["enabled"], row["created_at"]),
            )
        self._invalidate_sink_cache()
        return sink

    async def get_sink(self, sink_id: str) -> AuditSink:
        cursor = await self._db.execute(
            "SELECT id, kind, name, config, enabled, created_at "
            "FROM audit_sinks WHERE id = ?",
            (sink_id,),
        )
        row = await cursor.fetchone()
        if not row:
            raise KeyError(f"Sink {sink_id!r} not found")
        return AuditSink.from_row(dict(row))

    async def list_sinks(self) -> list[AuditSink]:
        cursor = await self._db.execute(
            "SELECT id, kind, name, config, enabled, created_at "
            "FROM audit_sinks ORDER BY name"
        )
        rows = await cursor.fetchall()
        return [AuditSink.from_row(dict(r)) for r in rows]

    async def update_sink(self, sink_id: str, **kwargs: Any) -> AuditSink:
        sink = await self.get_sink(sink_id)
        updated = sink.model_copy(update=kwargs)
        row = updated.to_row()
        async with write_transaction(self._db):
            await self._db.execute(
                "UPDATE audit_sinks SET kind=?, name=?, config=?, enabled=? WHERE id=?",
                (row["kind"], row["name"], row["config"], row["enabled"], sink_id),
            )
        self._invalidate_sink_cache()
        return updated

    async def delete_sink(self, sink_id: str) -> None:
        async with write_transaction(self._db):
            await self._db.execute("DELETE FROM audit_sinks WHERE id = ?", (sink_id,))
        self._invalidate_sink_cache()

    # ── Retention ─────────────────────────────────────────────────────────

    async def set_retention(self, policy: AuditRetention) -> AuditRetention:
        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT INTO audit_retention (id, sink_id, retain_days, max_events, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(sink_id) DO UPDATE SET
                    retain_days = excluded.retain_days,
                    max_events = excluded.max_events,
                    updated_at = excluded.updated_at
                """,
                (policy.id, policy.sink_id, policy.retain_days, policy.max_events,
                 datetime.now(timezone.utc).isoformat()),
            )
        return policy

    async def get_retention(self, sink_id: str) -> AuditRetention | None:
        cursor = await self._db.execute(
            "SELECT id, sink_id, retain_days, max_events FROM audit_retention WHERE sink_id = ?",
            (sink_id,),
        )
        row = await cursor.fetchone()
        return AuditRetention.model_validate(dict(row)) if row else None

    async def apply_retention(self) -> dict[str, int]:
        """Prune old audit events per sink retention policies.

        Returns a dict mapping sink_id → number of rows deleted.
        """
        from app.audit.log import query_audit_log
        sinks = await self.list_sinks()
        deleted: dict[str, int] = {}
        for sink in sinks:
            policy = await self.get_retention(sink.id)
            if not policy:
                continue
            n = await self._prune_sqlite_sink(policy)
            deleted[sink.id] = n
        return deleted

    async def _prune_sqlite_sink(self, policy: AuditRetention) -> int:
        """Delete audit_log rows older than retain_days or over max_events."""
        total_deleted = 0

        if policy.retain_days > 0:
            cutoff_ts = (
                datetime.now(timezone.utc)
                .replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
            )
            from datetime import timedelta
            cutoff_ts = cutoff_ts - timedelta(days=policy.retain_days)
            async with write_transaction(self._db):
                cursor = await self._db.execute(
                    "DELETE FROM audit_log WHERE created_at < ?",
                    (cutoff_ts.isoformat(),),
                )
                total_deleted += cursor.rowcount or 0

        if policy.max_events:
            cursor = await self._db.execute(
                "SELECT COUNT(*) FROM audit_log"
            )
            row = await cursor.fetchone()
            count = row[0] if row else 0
            excess = count - policy.max_events
            if excess > 0:
                async with write_transaction(self._db):
                    cursor = await self._db.execute(
                        """
                        DELETE FROM audit_log WHERE id IN (
                            SELECT id FROM audit_log
                            ORDER BY created_at ASC
                            LIMIT ?
                        )
                        """,
                        (excess,),
                    )
                    total_deleted += cursor.rowcount or 0

        if total_deleted > 0:
            logger.info(
                "AuditSinkManager: pruned %d audit_log rows", total_deleted
            )
        return total_deleted

    # ── Event fan-out to non-SQLite sinks ─────────────────────────────────

    async def route_event(self, event: Any) -> None:
        """Fan-out an AuditEvent to all enabled non-SQLite sinks."""
        # TD-167: Use cached sink list instead of DB query on every event
        sinks = self._get_cached_sinks()
        if sinks is None:
            sinks = await self.list_sinks()
            self._sink_cache = sinks
        event_dict = event.model_dump() if hasattr(event, "model_dump") else dict(event)
        # Serialise datetime fields
        for k, v in event_dict.items():
            if hasattr(v, "isoformat"):
                event_dict[k] = v.isoformat()

        for sink in sinks:
            if not sink.enabled or sink.kind == "sqlite":
                continue
            try:
                if sink.kind == "file":
                    await self._route_to_file(sink, event_dict)
                elif sink.kind == "webhook":
                    await self._route_to_webhook(sink, event_dict)
            except Exception as exc:
                logger.warning(
                    "Audit sink %r (%s) error: %s", sink.name, sink.kind, exc,
                    exc_info=True,
                )

    async def _route_to_file(self, sink: AuditSink, event: dict[str, Any]) -> None:
        path_str = sink.config.get("path", "data/logs/audit.jsonl")
        path = Path(path_str)
        # TD-144: Validate path is within allowed base directory
        allowed_base = Path("data/logs").resolve()
        try:
            resolved = path.resolve()
        except (OSError, ValueError):
            logger.warning("Audit file sink: invalid path %r", path_str)
            return
        if not str(resolved).startswith(str(allowed_base)):
            logger.warning("Audit file sink: path %r is outside allowed base %s", path_str, allowed_base)
            return
        resolved.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, default=str) + "\n"
        # TD-145: Use proper with-statement to avoid file handle leak
        def _append(p: Path, data: str) -> None:
            with p.open("a", encoding="utf-8") as f:
                f.write(data)
        await asyncio.to_thread(_append, resolved, line)

    async def _route_to_webhook(self, sink: AuditSink, event: dict[str, Any]) -> None:
        url = sink.config.get("url")
        if not url:
            return
        # TD-150: Block SSRF to private/link-local IP ranges
        import ipaddress
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname or ""
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                logger.warning("Webhook SSRF blocked: %r resolves to private/reserved IP", url)
                return
        except ValueError:
            pass  # Not an IP literal — hostname will be resolved by httpx
        headers = {"Content-Type": "application/json", **sink.config.get("headers", {})}
        try:
            # TD-166: Reuse shared httpx client instead of creating one per event
            client = self._get_http_client()
            await client.post(url, json=event, headers=headers)
        except Exception as exc:
            logger.warning("Webhook audit sink POST failed: %s", exc)

    # ── Stats ─────────────────────────────────────────────────────────────

    async def stats(self) -> dict[str, Any]:
        """Return basic audit log statistics."""
        cursor = await self._db.execute(
            """
            SELECT COUNT(*) as total,
                   MIN(created_at) as oldest,
                   MAX(created_at) as newest
            FROM audit_log
            """
        )
        row = await cursor.fetchone()
        d = dict(row) if row else {}
        # Count by outcome
        cursor2 = await self._db.execute(
            "SELECT outcome, COUNT(*) as cnt FROM audit_log GROUP BY outcome"
        )
        by_outcome = {r[0]: r[1] for r in await cursor2.fetchall()}
        return {
            "total": d.get("total", 0),
            "oldest": d.get("oldest"),
            "newest": d.get("newest"),
            "by_outcome": by_outcome,
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_manager: AuditSinkManager | None = None


def init_audit_sink_manager(db: aiosqlite.Connection) -> AuditSinkManager:
    global _manager
    _manager = AuditSinkManager(db)
    return _manager


def get_audit_sink_manager() -> AuditSinkManager:
    if _manager is None:
        raise RuntimeError("AuditSinkManager not initialised")
    return _manager
