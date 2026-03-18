"""Sprint 04 — AgentStore: CRUD for the ``agents`` table (§4.1).

Follows the same async/WAL pattern as ``SessionStore``:
- All writes serialised through ``write_transaction``
- Reads go directly to the connection
- ``row_to_dict`` / ``AgentConfig.from_row()`` for hydration
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.agent.models import AgentConfig, SoulConfig
from app.db.connection import write_transaction
from app.db.schema import row_to_dict
from app.exceptions import AgentNotFoundError, ConflictError

logger = logging.getLogger(__name__)

MAX_OCC_RETRIES = 3


# TD-364: Allow-list for extra columns accepted by AgentStore.create()
_ALLOWED_EXTRA_COLUMNS: frozenset[str] = frozenset({
    "tools", "skills", "default_policy", "memory_scope",
    "escalation", "fallback_provider_id",
})


class AgentStore:
    """Database operations for the ``agents`` table."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # ── Create ────────────────────────────────────────────────────────────────

    async def create(
        self,
        *,
        name: str,
        provider: str = "anthropic",
        default_model: str = "anthropic:claude-sonnet-4-5",
        persona: str = "a helpful AI assistant",
        soul: SoulConfig | None = None,
        role: str = "main",
        is_admin: bool = False,
        status: str = "active",
        extra: dict[str, Any] | None = None,
    ) -> AgentConfig:
        """Insert a new agent row and return a hydrated ``AgentConfig``."""
        agent_id = f"agent:{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        soul_obj = soul or SoulConfig(persona=persona, instructions=[])

        row: dict[str, Any] = {
            "agent_id": agent_id,
            "name": name,
            "provider": provider,
            "default_model": default_model,
            "persona": persona,
            "role": role,
            "soul": soul_obj.model_dump_json(),
            "fallback_provider_id": None,
            "tools": json.dumps([]),
            "skills": json.dumps([]),
            "default_policy": json.dumps({}),
            "memory_scope": json.dumps({}),
            "is_admin": 1 if is_admin else 0,
            "escalation": json.dumps({}),
            "status": status,
            "version": 1,
            "created_at": now,
            "updated_at": now,
        }
        if extra:
            filtered = {k: v for k, v in extra.items() if k in _ALLOWED_EXTRA_COLUMNS}
            if len(filtered) < len(extra):
                unknown = set(extra) - _ALLOWED_EXTRA_COLUMNS
                logger.warning("AgentStore.create: ignoring unknown extra keys: %s", unknown)
            row.update(filtered)

        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT INTO agents (
                    agent_id, name, provider, default_model, persona,
                    role, soul, fallback_provider_id,
                    tools, skills, default_policy, memory_scope,
                    is_admin, escalation,
                    status, version, created_at, updated_at
                ) VALUES (
                    :agent_id, :name, :provider, :default_model, :persona,
                    :role, :soul, :fallback_provider_id,
                    :tools, :skills, :default_policy, :memory_scope,
                    :is_admin, :escalation,
                    :status, :version, :created_at, :updated_at
                )
                """,
                row,
            )

        return await self.get_by_id(agent_id)

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_by_id(self, agent_id: str) -> AgentConfig:
        """Fetch by ``agent_id`` PK.

        Raises :class:`~app.exceptions.AgentNotFoundError` when absent.
        """
        async with self._db.execute(
            "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise AgentNotFoundError(agent_id)
        return AgentConfig.from_row(row_to_dict(row))

    async def list(
        self,
        *,
        status: str | None = None,
        role: str | None = None,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentConfig]:
        """Return a filtered list of agents."""
        clauses: list[str] = []
        params: list[Any] = []

        if status:
            clauses.append("status = ?")
            params.append(status)
        if role:
            clauses.append("role = ?")
            params.append(role)
        if q:
            clauses.append("(name LIKE ? OR persona LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])

        async with self._db.execute(
            f"SELECT * FROM agents {where} ORDER BY created_at ASC LIMIT ? OFFSET ?",
            params,
        ) as cur:
            rows = await cur.fetchall()
        return [AgentConfig.from_row(row_to_dict(r)) for r in rows]
    async def count(
        self,
        *,
        status: str | None = None,
        role: str | None = None,
        q: str | None = None,
    ) -> int:
        """Return total count of agents matching filters (TD-168)."""
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if role:
            clauses.append("role = ?")
            params.append(role)
        if q:
            clauses.append("(name LIKE ? OR persona LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self._db.execute(
            f"SELECT COUNT(*) FROM agents {where}",
            params,
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0
    # ── Update ────────────────────────────────────────────────────────────────

    async def update(
        self,
        agent_id: str,
        *,
        version: int,
        **fields: Any,
    ) -> AgentConfig:
        """OCC update — increments version if successful.

        Raises :class:`~app.exceptions.ConflictError` after ``MAX_OCC_RETRIES``
        version mismatches.
        """
        now = datetime.now(timezone.utc).isoformat()
        fields["updated_at"] = now

        # Serialise Pydantic models to JSON strings where needed
        for key in ("soul", "default_policy", "memory_scope", "escalation"):
            if key in fields and hasattr(fields[key], "model_dump_json"):
                fields[key] = fields[key].model_dump_json()
        for key in ("tools", "skills"):
            if key in fields and isinstance(fields[key], list):
                fields[key] = json.dumps(fields[key])
        if "is_admin" in fields:
            fields["is_admin"] = 1 if fields["is_admin"] else 0

        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        params = {**fields, "agent_id": agent_id, "version": version, "new_version": version + 1}
        # Add new_version to SET
        full_set = f"{set_clause}, version = :new_version"

        for attempt in range(MAX_OCC_RETRIES + 1):
            async with write_transaction(self._db):
                result = await self._db.execute(
                    f"UPDATE agents SET {full_set} "
                    "WHERE agent_id = :agent_id AND version = :version",
                    params,
                )
                if result.rowcount == 1:
                    break
                # Version mismatch — check agent exists first
                existing = await self._db.execute(
                    "SELECT agent_id FROM agents WHERE agent_id = :agent_id",
                    {"agent_id": agent_id},
                )
                row = await existing.fetchone()
                if row is None:
                    raise AgentNotFoundError(agent_id)
                if attempt >= MAX_OCC_RETRIES:
                    raise ConflictError(
                        f"Agent '{agent_id}' version mismatch: expected {version}"
                    )
                # Re-read current version for next attempt
                fresh = await self._db.execute(
                    "SELECT version FROM agents WHERE agent_id = :agent_id",
                    {"agent_id": agent_id},
                )
                fresh_row = await fresh.fetchone()
                if fresh_row:
                    params["version"] = fresh_row["version"]
                    params["new_version"] = fresh_row["version"] + 1

        return await self.get_by_id(agent_id)

    # ── Delete ────────────────────────────────────────────────────────────────

    async def delete(self, agent_id: str) -> None:
        """Hard-delete an agent row; raises ``AgentNotFoundError`` when absent."""
        await self.get_by_id(agent_id)  # ensure exists
        async with write_transaction(self._db):
            await self._db.execute(
                "DELETE FROM agents WHERE agent_id = ?", (agent_id,)
            )

    # ── Clone ─────────────────────────────────────────────────────────────────

    async def clone(self, agent_id: str, *, new_name: str | None = None) -> AgentConfig:
        """Duplicate an agent row returning the new ``AgentConfig``."""
        source = await self.get_by_id(agent_id)
        cloned_soul = SoulConfig(**source.soul.model_dump()) if source.soul else None
        return await self.create(
            name=new_name or f"Copy of {source.name}",
            provider=source.default_model.split(":")[0] if ":" in source.default_model else "anthropic",
            default_model=source.default_model,
            persona=source.soul.persona if source.soul else "a helpful AI assistant",
            soul=cloned_soul,
            role=source.role,
            is_admin=source.is_admin,
            status=source.status,
            extra={
                "tools": json.dumps(source.tools),
                "skills": json.dumps(source.skills),
                "default_policy": source.default_policy.model_dump_json(),
                "memory_scope": source.memory_scope.model_dump_json(),
                "escalation": source.escalation.model_dump_json(),
                "fallback_provider_id": source.fallback_provider_id,
            },
        )


# ── Module-level singleton ────────────────────────────────────────────────────

_store: AgentStore | None = None


def init_agent_store(db: aiosqlite.Connection) -> AgentStore:
    """Create and register the application-scoped ``AgentStore`` instance."""
    global _store  # noqa: PLW0603
    _store = AgentStore(db)
    return _store


def get_agent_store() -> AgentStore:
    """Return the application-scoped ``AgentStore``.

    Raises ``RuntimeError`` if ``init_agent_store()`` has not been called.
    """
    if _store is None:
        raise RuntimeError(
            "AgentStore has not been initialised. "
            "Call init_agent_store() during application startup."
        )
    return _store
