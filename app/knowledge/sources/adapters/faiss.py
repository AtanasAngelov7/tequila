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

# TD-45: Restrict FAISS file access to within the data directory
_DATA_DIR = Path("data").resolve()


def _validate_path(raw_path: str, label: str) -> Path:
    """Raise ValueError if *raw_path* resolves outside the allowed data directory."""
    resolved = Path(raw_path).resolve()
    try:
        resolved.relative_to(_DATA_DIR)
    except ValueError:
        raise ValueError(
            f"Path for {label} ({raw_path!r}) is outside the allowed data directory."
        )
    return resolved


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
        index_path = _validate_path(
            cfg.get("index_path", "data/faiss/index.faiss"), "index_path"
        )
        meta_path_raw = cfg.get("metadata_path", "data/faiss/metadata.json")
        meta_path = _validate_path(meta_path_raw, "metadata_path") if meta_path_raw else None

        self._index = faiss.read_index(str(index_path))
        if meta_path is not None:
            with open(meta_path) as f:
                self._metadata = json.load(f)
        else:
            self._metadata = []

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
                # TD-54: L2 distance — lower = more similar.  Convert to 0–1 similarity.
                # (For inner-product indices the raw score can be used directly, but
                # the default index built by FaissAdapter is always L2.)
                score = 1.0 / (1.0 + float(dist))
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
