"""Entity store — CRUD for entity records and alias resolution (§5.4, Sprint 09)."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.db.connection import write_transaction
from app.db.schema import row_to_dict
from app.exceptions import NotFoundError
from app.memory.entities import Entity, extract_entity_mentions

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── EntityStore ───────────────────────────────────────────────────────────────


class EntityStore:
    """CRUD and alias resolution for entity records (§5.4)."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # ── Create ────────────────────────────────────────────────────────────────

    async def create(
        self,
        *,
        name: str,
        entity_type: str,
        aliases: list[str] | None = None,
        summary: str = "",
        properties: dict[str, Any] | None = None,
    ) -> Entity:
        """Create and persist a new entity."""
        now = _now_iso()
        entity_id = str(uuid.uuid4())
        clean_aliases = aliases or []
        clean_props = properties or {}

        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT INTO entities
                    (id, name, entity_type, aliases, summary, properties,
                     first_seen, last_referenced, reference_count, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'active', ?)
                """,
                (
                    entity_id, name, entity_type,
                    json.dumps(clean_aliases), summary, json.dumps(clean_props),
                    now, now, now,
                ),
            )

        return await self.get(entity_id)

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get(self, entity_id: str) -> Entity:
        """Return the entity with *entity_id* or raise ``NotFoundError``."""
        async with self._db.execute(
            "SELECT * FROM entities WHERE id = ?", (entity_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise NotFoundError(resource="Entity", id=entity_id)
        return Entity.from_row(row_to_dict(row))

    async def list(
        self,
        *,
        entity_type: str | None = None,
        status: str = "active",
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Entity]:
        """Return entities matching the given filters."""
        clauses = ["status = ?"]
        params: list = [status]

        if entity_type:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if search:
            clauses.append("(name LIKE ? OR summary LIKE ?)")
            params += [f"%{search}%", f"%{search}%"]

        where = " AND ".join(clauses)
        params += [limit, offset]

        async with self._db.execute(
            f"SELECT * FROM entities WHERE {where} "
            f"ORDER BY reference_count DESC, name ASC LIMIT ? OFFSET ?",
            params,
        ) as cur:
            rows = await cur.fetchall()

        return [Entity.from_row(row_to_dict(r)) for r in rows]

    # ── Alias resolution ──────────────────────────────────────────────────────

    async def resolve(self, name: str) -> Entity | None:
        """Return the entity whose canonical name or an alias matches *name*.

        Returns ``None`` if no match found.
        """
        target = name.strip().lower()
        async with self._db.execute(
            "SELECT * FROM entities WHERE status = 'active' AND LOWER(name) = ?",
            (target,),
        ) as cur:
            row = await cur.fetchone()
        if row:
            return Entity.from_row(row_to_dict(row))

        # Search aliases (stored as JSON array — scan all active entities)
        async with self._db.execute(
            "SELECT * FROM entities WHERE status = 'active'"
        ) as cur:
            rows = await cur.fetchall()
        for row in rows:
            entity = Entity.from_row(row_to_dict(row))
            if any(a.lower() == target for a in entity.aliases):
                return entity
        return None

    # ── Update ────────────────────────────────────────────────────────────────

    async def update(
        self,
        entity_id: str,
        *,
        name: str | None = None,
        aliases: list[str] | None = None,
        summary: str | None = None,
        properties: dict[str, Any] | None = None,
        status: str | None = None,
        merged_into: str | None = None,
    ) -> Entity:
        """Update selected fields on *entity_id*."""
        entity = await self.get(entity_id)
        new_name = name if name is not None else entity.name
        new_aliases = aliases if aliases is not None else entity.aliases
        new_summary = summary if summary is not None else entity.summary
        new_props = properties if properties is not None else entity.properties
        new_status = status if status is not None else entity.status
        new_merged = merged_into if merged_into is not None else entity.merged_into
        now = _now_iso()

        async with write_transaction(self._db):
            await self._db.execute(
                """
                UPDATE entities
                   SET name = ?, aliases = ?, summary = ?, properties = ?,
                       status = ?, merged_into = ?, updated_at = ?
                 WHERE id = ?
                """,
                (
                    new_name, json.dumps(new_aliases), new_summary,
                    json.dumps(new_props), new_status, new_merged, now, entity_id,
                ),
            )
        return await self.get(entity_id)

    async def add_alias(self, entity_id: str, alias: str) -> Entity:
        """Add *alias* to *entity_id*'s alias list if not already present."""
        entity = await self.get(entity_id)
        if alias not in entity.aliases:
            return await self.update(entity_id, aliases=entity.aliases + [alias])
        return entity

    # ── Delete ────────────────────────────────────────────────────────────────

    async def delete(self, entity_id: str) -> None:
        """Hard-delete *entity_id*."""
        await self.get(entity_id)  # confirm exists
        async with write_transaction(self._db):
            await self._db.execute("DELETE FROM entities WHERE id = ?", (entity_id,))

    async def soft_delete(self, entity_id: str) -> Entity:
        """Mark *entity_id* as ``deleted``."""
        return await self.update(entity_id, status="deleted")

    # ── Reference count ───────────────────────────────────────────────────────

    async def increment_reference(self, entity_id: str) -> None:
        """Bump ``reference_count`` and update ``last_referenced``."""
        now = _now_iso()
        async with write_transaction(self._db):
            await self._db.execute(
                "UPDATE entities SET reference_count = reference_count + 1, "
                "last_referenced = ? WHERE id = ?",
                (now, entity_id),
            )

    # ── Memory links ──────────────────────────────────────────────────────────

    async def get_memories(self, entity_id: str) -> list[str]:
        """Return a list of memory IDs linked to *entity_id*."""
        await self.get(entity_id)  # confirm exists
        async with self._db.execute(
            "SELECT memory_id FROM memory_entity_links WHERE entity_id = ?",
            (entity_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [row_to_dict(r)["memory_id"] for r in rows]

    # ── NER extraction ────────────────────────────────────────────────────────

    async def extract_and_link(
        self, text: str, memory_id: str | None = None
    ) -> list[Entity]:
        """Run NER on *text*, resolve or create entities, optionally link to *memory_id*.

        Returns the list of resolved/created entities.
        """
        mentions = extract_entity_mentions(text)
        entities: list[Entity] = []

        for mention in mentions:
            entity = await self.resolve(mention["name"])
            if entity is None:
                try:
                    entity = await self.create(
                        name=mention["name"],
                        entity_type=mention["entity_type"],
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "EntityStore.extract_and_link: failed to create entity '%s': %s",
                        mention["name"], exc,
                    )
                    continue
            else:
                await self.increment_reference(entity.id)

            if memory_id:
                try:
                    async with write_transaction(self._db):
                        await self._db.execute(
                            "INSERT OR IGNORE INTO memory_entity_links (memory_id, entity_id) VALUES (?, ?)",
                            (memory_id, entity.id),
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "EntityStore.extract_and_link: failed to link memory '%s' → entity '%s': %s",
                        memory_id, entity.id, exc,
                    )

            entities.append(entity)

        return entities


# ── Module-level singleton ────────────────────────────────────────────────────

_entity_store: EntityStore | None = None


def init_entity_store(db: aiosqlite.Connection) -> EntityStore:
    """Initialise and register the global EntityStore singleton."""
    global _entity_store  # noqa: PLW0603
    _entity_store = EntityStore(db)
    logger.info("EntityStore initialised.")
    return _entity_store


def get_entity_store() -> EntityStore:
    """Return the global EntityStore singleton.

    Raises ``RuntimeError`` if not yet initialised.
    """
    if _entity_store is None:
        raise RuntimeError("EntityStore not initialised.  Check app lifespan.")
    return _entity_store
