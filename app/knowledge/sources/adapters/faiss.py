"""Sprint 10 — FAISS local index knowledge source adapter (§5.14).

Optional dependency: ``faiss-cpu`` (or ``faiss-gpu``).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.knowledge.sources.adapters.base import KnowledgeSourceAdapter
from app.knowledge.sources.models import KnowledgeChunk, KnowledgeSource

logger = logging.getLogger(__name__)


class FAISSAdapter(KnowledgeSourceAdapter):
    """Adapter for a local FAISS index file."""

    def __init__(self, source: KnowledgeSource) -> None:
        super().__init__(source)
        self._index: Any = None
        self._metadata: list[dict[str, Any]] = []

    def _load(self) -> None:
        if self._index is not None:
            return
        try:
            import faiss  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "faiss-cpu is required to use FAISS knowledge sources. "
                "Install it with: pip install faiss-cpu"
            ) from exc

        cfg = self.source.connection
        index_path = Path(cfg.get("index_path", "data/faiss/index.faiss"))
        meta_path = Path(cfg.get("metadata_path", "data/faiss/metadata.json"))

        self._index = faiss.read_index(str(index_path))
        with open(meta_path) as f:
            self._metadata = json.load(f)

    async def search(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.6,
    ) -> list[KnowledgeChunk]:
        try:
            self._load()
            from app.knowledge.embeddings import get_embedding_store
            store = get_embedding_store()
            if store is None:
                return []
            vectors = await store._provider.embed([query])
            query_vec = vectors[0]

            import numpy as np  # type: ignore[import]
            q = np.array([query_vec], dtype="float32")
            distances, indices = self._index.search(q, top_k)

            chunks: list[KnowledgeChunk] = []
            for dist, idx in zip(distances[0], indices[0]):
                if idx < 0 or idx >= len(self._metadata):
                    continue
                # FAISS inner product → score directly; L2 → convert
                score = float(dist)
                if score < threshold:
                    continue
                meta = self._metadata[idx]
                chunks.append(KnowledgeChunk(
                    source_id=self.source.source_id,
                    content=meta.get("content", ""),
                    score=min(1.0, score),
                    metadata={k: v for k, v in meta.items() if k != "content"},
                ))
            return sorted(chunks, key=lambda c: c.score, reverse=True)
        except Exception as exc:
            logger.warning("FAISSAdapter search error: %s", exc)
            return []

    async def health_check(self) -> bool:
        try:
            self._load()
            return self._index.ntotal >= 0
        except Exception as exc:
            logger.warning("FAISSAdapter health check failed: %s", exc)
            return False

    async def count(self) -> int:
        try:
            self._load()
            return int(self._index.ntotal)
        except Exception:
            return 0
