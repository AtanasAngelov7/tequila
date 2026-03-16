"""Memory audit trail — logs all memory and entity mutations (§5.9, Sprint 11).

Every change to a ``MemoryExtract`` or ``Entity`` is appended to the
``memory_events`` table.  No updates, no deletes — only appends.

Usage::

    audit = get_memory_audit()
    await audit.log(
        event_type="updated",
        memory_id=mem_id,
        actor="agent",
        actor_id=agent_id,
        old_content=old.content,
        new_content=new.content,
        reason="User correction",
    )
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, get_args

import aiosqlite
from pydantic import BaseModel, Field

from app.db.connection import write_transaction
from app.db.schema import row_to_dict

logger = logging.getLogger(__name__)

# ── Event type literals ───────────────────────────────────────────────────────

EVENT_TYPES = Literal[
    "created",
    "updated",
    "merged",
    "promoted",
    "archived",
    "deleted",
    "accessed",
    "pinned",
    "unpinned",
    "conflict_detected",
    "conflict_resolved",
    "entity_created",
    "entity_merged",
    "entity_updated",
    "decay_recalculated",
    "consolidated",
]

ACTOR_TYPES = Literal[
    "extraction_pipeline",
    "consolidation",
    "recall",
    "agent",
    "user",
    "system",
]

# Derived sets for O(1) runtime validation (TD-98)
_VALID_EVENT_TYPES: frozenset[str] = frozenset(get_args(EVENT_TYPES))
_VALID_ACTOR_TYPES: frozenset[str] = frozenset(get_args(ACTOR_TYPES))

# Sentinel for corrupt timestamps — clearly wrong epoch, not disguised as now()
_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


# ── MemoryEvent model ─────────────────────────────────────────────────────────


class MemoryEvent(BaseModel):
    """A single audit-trail entry recording one memory or entity mutation (§5.9)."""

    id: str
    """UUID assigned at log time."""

    memory_id: str | None = None
    """For memory-related events: the target ``MemoryExtract`` ID."""

    entity_id: str | None = None
    """For entity-related events: the target ``Entity`` ID."""

    event_type: str
    """Type of mutation (see ``EVENT_TYPES``)."""

    actor: str = "system"
    """Who triggered this change (see ``ACTOR_TYPES``)."""

    actor_id: str | None = None
    """Optional ID of the specific agent or user."""

    old_content: str | None = None
    """Previous content snapshot (for ``updated``/``merged`` events)."""

    new_content: str | None = None
    """New content snapshot."""

    reason: str | None = None
    """Human-readable explanation (e.g., 'similarity=0.94 above merge threshold')."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Extra context (similarity scores, version numbers, etc.)."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    """UTC timestamp of the event."""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "MemoryEvent":
        """Deserialise a DB row into a ``MemoryEvent``."""
        ts = row.get("timestamp", "")
        try:
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            parsed_ts = datetime.fromisoformat(ts)
        except (ValueError, AttributeError):
            logger.warning(
                "Corrupt timestamp in memory_event %s: %r — using sentinel epoch",
                row.get("id"),
                row.get("timestamp"),
            )
            parsed_ts = _EPOCH

        meta_raw = row.get("metadata", "{}")
        try:
            meta = json.loads(meta_raw) if meta_raw else {}
        except (ValueError, TypeError):
            meta = {}

        return cls(
            id=row["id"],
            memory_id=row.get("memory_id"),
            entity_id=row.get("entity_id"),
            event_type=row["event_type"],
            actor=row.get("actor", "system"),
            actor_id=row.get("actor_id"),
            old_content=row.get("old_content"),
            new_content=row.get("new_content"),
            reason=row.get("reason"),
            metadata=meta,
            timestamp=parsed_ts,
        )


# ── MemoryAuditLog ────────────────────────────────────────────────────────────


class MemoryAuditLog:
    """Append-only audit log for memory and entity mutations (§5.9).

    All writes are simple INSERTs — no updates, no deletes.
    """

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # ── Write ─────────────────────────────────────────────────────────────────

    async def log(
        self,
        *,
        event_type: str,
        memory_id: str | None = None,
        entity_id: str | None = None,
        actor: str = "system",
        actor_id: str | None = None,
        old_content: str | None = None,
        new_content: str | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEvent:
        """Append one event to the audit trail.

        Returns the persisted ``MemoryEvent``.
        """
        # TD-98: validate types at write time
        if event_type not in _VALID_EVENT_TYPES:
            raise ValueError(
                f"Invalid event_type: {event_type!r}. Must be one of {sorted(_VALID_EVENT_TYPES)}"
            )
        if actor not in _VALID_ACTOR_TYPES:
            raise ValueError(
                f"Invalid actor: {actor!r}. Must be one of {sorted(_VALID_ACTOR_TYPES)}"
            )
        event = MemoryEvent(
            id=str(uuid.uuid4()),
            memory_id=memory_id,
            entity_id=entity_id,
            event_type=event_type,
            actor=actor,
            actor_id=actor_id,
            old_content=old_content,
            new_content=new_content,
            reason=reason,
            metadata=metadata or {},
        )

        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT INTO memory_events
                    (id, memory_id, entity_id, event_type,
                     actor, actor_id, old_content, new_content,
                     reason, metadata, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.memory_id,
                    event.entity_id,
                    event.event_type,
                    event.actor,
                    event.actor_id,
                    event.old_content,
                    event.new_content,
                    event.reason,
                    json.dumps(event.metadata),
                    event.timestamp.isoformat(),
                ),
            )

        logger.debug(
            "Memory audit: %s on %s",
            event.event_type,
            event.memory_id or event.entity_id or "unknown",
        )
        return event

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_memory_history(
        self,
        memory_id: str,
        limit: int = 50,
    ) -> list[MemoryEvent]:
        """Return all events for a given memory, newest first."""
        async with self._db.execute(
            """
            SELECT * FROM memory_events
             WHERE memory_id = ?
             ORDER BY timestamp DESC
             LIMIT ?
            """,
            (memory_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [MemoryEvent.from_row(row_to_dict(r)) for r in rows]

    async def get_entity_history(
        self,
        entity_id: str,
        limit: int = 50,
    ) -> list[MemoryEvent]:
        """Return all events for a given entity, newest first."""
        async with self._db.execute(
            """
            SELECT * FROM memory_events
             WHERE entity_id = ?
             ORDER BY timestamp DESC
             LIMIT ?
            """,
            (entity_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [MemoryEvent.from_row(row_to_dict(r)) for r in rows]

    async def get_global_feed(
        self,
        *,
        event_type: str | None = None,
        actor: str | None = None,
        since: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryEvent]:
        """Return the global event feed (paginated), newest first.

        Optional filters: ``event_type``, ``actor``, ``since`` (ISO datetime string).
        """
        clauses: list[str] = []
        params: list[Any] = []

        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if actor:
            clauses.append("actor = ?")
            params.append(actor)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params += [limit, offset]

        async with self._db.execute(
            f"SELECT * FROM memory_events {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            params,
        ) as cur:
            rows = await cur.fetchall()
        return [MemoryEvent.from_row(row_to_dict(r)) for r in rows]


# ── Module-level singleton ────────────────────────────────────────────────────

_audit: MemoryAuditLog | None = None


def init_memory_audit(db: aiosqlite.Connection) -> MemoryAuditLog:
    """Initialise and register the global MemoryAuditLog singleton."""
    global _audit  # noqa: PLW0603
    _audit = MemoryAuditLog(db)
    logger.info("MemoryAuditLog initialised.")
    return _audit


def get_memory_audit() -> MemoryAuditLog:
    """Return the global MemoryAuditLog singleton.

    Raises ``RuntimeError`` if not yet initialised.
    """
    if _audit is None:
        raise RuntimeError("MemoryAuditLog not initialised.  Check app lifespan.")
    return _audit
