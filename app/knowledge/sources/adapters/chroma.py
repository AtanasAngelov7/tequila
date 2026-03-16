"""Sprint 10 — ChromaDB knowledge source adapter (§5.14).

Optional dependency: ``chromadb``.  Import errors are deferred to first use.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.knowledge.sources.adapters.base import KnowledgeSourceAdapter
from app.knowledge.sources.models import KnowledgeChunk, KnowledgeSource

logger = logging.getLogger(__name__)


class ChromaAdapter(KnowledgeSourceAdapter):
    """Adapter for ChromaDB (local in-process or remote HTTP server)."""

    def __init__(self, source: KnowledgeSource) -> None:
        super().__init__(source)
        self._client: Any = None
        self._collection: Any = None  # cached collection object (TD-93)

    def _ensure_client(self) -> None:
        """Lazily initialise the Chroma client on first use."""
        if self._client is not None:
            return
        try:
            import chromadb  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "chromadb is required to use ChromaDB knowledge sources. "
                "Install it with: pip install chromadb"
            ) from exc

        cfg = self.source.connection
        host = cfg.get("host", "localhost")
        if host == "local":
            path = cfg.get("path", "data/chroma/")
            self._client = chromadb.PersistentClient(path=path)
        else:
            port = cfg.get("port", 8000)
            api_key = cfg.get("api_key")
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            self._client = chromadb.HttpClient(
                host=host, port=port, headers=headers
            )

    def _get_collection(self) -> Any:
        """Return the cached collection, fetching once on first call (TD-93)."""
        if self._collection is not None:
            return self._collection
        self._ensure_client()
        cfg = self.source.connection
        collection_name = cfg.get("collection", "default")
        tenant = cfg.get("tenant", "default_tenant")
        database = cfg.get("database", "default_database")
        try:
            self._collection = self._client.get_or_create_collection(
                name=collection_name,
                tenant=tenant,
                database=database,
            )
        except TypeError:
            # Older chromadb versions don't accept tenant/database
            self._collection = self._client.get_or_create_collection(name=collection_name)
        return self._collection

    async def search(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.6,
    ) -> list[KnowledgeChunk]:
        try:
            collection = self._get_collection()
            # Chroma's collection.query() is synchronous — offload to thread (TD-86)
            results = await asyncio.to_thread(
                collection.query,
                query_texts=[query],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )
            chunks: list[KnowledgeChunk] = []
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            dists = results.get("distances", [[]])[0]
            for doc, meta, dist in zip(docs, metas, dists):
                # Chroma returns L2 distance; convert to 0–1 score
                score = max(0.0, 1.0 - (dist / 2.0))
                if score >= threshold:
                    chunks.append(KnowledgeChunk(
                        source_id=self.source.source_id,
                        content=doc or "",
                        score=score,
                        metadata=meta or {},
                    ))
            return sorted(chunks, key=lambda c: c.score, reverse=True)
        except Exception as exc:
            logger.warning("ChromaAdapter search error for source %s: %s", self.source.source_id, exc)
            return []

    async def health_check(self) -> bool:
        try:
            self._ensure_client()
            await asyncio.to_thread(self._client.heartbeat)
            return True
        except Exception as exc:
            logger.warning("ChromaAdapter health check failed: %s", exc)
            return False

    async def count(self) -> int:
        try:
            collection = self._get_collection()
            return await asyncio.to_thread(collection.count)
        except Exception:
            return 0
