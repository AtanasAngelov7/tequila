"""Embedding engine — vector storage and semantic search (§5.13, Sprint 09).

Provides:
- ``EmbeddingProvider``       — abstract interface for text → vector conversion.
- ``LocalEmbeddingProvider``  — default local provider via ``sentence-transformers``.
- ``EmbeddingStore``          — abstract storage/search interface.
- ``SQLiteEmbeddingStore``    — SQLite + numpy brute-force cosine similarity.

Singletons:
- ``init_embedding_store(db, provider=None) → SQLiteEmbeddingStore``
- ``get_embedding_store() → SQLiteEmbeddingStore``
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.db.connection import write_transaction
from app.db.schema import row_to_dict

logger = logging.getLogger(__name__)


# ── Abstract provider ─────────────────────────────────────────────────────────


class EmbeddingProvider(ABC):
    """Abstract interface for embedding text into vectors (§5.13)."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts.  Returns one vector per input text."""

    @abstractmethod
    def dimensions(self) -> int:
        """Return the dimensionality of this provider's embeddings."""

    @abstractmethod
    def model_id(self) -> str:
        """Return a unique string identifying the model (used for cache invalidation)."""


# ── Local provider (sentence-transformers) ────────────────────────────────────


class LocalEmbeddingProvider(EmbeddingProvider):
    """Local embedding provider using ``sentence-transformers/all-MiniLM-L6-v2``.

    The model is lazy-loaded on the first ``embed()`` call — startup is instant.
    Model size: ~90 MB; download happens once to the HuggingFace cache.
    """

    MODEL_NAME: str = "all-MiniLM-L6-v2"
    DIMENSIONS: int = 384

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or self.MODEL_NAME
        self._model: Any = None  # loaded lazily

    def _load(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
                self._model = SentenceTransformer(self._model_name)
                logger.info(
                    "LocalEmbeddingProvider: model loaded.",
                    extra={"model": self._model_name},
                )
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers is not installed.  "
                    "Run: pip install sentence-transformers"
                ) from exc
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed *texts* using the loaded model (offloaded to thread pool, TD-61)."""
        model = self._load()
        # model.encode() is CPU-bound — offload to thread pool to avoid blocking the event loop
        vectors = await asyncio.to_thread(model.encode, texts, convert_to_numpy=True)
        return [v.tolist() for v in vectors]

    def dimensions(self) -> int:
        return self.DIMENSIONS

    def model_id(self) -> str:
        return f"local/{self._model_name}"


# ── Data transfer objects ─────────────────────────────────────────────────────

from pydantic import BaseModel, Field  # noqa: E402


class EmbeddingItem(BaseModel):
    """A single item to embed and store."""

    source_type: str
    """Category of the source record: ``"memory"``, ``"note"``, or ``"entity"``."""

    source_id: str
    """ID of the record in its source table."""

    text: str
    """Text to embed."""


class EmbeddingSearchResult(BaseModel):
    """A single hit from a similarity search."""

    source_type: str
    """Category of the matched record."""

    source_id: str
    """ID of the matched record."""

    similarity: float
    """Cosine similarity score (0.0 – 1.0)."""


class ReindexResult(BaseModel):
    """Summary of a full or partial reindex operation."""

    total: int = 0
    """Total records examined."""

    updated: int = 0
    """Records that were re-embedded (new or content changed)."""

    errors: int = 0
    """Records that failed to embed."""

    duration_ms: int = 0
    """Wall-clock time for the operation in milliseconds."""


# ── Abstract store ────────────────────────────────────────────────────────────


class EmbeddingStore(ABC):
    """Abstract interface for storing and searching embedding vectors (§5.13)."""

    @abstractmethod
    async def add(self, source_type: str, source_id: str, text: str) -> None:
        """Embed *text* and store the vector.  Replaces an existing entry if present."""

    @abstractmethod
    async def add_batch(self, items: list[EmbeddingItem]) -> None:
        """Embed and store a batch of items.  More efficient than repeated ``add()``."""

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        source_types: list[str] | None = None,
        limit: int = 20,
        threshold: float | None = None,
    ) -> list[EmbeddingSearchResult]:
        """Embed *query* and return the top-K most similar stored records."""

    @abstractmethod
    async def delete(self, source_type: str, source_id: str) -> None:
        """Remove a stored embedding."""

    @abstractmethod
    async def reindex(self, source_type: str | None = None) -> ReindexResult:
        """Re-embed all items (or only items of *source_type*).

        Used when the embedding model changes or content has been updated externally.
        """

    @abstractmethod
    def model_id(self) -> str:
        """Return the model ID used by the underlying provider."""


# ── SQLiteEmbeddingStore ─────────────────────────────────────────────────────


class SQLiteEmbeddingStore(EmbeddingStore):
    """SQLite + numpy implementation of ``EmbeddingStore`` (§5.13).

    Search strategy (brute-force cosine similarity):
    1. Load all vectors for the requested ``source_types`` into memory.
    2. ``query_vec @ matrix.T`` — single numpy operation.
    3. Filter by threshold, sort by similarity, return top-K.

    Vectors are lazy-loaded from the DB and cached; cache is invalidated on add/delete.
    """

    DEFAULT_THRESHOLD: float = 0.65

    def __init__(
        self,
        db: aiosqlite.Connection,
        provider: EmbeddingProvider,
    ) -> None:
        self._db = db
        self._provider = provider
        # In-memory vector cache; keyed by frozenset of source_types filter (TD-78)
        # None means uninitialised; {} would mean "empty cache"
        self._cache: dict[tuple | None, dict[str, list[tuple[str, Any]]]] | None = None

    # ── Cache helpers ─────────────────────────────────────────────────────────

    def _invalidate(self, source_type: str | None = None) -> None:
        if self._cache is None:
            return
        if source_type is None:
            self._cache = None
        else:
            # Only evict cache entries that include this source_type
            keys_to_drop = []
            for key in self._cache:
                if key is None or source_type in key:
                    keys_to_drop.append(key)
            for key in keys_to_drop:
                del self._cache[key]

    async def _load_vectors(
        self, source_types: list[str] | None = None
    ) -> dict[str, list[tuple[str, Any]]]:
        """Load vectors from DB into a dict keyed by source_type.

        Results are cached per filter key (TD-78).
        """
        import numpy as np  # type: ignore[import-untyped]

        # Hashable cache key derived from the filter (TD-78)
        cache_key: tuple[str, ...] | None = (
            tuple(sorted(source_types)) if source_types is not None else None
        )

        if self._cache is not None and cache_key in self._cache:
            return self._cache[cache_key]

        if source_types:
            placeholders = ",".join("?" * len(source_types))
            async with self._db.execute(
                f"SELECT source_type, source_id, vector FROM embeddings WHERE source_type IN ({placeholders})",
                source_types,
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with self._db.execute(
                "SELECT source_type, source_id, vector FROM embeddings"
            ) as cur:
                rows = await cur.fetchall()

        result: dict[str, list[tuple[str, Any]]] = {}
        for row in rows:
            d = row_to_dict(row)
            stype = d["source_type"]
            sid = d["source_id"]
            vec = np.frombuffer(d["vector"], dtype=np.float32)
            result.setdefault(stype, []).append((sid, vec))

        if self._cache is None:
            self._cache = {}
        self._cache[cache_key] = result
        return result

    # ── EmbeddingStore interface ──────────────────────────────────────────────

    def model_id(self) -> str:
        return self._provider.model_id()

    async def add(self, source_type: str, source_id: str, text: str) -> None:
        """Embed *text* and upsert the vector for *(source_type, source_id)*."""
        import numpy as np

        vecs = await self._provider.embed([text])
        vec = np.array(vecs[0], dtype=np.float32)
        dims = len(vecs[0])
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        row_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT INTO embeddings (id, source_type, source_id, model_id, vector, dimensions, text_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_type, source_id) DO UPDATE
                    SET model_id    = excluded.model_id,
                        vector      = excluded.vector,
                        dimensions  = excluded.dimensions,
                        text_hash   = excluded.text_hash,
                        created_at  = excluded.created_at
                """,
                (row_id, source_type, source_id, self._provider.model_id(),
                 vec.tobytes(), dims, text_hash, now),
            )
        self._invalidate(source_type)

    async def add_batch(self, items: list[EmbeddingItem]) -> None:
        """Embed and store a batch of items."""
        if not items:
            return
        import numpy as np

        texts = [it.text for it in items]
        vecs = await self._provider.embed(texts)
        now = datetime.now(timezone.utc).isoformat()
        model = self._provider.model_id()

        async with write_transaction(self._db):
            for item, vec_list in zip(items, vecs):
                vec = np.array(vec_list, dtype=np.float32)
                text_hash = hashlib.sha256(item.text.encode()).hexdigest()[:16]
                row_id = str(uuid.uuid4())
                await self._db.execute(
                    """
                    INSERT INTO embeddings (id, source_type, source_id, model_id, vector, dimensions, text_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_type, source_id) DO UPDATE
                        SET model_id    = excluded.model_id,
                            vector      = excluded.vector,
                            dimensions  = excluded.dimensions,
                            text_hash   = excluded.text_hash,
                            created_at  = excluded.created_at
                    """,
                    (row_id, item.source_type, item.source_id, model,
                     vec.tobytes(), len(vec_list), text_hash, now),
                )
        # Invalidate cache entries for all affected source types
        affected_types = {it.source_type for it in items}
        for st in affected_types:
            self._invalidate(st)

    async def search(
        self,
        query: str,
        *,
        source_types: list[str] | None = None,
        limit: int = 20,
        threshold: float | None = None,
    ) -> list[EmbeddingSearchResult]:
        """Return the top-*limit* records most similar to *query*."""
        import numpy as np

        threshold = threshold if threshold is not None else self.DEFAULT_THRESHOLD

        # Embed the query
        q_vecs = await self._provider.embed([query])
        q_vec = np.array(q_vecs[0], dtype=np.float32)
        q_norm = np.linalg.norm(q_vec)
        if q_norm == 0:
            return []
        q_unit = q_vec / q_norm

        vectors_by_type = await self._load_vectors(source_types)

        candidates: list[tuple[str, str, float]] = []  # (type, id, score)
        for stype, entries in vectors_by_type.items():
            if not entries:
                continue
            ids, mats = zip(*entries)
            matrix = np.stack(mats, axis=0).astype(np.float32)
            # Cosine similarity: normalise rows then dot
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1, norms)
            normed = matrix / norms
            scores = normed @ q_unit  # (N,)
            for sid, score in zip(ids, scores.tolist()):
                if score >= threshold:
                    candidates.append((stype, sid, float(score)))

        candidates.sort(key=lambda x: x[2], reverse=True)
        return [
            EmbeddingSearchResult(source_type=t, source_id=i, similarity=s)
            for t, i, s in candidates[:limit]
        ]

    async def delete(self, source_type: str, source_id: str) -> None:
        """Remove the stored embedding for *(source_type, source_id)*."""
        async with write_transaction(self._db):
            await self._db.execute(
                "DELETE FROM embeddings WHERE source_type = ? AND source_id = ?",
                (source_type, source_id),
            )
        self._invalidate(source_type)

    async def reindex(self, source_type: str | None = None) -> ReindexResult:
        """Re-embed all tracked items from their source tables.

        Fetches text from the appropriate source table and calls ``add_batch``.
        Source tables queried:
        - ``note``   → ``vault_notes`` (content read from disk).
        - ``memory`` → ``memory_extracts``.
        - ``entity`` → ``entities`` (name + summary concatenated).
        """
        start = time.monotonic()
        result = ReindexResult()

        # Collect items per source type
        items: list[EmbeddingItem] = []

        if source_type in (None, "note"):
            async with self._db.execute(
                "SELECT id, filename FROM vault_notes"
            ) as cur:
                rows = await cur.fetchall()
            from app.paths import vault_dir
            vd = vault_dir()
            for row in rows:
                d = row_to_dict(row)
                p = vd / d["filename"]
                if await asyncio.to_thread(p.exists):
                    text = await asyncio.to_thread(p.read_text, encoding="utf-8")
                    items.append(EmbeddingItem(source_type="note", source_id=d["id"], text=text))
                    result.total += 1

        if source_type in (None, "memory"):
            async with self._db.execute(
                "SELECT id, content FROM memory_extracts WHERE status = 'active'"
            ) as cur:
                rows = await cur.fetchall()
            for row in rows:
                d = row_to_dict(row)
                items.append(EmbeddingItem(source_type="memory", source_id=d["id"], text=d["content"]))
                result.total += 1

        if source_type in (None, "entity"):
            async with self._db.execute(
                "SELECT id, name, summary FROM entities WHERE status = 'active'"
            ) as cur:
                rows = await cur.fetchall()
            for row in rows:
                d = row_to_dict(row)
                text = d["name"] + (" — " + d["summary"] if d.get("summary") else "")
                items.append(EmbeddingItem(source_type="entity", source_id=d["id"], text=text))
                result.total += 1

        # Process in sub-batches so partial failures are tracked per-batch
        _BATCH = 50
        for batch_start in range(0, max(len(items), 1), _BATCH):
            batch = items[batch_start : batch_start + _BATCH]
            if not batch:
                break
            try:
                await self.add_batch(batch)
                result.updated += len(batch)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Reindex batch failed (%d items, offset %d)",
                    len(batch),
                    batch_start,
                    exc_info=True,
                )
                result.errors += len(batch)

        result.duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "Embedding reindex complete.",
            extra={
                "source_type": source_type or "all",
                "total": result.total,
                "updated": result.updated,
                "errors": result.errors,
                "duration_ms": result.duration_ms,
            },
        )
        return result


# ── Module-level singleton ────────────────────────────────────────────────────

_embedding_store: SQLiteEmbeddingStore | None = None


def init_embedding_store(
    db: aiosqlite.Connection,
    provider: EmbeddingProvider | None = None,
) -> SQLiteEmbeddingStore:
    """Initialise and register the global ``SQLiteEmbeddingStore`` singleton.

    If *provider* is ``None``, the ``LocalEmbeddingProvider`` (sentence-transformers)
    is used by default (model is lazy-loaded on first embed call).
    """
    global _embedding_store  # noqa: PLW0603
    _embedding_store = SQLiteEmbeddingStore(db, provider or LocalEmbeddingProvider())
    logger.info(
        "EmbeddingStore initialised.",
        extra={"model": _embedding_store.model_id()},
    )
    return _embedding_store


def get_embedding_store() -> SQLiteEmbeddingStore:
    """Return the global ``SQLiteEmbeddingStore`` singleton.

    Raises ``RuntimeError`` if not yet initialised.
    """
    if _embedding_store is None:
        raise RuntimeError("EmbeddingStore not initialised.  Check app lifespan.")
    return _embedding_store
