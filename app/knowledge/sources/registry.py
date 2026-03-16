"""Sprint 10 — KnowledgeSourceRegistry (§5.14).

Manages registered external knowledge sources, instantiates their adapters,
runs federated search, and performs periodic health monitoring.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.db.connection import write_transaction
from app.db.schema import row_to_dict
from app.exceptions import NotFoundError
from app.knowledge.sources.adapters.base import KnowledgeSourceAdapter
from app.knowledge.sources.models import KnowledgeChunk, KnowledgeSource

logger = logging.getLogger(__name__)


def _make_adapter(source: KnowledgeSource) -> KnowledgeSourceAdapter:
    """Instantiate the correct adapter for *source.backend*."""
    if source.backend == "chroma":
        from app.knowledge.sources.adapters.chroma import ChromaAdapter
        return ChromaAdapter(source)
    if source.backend == "pgvector":
        from app.knowledge.sources.adapters.pgvector import PgVectorAdapter
        return PgVectorAdapter(source)
    if source.backend == "faiss":
        from app.knowledge.sources.adapters.faiss import FAISSAdapter
        return FAISSAdapter(source)
    if source.backend == "http":
        from app.knowledge.sources.adapters.http import HTTPAdapter
        return HTTPAdapter(source)
    raise ValueError(f"Unknown backend: {source.backend!r}")


def _now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeSourceRegistry:
    """Registry for external knowledge sources.

    Stores source configs in SQLite (``knowledge_sources`` table) and
    maintains in-memory adapter instances for active sources.
    """

    # Config defaults (can be overridden via ConfigStore later)
    per_source_timeout_s: float = 5.0
    max_consecutive_failures: int = 5
    health_check_interval_s: int = 300

    def __init__(self, db: Any) -> None:
        self._db = db
        self._adapters: dict[str, KnowledgeSourceAdapter] = {}
        self._adapter_lock: asyncio.Lock = asyncio.Lock()  # TD-95: guard _adapters mutations
        self._health_task: asyncio.Task[None] | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Load active sources, start background health-check loop (TD-57)."""
        rows = await self._db.execute_fetchall(
            "SELECT * FROM knowledge_sources WHERE status = 'active'"
        )
        async with self._adapter_lock:
            for row in rows:
                source = KnowledgeSource.from_row(row_to_dict(row))
                self._adapters[source.source_id] = _make_adapter(source)
        logger.info(
            "KnowledgeSourceRegistry started (%d active sources)", len(self._adapters)
        )
        # Start background health monitoring (TD-57)
        if self._health_task is None:
            self._health_task = asyncio.create_task(
                self._health_loop(), name="knowledge_registry_health_loop"
            )

    async def _health_loop(self) -> None:
        """Periodically check health of all registered adapters."""
        while True:
            await asyncio.sleep(self.health_check_interval_s)
            async with self._adapter_lock:
                adapters_snapshot = dict(self._adapters)
            for source_id, adapter in adapters_snapshot.items():
                try:
                    healthy = await adapter.health_check()
                    if not healthy:
                        logger.warning(
                            "Source %s health check failed — marking as unhealthy", source_id
                        )
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "Source %s health check raised an exception", source_id, exc_info=True
                    )

    async def stop(self) -> None:
        """Cancel the background health-check task for clean shutdown."""
        if self._health_task is not None:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
            self._health_task = None
            logger.info("KnowledgeSourceRegistry health loop stopped.")

    # ── CRUD ──────────────────────────────────────────────────────────────────

    async def register(
        self,
        *,
        source_id: str | None = None,
        name: str,
        description: str = "",
        backend: str,
        query_mode: str = "text",
        embedding_provider: str | None = None,
        auto_recall: bool = False,
        priority: int = 100,
        max_results: int = 5,
        similarity_threshold: float = 0.6,
        connection: dict[str, Any] | None = None,
        allowed_agents: list[str] | None = None,
    ) -> KnowledgeSource:
        """Create and persist a new knowledge source (status=disabled)."""
        sid = source_id or str(uuid.uuid4())
        now = _now_str()
        conn_json = json.dumps(connection or {})
        agents_json = json.dumps(allowed_agents) if allowed_agents is not None else None

        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT INTO knowledge_sources (
                    id, name, description, backend, query_mode, embedding_provider,
                    auto_recall, priority, max_results, similarity_threshold,
                    connection_json, allowed_agents_json, status,
                    error_message, consecutive_failures,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'disabled',NULL,0,?,?)
                """,
                (
                    sid, name, description, backend, query_mode, embedding_provider,
                    int(auto_recall), priority, max_results, similarity_threshold,
                    conn_json, agents_json, now, now,
                ),
            )
        return await self.get(sid)

    async def get(self, source_id: str) -> KnowledgeSource:
        """Fetch a knowledge source by ID."""
        async with self._db.execute(
            "SELECT * FROM knowledge_sources WHERE id = ?", (source_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            raise NotFoundError(f"Knowledge source not found: {source_id!r}")
        return KnowledgeSource.from_row(row_to_dict(row))

    async def list(
        self,
        *,
        status: str | None = None,
        backend: str | None = None,
        auto_recall_only: bool = False,
    ) -> list[KnowledgeSource]:
        """List all sources with optional filtering."""
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if backend:
            clauses.append("backend = ?")
            params.append(backend)
        if auto_recall_only:
            clauses.append("auto_recall = 1")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = await self._db.execute_fetchall(
            f"SELECT * FROM knowledge_sources {where} ORDER BY priority, name",
            params,
        )
        return [KnowledgeSource.from_row(row_to_dict(r)) for r in rows]

    async def update(self, source_id: str, **kwargs: Any) -> KnowledgeSource:
        """Patch source fields. Returns updated source."""
        col_map = {
            "name": "name",
            "description": "description",
            "auto_recall": "auto_recall",
            "priority": "priority",
            "max_results": "max_results",
            "similarity_threshold": "similarity_threshold",
            "connection": "connection_json",
            "allowed_agents": "allowed_agents_json",
            "status": "status",
            "error_message": "error_message",
            "consecutive_failures": "consecutive_failures",
            "last_health_check": "last_health_check",
        }
        assignments: list[str] = []
        values: list[Any] = []
        for key, val in kwargs.items():
            if key not in col_map:
                continue
            col = col_map[key]
            if key == "connection":
                val = json.dumps(val or {})
            elif key == "allowed_agents":
                val = json.dumps(val) if val is not None else None
            elif key == "auto_recall":
                val = int(bool(val))
            assignments.append(f"{col} = ?")
            values.append(val)
        if not assignments:
            return await self.get(source_id)
        assignments.append("updated_at = ?")
        values.append(_now_str())
        values.append(source_id)
        async with write_transaction(self._db):
            await self._db.execute(
                f"UPDATE knowledge_sources SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
        source = await self.get(source_id)
        # Refresh adapter cache if status changed (TD-95: guarded by lock)
        if "status" in kwargs:
            if source.status == "active":
                async with self._adapter_lock:
                    self._adapters[source_id] = _make_adapter(source)
            else:
                async with self._adapter_lock:
                    old_adapter = self._adapters.pop(source_id, None)
                if old_adapter is not None:
                    try:
                        await old_adapter.deactivate()
                    except Exception:
                        logger.warning("Error deactivating adapter for source %s on status change", source_id, exc_info=True)
        return source

    async def delete(self, source_id: str) -> None:
        """Remove a source from DB and adapter cache."""
        await self.get(source_id)  # raises NotFoundError if missing
        async with self._adapter_lock:
            adapter = self._adapters.pop(source_id, None)
        if adapter is not None:
            try:
                await adapter.deactivate()
            except Exception:
                logger.warning("Error deactivating adapter for source %s on delete", source_id, exc_info=True)
        async with write_transaction(self._db):
            await self._db.execute(
                "DELETE FROM knowledge_sources WHERE id = ?", (source_id,)
            )

    # ── Activation ───────────────────────────────────────────────────────────

    async def activate(self, source_id: str) -> KnowledgeSource:
        """Health-check → set status=active."""
        source = await self.get(source_id)
        adapter = _make_adapter(source)
        healthy = await adapter.health_check()
        if healthy:
            updated = await self.update(
                source_id,
                status="active",
                consecutive_failures=0,
                error_message=None,
                last_health_check=_now_str(),
            )
            async with self._adapter_lock:
                self._adapters[source_id] = adapter
            return updated
        else:
            return await self.update(
                source_id,
                status="error",
                error_message="Health check failed during activation",
                last_health_check=_now_str(),
            )

    async def deactivate(self, source_id: str) -> KnowledgeSource:
        """Set status=disabled and remove from adapter cache."""
        async with self._adapter_lock:
            adapter = self._adapters.pop(source_id, None)
        if adapter is not None:
            try:
                await adapter.deactivate()
            except Exception:
                logger.warning("Error deactivating adapter for source %s", source_id, exc_info=True)
        return await self.update(source_id, status="disabled")

    # ── Search ────────────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        *,
        source_ids: list[str] | None = None,
        agent_id: str | None = None,
        top_k: int = 10,
    ) -> list[KnowledgeChunk]:
        """Federated search across specified (or all active) sources."""
        sources = await self.list(status="active")
        if source_ids is not None:
            sources = [s for s in sources if s.source_id in source_ids]
        if agent_id is not None:
            sources = [
                s for s in sources
                if s.allowed_agents is None or agent_id in s.allowed_agents
            ]
        if not sources:
            return []

        tasks = [
            self._search_one(s, query, top_k)
            for s in sources
        ]
        results_per_source: list[list[KnowledgeChunk]] = await asyncio.gather(*tasks)
        all_chunks: list[KnowledgeChunk] = []
        for chunks in results_per_source:
            all_chunks.extend(chunks)
        # Re-rank by score descending, take top_k globally
        return sorted(all_chunks, key=lambda c: c.score, reverse=True)[:top_k]

    async def search_auto_recall(
        self,
        query: str,
        agent_id: str,
        top_k: int = 10,
    ) -> list[KnowledgeChunk]:
        """Search only auto_recall=True sources accessible to agent_id."""
        sources = await self.list(status="active", auto_recall_only=True)
        sources = [
            s for s in sources
            if not s.allowed_agents or agent_id in s.allowed_agents
        ]
        if not sources:
            return []
        tasks = [self._search_one(s, query, s.max_results) for s in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        chunks: list[KnowledgeChunk] = []
        for batch in results:
            if isinstance(batch, BaseException):
                logger.warning("search_auto_recall task failed: %s", batch)
            elif batch:
                chunks.extend(batch)
        return sorted(chunks, key=lambda c: c.score, reverse=True)[:top_k]

    async def _search_one(
        self,
        source: KnowledgeSource,
        query: str,
        top_k: int,
    ) -> list[KnowledgeChunk]:
        """Search a single source with timeout + failure tracking."""
        async with self._adapter_lock:
            adapter = self._adapters.get(source.source_id)
            if adapter is None:
                adapter = _make_adapter(source)
                self._adapters[source.source_id] = adapter
        try:
            coro = adapter.search(
                query,
                top_k=top_k,
                threshold=source.similarity_threshold,
            )
            return await asyncio.wait_for(coro, timeout=self.per_source_timeout_s)
        except asyncio.TimeoutError:
            logger.warning(
                "Knowledge source %r timed out (%.1fs)",
                source.source_id, self.per_source_timeout_s,
            )
        except Exception as exc:
            logger.warning("Knowledge source %r search error: %s", source.source_id, exc)
        # Track failure atomically (TD-96: avoid stale read-then-write race)
        now = _now_str()
        async with write_transaction(self._db):
            await self._db.execute(
                "UPDATE knowledge_sources SET consecutive_failures = consecutive_failures + 1, updated_at = ? WHERE id = ?",
                (now, source.source_id),
            )
        # Re-fetch to see the authoritative new count
        try:
            refreshed = await self.get(source.source_id)
            new_failures = refreshed.consecutive_failures
        except Exception:
            new_failures = self.max_consecutive_failures  # safe fallback
        if new_failures >= self.max_consecutive_failures:
            logger.warning(
                "Knowledge source %r disabled after %d consecutive failures",
                source.source_id, new_failures,
            )
            await self.update(
                source.source_id,
                status="error",
                error_message=f"Auto-disabled after {new_failures} consecutive failures",
            )
            async with self._adapter_lock:
                self._adapters.pop(source.source_id, None)
        return []

    # ── Health monitoring ────────────────────────────────────────────────────

    async def health_check_all(self) -> dict[str, bool]:
        """Run health checks on all known (active + error) sources."""
        rows = await self._db.execute_fetchall(
            "SELECT * FROM knowledge_sources WHERE status IN ('active','error')"
        )
        results: dict[str, bool] = {}
        for row in rows:
            source = KnowledgeSource.from_row(row_to_dict(row))
            adapter = self._adapters.get(source.source_id) or _make_adapter(source)
            try:
                healthy = await asyncio.wait_for(
                    adapter.health_check(), timeout=self.per_source_timeout_s
                )
            except Exception:
                healthy = False
            results[source.source_id] = healthy
            new_status = "active" if healthy else "error"
            await self.update(
                source.source_id,
                status=new_status,
                consecutive_failures=0 if healthy else source.consecutive_failures + 1,
                last_health_check=_now_str(),
                error_message=None if healthy else "Health check failed",
            )
            if healthy:
                self._adapters[source.source_id] = adapter
            else:
                self._adapters.pop(source.source_id, None)
        return results

    def get_adapter(self, source_id: str) -> KnowledgeSourceAdapter:
        """Return instantiated adapter, or raise KeyError if not active."""
        adapter = self._adapters.get(source_id)
        if adapter is None:
            raise KeyError(f"No active adapter for source {source_id!r}")
        return adapter


# ── Singleton ─────────────────────────────────────────────────────────────────

_registry: KnowledgeSourceRegistry | None = None


def init_knowledge_source_registry(db: Any) -> KnowledgeSourceRegistry:
    """Create and store the process-wide registry singleton."""
    global _registry
    _registry = KnowledgeSourceRegistry(db)
    return _registry


def get_knowledge_source_registry() -> KnowledgeSourceRegistry:
    """Return the process-wide registry singleton.

    Raises ``RuntimeError`` if not yet initialised.
    """
    if _registry is None:
        raise RuntimeError(
            "KnowledgeSourceRegistry not initialised — call init_knowledge_source_registry() at startup."
        )
    return _registry
