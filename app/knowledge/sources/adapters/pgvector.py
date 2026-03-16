"""Sprint 10 — PostgreSQL + pgvector knowledge source adapter (§5.14).

Optional dependencies: ``asyncpg``, ``pgvector``.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.knowledge.sources.adapters.base import KnowledgeSourceAdapter
from app.knowledge.sources.models import KnowledgeChunk, KnowledgeSource

logger = logging.getLogger(__name__)

# TD-43: SQL identifier validation (defense-in-depth)
_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


def _validate_ident(name: str, label: str) -> str:
    """Raise ValueError if *name* is not a safe SQL identifier."""
    if not _IDENT_RE.match(name):
        raise ValueError(f"Invalid SQL identifier for {label}: {name!r}")
    return name


class PgVectorAdapter(KnowledgeSourceAdapter):
    """Adapter for PostgreSQL with the pgvector extension."""

    def __init__(self, source: KnowledgeSource) -> None:
        super().__init__(source)
        self._pool: Any = None

    async def _ensure_pool(self) -> Any:
        if self._pool is not None:
            return self._pool
        try:
            import asyncpg  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "asyncpg is required to use pgvector knowledge sources. "
                "Install it with: pip install asyncpg pgvector"
            ) from exc

        cfg = self.source.connection
        self._pool = await asyncpg.create_pool(dsn=cfg["dsn"], min_size=1, max_size=3)
        return self._pool

    async def search(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.6,
    ) -> list[KnowledgeChunk]:
        try:
            from app.knowledge.embeddings import get_embedding_store
            store = get_embedding_store()
            if store is None:
                return []
            vectors = await store._provider.embed([query])
            query_vec = vectors[0]

            pool = await self._ensure_pool()
            cfg = self.source.connection
            table = _validate_ident(cfg.get("table", "documents"), "table")
            content_col = _validate_ident(cfg.get("content_column", "content"), "content_column")
            emb_col = _validate_ident(cfg.get("embedding_column", "embedding"), "embedding_column")
            meta_cols = [_validate_ident(c, f"meta_col[{i}]") for i, c in enumerate(cfg.get("metadata_columns", []))]

            meta_select = ", ".join(meta_cols) if meta_cols else ""
            meta_clause = f", {meta_select}" if meta_select else ""
            vec_str = "[" + ",".join(str(x) for x in query_vec) + "]"

            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT {content_col}{meta_clause},
                           1 - ({emb_col} <=> $1::vector) AS score
                    FROM {table}
                    WHERE 1 - ({emb_col} <=> $1::vector) >= $2
                    ORDER BY {emb_col} <=> $1::vector
                    LIMIT $3
                    """,
                    vec_str,
                    threshold,
                    top_k,
                )

            chunks: list[KnowledgeChunk] = []
            for row in rows:
                meta = {col: row[col] for col in meta_cols if col in row}
                chunks.append(KnowledgeChunk(
                    source_id=self.source.source_id,
                    content=row[content_col] or "",
                    score=float(row["score"]),
                    metadata=meta,
                ))
            return chunks
        except Exception as exc:
            logger.warning("PgVectorAdapter search error: %s", exc)
            return []

    async def health_check(self) -> bool:
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as exc:
            logger.warning("PgVectorAdapter health check failed: %s", exc)
            return False

    async def count(self) -> int:
        try:
            pool = await self._ensure_pool()
            cfg = self.source.connection
            table = _validate_ident(cfg.get("table", "documents"), "table")
            async with pool.acquire() as conn:
                return await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
        except Exception:
            return 0

    async def deactivate(self) -> None:
        """Close the asyncpg connection pool (TD-94).

        Called by the registry when this source is removed or disabled so
        that database connections are released promptly.
        """
        if self._pool is not None:
            try:
                await self._pool.close()
            except Exception:
                logger.warning("PgVectorAdapter: error closing pool for source %s", self.source.source_id, exc_info=True)
            finally:
                self._pool = None
