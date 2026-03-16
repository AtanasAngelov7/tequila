"""Memory store — CRUD for structured memory records (§5.3, Sprint 09)."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

import aiosqlite

from app.db.connection import write_transaction
from app.db.schema import row_to_dict
from app.exceptions import ConflictError, NotFoundError
from app.memory.models import MEMORY_SCOPES, MEMORY_TYPES, MemoryExtract

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── MemoryStore ───────────────────────────────────────────────────────────────


class MemoryStore:
    """CRUD access to the ``memory_extracts`` table (§5.3)."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # ── Create ────────────────────────────────────────────────────────────────

    async def create(
        self,
        *,
        content: str,
        memory_type: str,
        always_recall: bool | None = None,
        recall_weight: float | None = None,
        pinned: bool = False,
        expires_at: datetime | None = None,
        source_type: str = "user_created",
        source_session_id: str | None = None,
        source_message_id: str | None = None,
        confidence: float = 1.0,
        entity_ids: list[str] | None = None,
        tags: list[str] | None = None,
        scope: str = "global",
        agent_id: str | None = None,
    ) -> MemoryExtract:
        """Create and persist a new memory record, applying per-type defaults."""
        mem = MemoryExtract.with_type_defaults(
            id=str(uuid.uuid4()),
            content=content,
            memory_type=memory_type,
            **({"always_recall": always_recall} if always_recall is not None else {}),
            **({"recall_weight": recall_weight} if recall_weight is not None else {}),
            pinned=pinned,
            expires_at=expires_at,
            source_type=source_type,
            source_session_id=source_session_id,
            source_message_id=source_message_id,
            confidence=confidence,
            entity_ids=entity_ids or [],
            tags=tags or [],
            scope=scope,
            agent_id=agent_id,
        )
        now = _now_iso()
        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT INTO memory_extracts
                    (id, content, memory_type, always_recall, recall_weight, pinned,
                     created_at, updated_at, last_accessed,
                     expires_at, decay_score, source_type,
                     source_session_id, source_message_id, confidence,
                     entity_ids, tags, scope, agent_id, status, version)
                VALUES
                    (?, ?, ?, ?, ?, ?,
                     ?, ?, ?,
                     ?, ?, ?,
                     ?, ?, ?,
                     ?, ?, ?, ?, ?, ?)
                """,
                (
                    mem.id, mem.content, mem.memory_type,
                    int(mem.always_recall), mem.recall_weight, int(mem.pinned),
                    now, now, now,
                    mem.expires_at.isoformat() if mem.expires_at else None,
                    mem.decay_score, mem.source_type,
                    mem.source_session_id, mem.source_message_id, mem.confidence,
                    json.dumps(mem.entity_ids), json.dumps(mem.tags),
                    mem.scope, mem.agent_id, mem.status, mem.version,
                ),
            )
        mem.created_at = mem.updated_at = mem.last_accessed = datetime.now(timezone.utc)
        return mem

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get(self, memory_id: str) -> MemoryExtract:
        """Return the memory with *memory_id* (read-only — no side effects).

        Use ``touch()`` after ``get()`` if you want to bump the access
        timestamp and counter (TD-62).
        """
        async with self._db.execute(
            "SELECT * FROM memory_extracts WHERE id = ?", (memory_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise NotFoundError(resource="MemoryExtract", id=memory_id)
        return MemoryExtract.from_row(row_to_dict(row))

    async def touch(self, memory_id: str) -> None:
        """Bump ``last_accessed`` and ``access_count`` for *memory_id* (TD-62).

        Safe to call concurrently — the UPDATE is a single atomic statement.
        Silently no-ops if *memory_id* does not exist.
        """
        now = _now_iso()
        async with write_transaction(self._db):
            await self._db.execute(
                "UPDATE memory_extracts SET last_accessed = ?, access_count = access_count + 1 WHERE id = ?",
                (now, memory_id),
            )

    async def list(
        self,
        *,
        memory_type: str | None = None,
        scope: str | None = None,
        agent_id: str | None = None,
        status: str = "active",
        always_recall_only: bool = False,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
        after_id: str | None = None,
    ) -> list[MemoryExtract]:
        """Return memory records matching the given filters.

        Parameters
        ----------
        after_id:
            When set, only return records with ``id > after_id``, ordered by
            ``id ASC``.  Use for cursor-based pagination (TD-65) — avoids
            skipping items when rows are mutated during iteration.
        """
        clauses = ["status = ?"]
        params: list = [status]

        if memory_type:
            clauses.append("memory_type = ?")
            params.append(memory_type)
        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if always_recall_only:
            clauses.append("always_recall = 1")
        if search:
            clauses.append("content LIKE ?")
            params.append(f"%{search}%")

        where = " AND ".join(clauses)

        if after_id is not None:
            # Cursor-based pagination: order by id, skip rows already seen
            params_q = params + [after_id, limit]
            async with self._db.execute(
                f"SELECT * FROM memory_extracts WHERE {where} AND id > ? "
                f"ORDER BY id ASC LIMIT ?",
                params_q,
            ) as cur:
                rows = await cur.fetchall()
        else:
            params_q = params + [limit, offset]
            async with self._db.execute(
                f"SELECT * FROM memory_extracts WHERE {where} "
                f"ORDER BY recall_weight DESC, updated_at DESC LIMIT ? OFFSET ?",
                params_q,
            ) as cur:
                rows = await cur.fetchall()

        return [MemoryExtract.from_row(row_to_dict(r)) for r in rows]

    # ── Update ────────────────────────────────────────────────────────────────

    async def update(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        pinned: bool | None = None,
        recall_weight: float | None = None,
        tags: list[str] | None = None,
        entity_ids: list[str] | None = None,
        status: str | None = None,
        decay_score: float | None = None,
        confidence: float | None = None,
    ) -> MemoryExtract:
        """Update selected fields on *memory_id* with OCC retry (§20.3b)."""
        for attempt in range(3):
            mem = await self.get(memory_id)
            new_content = content if content is not None else mem.content
            new_pinned = pinned if pinned is not None else mem.pinned
            new_weight = recall_weight if recall_weight is not None else mem.recall_weight
            new_tags = tags if tags is not None else mem.tags
            new_entity_ids = entity_ids if entity_ids is not None else mem.entity_ids
            new_status = status if status is not None else mem.status
            new_decay = decay_score if decay_score is not None else mem.decay_score
            new_conf = confidence if confidence is not None else mem.confidence
            now = _now_iso()

            async with write_transaction(self._db):
                await self._db.execute(
                    """
                    UPDATE memory_extracts
                       SET content = ?, pinned = ?, recall_weight = ?,
                           tags = ?, entity_ids = ?, status = ?,
                           decay_score = ?, confidence = ?,
                           updated_at = ?, version = version + 1
                     WHERE id = ? AND version = ?
                    """,
                    (
                        new_content, int(new_pinned), new_weight,
                        json.dumps(new_tags), json.dumps(new_entity_ids), new_status,
                        new_decay, new_conf,
                        now, memory_id, mem.version,
                    ),
                )
                async with self._db.execute(
                    "SELECT changes()"
                ) as cur:
                    row = await cur.fetchone()
                changed = row[0] if row else 0

            if changed:
                return await self.get(memory_id)
            if attempt < 2:
                logger.warning(
                    "MemoryStore.update: OCC conflict on '%s', retrying (%d/3).",
                    memory_id, attempt + 1,
                )

        raise ConflictError(f"MemoryExtract '{memory_id}' was modified concurrently — update failed after 3 attempts.")

    # ── Delete ────────────────────────────────────────────────────────────────

    async def delete(self, memory_id: str) -> None:
        """Hard-delete memory *memory_id* (raises ``NotFoundError`` if absent)."""
        await self.get(memory_id)  # confirm exists
        async with write_transaction(self._db):
            await self._db.execute(
                "DELETE FROM memory_extracts WHERE id = ?", (memory_id,)
            )

    async def soft_delete(self, memory_id: str) -> MemoryExtract:
        """Mark *memory_id* as ``deleted`` without removing the row."""
        return await self.update(memory_id, status="deleted")

    # ── Entity linkage ────────────────────────────────────────────────────────

    async def link_entity(self, memory_id: str, entity_id: str) -> None:
        """Create a ``memory_entity_links`` row if it doesn't already exist."""
        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT OR IGNORE INTO memory_entity_links (memory_id, entity_id)
                VALUES (?, ?)
                """,
                (memory_id, entity_id),
            )
        # Also update entity_ids JSON column
        mem = await self.get(memory_id)
        if entity_id not in mem.entity_ids:
            await self.update(memory_id, entity_ids=mem.entity_ids + [entity_id])

    async def unlink_entity(self, memory_id: str, entity_id: str) -> None:
        """Remove the ``memory_entity_links`` row and update the entity_ids JSON column."""
        async with write_transaction(self._db):
            await self._db.execute(
                "DELETE FROM memory_entity_links WHERE memory_id = ? AND entity_id = ?",
                (memory_id, entity_id),
            )
        # TD-63: also remove entity_id from the JSON column (mirrors link_entity's behaviour)
        mem = await self.get(memory_id)
        updated_ids = [eid for eid in mem.entity_ids if eid != entity_id]
        if updated_ids != mem.entity_ids:
            await self.update(memory_id, entity_ids=updated_ids)


# ── Module-level singleton ────────────────────────────────────────────────────

_memory_store: MemoryStore | None = None


def init_memory_store(db: aiosqlite.Connection) -> MemoryStore:
    """Initialise and register the global MemoryStore singleton."""
    global _memory_store  # noqa: PLW0603
    _memory_store = MemoryStore(db)
    logger.info("MemoryStore initialised.")
    return _memory_store


def get_memory_store() -> MemoryStore:
    """Return the global MemoryStore singleton.

    Raises ``RuntimeError`` if not yet initialised.
    """
    if _memory_store is None:
        raise RuntimeError("MemoryStore not initialised.  Check app lifespan.")
    return _memory_store
