"""Sprint 09 — Unit tests for the embedding engine (§5.13)."""
from __future__ import annotations

import pytest
import unittest.mock as mock


# ── Fake provider ─────────────────────────────────────────────────────────────

class FakeEmbeddingProvider:
    """Returns deterministic pseudo-embeddings for testing (no model download)."""

    _DIMS = 4

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Deterministic: hash-based unit vectors so similar texts get similar vecs
        results = []
        for text in texts:
            h = hash(text[:10]) % 1000  # crude hash
            import math
            angle = (h / 1000.0) * 2 * math.pi
            vec = [math.cos(angle), math.sin(angle), 0.0, 0.0]
            results.append(vec)
        return results

    def dimensions(self) -> int:
        return self._DIMS

    def model_id(self) -> str:
        return "fake/test-model"


@pytest.fixture
async def emb_store(migrated_db):
    """SQLiteEmbeddingStore backed by a test DB and fake provider."""
    from app.knowledge.embeddings import SQLiteEmbeddingStore, init_embedding_store
    store = SQLiteEmbeddingStore(migrated_db, FakeEmbeddingProvider())
    # Also set the module singleton so get_embedding_store() works
    import app.knowledge.embeddings as _mod
    _mod._embedding_store = store
    return store


# ── add / delete ──────────────────────────────────────────────────────────────


async def test_add_stores_vector(emb_store, migrated_db):
    """add() persists a row in the embeddings table."""
    await emb_store.add("note", "note-123", "Hello world")
    async with migrated_db.execute(
        "SELECT source_type, source_id FROM embeddings WHERE source_id = 'note-123'"
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row[0] == "note"


async def test_add_upserts_on_duplicate(emb_store, migrated_db):
    """Calling add() twice for the same source replaces the vector."""
    await emb_store.add("note", "n1", "first text")
    await emb_store.add("note", "n1", "updated text")
    async with migrated_db.execute(
        "SELECT COUNT(*) FROM embeddings WHERE source_id = 'n1'"
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == 1


async def test_delete_removes_vector(emb_store, migrated_db):
    """delete() removes the embedding row."""
    await emb_store.add("memory", "mem-abc", "some memory")
    await emb_store.delete("memory", "mem-abc")
    async with migrated_db.execute(
        "SELECT COUNT(*) FROM embeddings WHERE source_id = 'mem-abc'"
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == 0


# ── add_batch ─────────────────────────────────────────────────────────────────


async def test_add_batch_stores_multiple(emb_store, migrated_db):
    """add_batch() stores all items in one transaction."""
    from app.knowledge.embeddings import EmbeddingItem
    items = [
        EmbeddingItem(source_type="note", source_id=f"n{i}", text=f"text {i}")
        for i in range(5)
    ]
    await emb_store.add_batch(items)
    async with migrated_db.execute(
        "SELECT COUNT(*) FROM embeddings WHERE source_type = 'note'"
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == 5


async def test_add_batch_empty_is_noop(emb_store):
    """add_batch([]) does nothing and doesn't raise."""
    await emb_store.add_batch([])  # should not raise


# ── search ────────────────────────────────────────────────────────────────────


async def test_search_returns_similar(emb_store):
    """search() returns results with similarity >= threshold."""
    await emb_store.add("note", "n1", "Python programming guide")
    await emb_store.add("note", "n2", "Python programming guide")
    # Searching for the exact same text should return high similarity
    results = await emb_store.search("Python programming guide", threshold=0.0)
    assert len(results) >= 1
    assert any(r.source_id == "n1" for r in results)


async def test_search_respects_source_type_filter(emb_store):
    """search() with source_types filter only returns matching types."""
    await emb_store.add("note", "n1", "hello world")
    await emb_store.add("memory", "m1", "hello world")
    results = await emb_store.search("hello world", source_types=["note"], threshold=0.0)
    assert all(r.source_type == "note" for r in results)


async def test_search_empty_store_returns_empty(emb_store):
    """search() with no vectors returns empty list."""
    results = await emb_store.search("query", threshold=0.0)
    assert results == []


async def test_search_results_sorted_by_score(emb_store):
    """search() returns results sorted descending by similarity."""
    # Add two identical vectors — scores should be 1.0
    await emb_store.add("note", "same1", "identical text exact")
    await emb_store.add("note", "same2", "identical text exact")
    results = await emb_store.search("identical text exact", threshold=0.0, limit=10)
    scores = [r.similarity for r in results]
    assert scores == sorted(scores, reverse=True)


# ── reindex ───────────────────────────────────────────────────────────────────


async def test_reindex_empty_db(emb_store):
    """reindex() with no source records returns total=0."""
    result = await emb_store.reindex()
    assert result.total == 0
    assert result.errors == 0


async def test_reindex_result_has_duration(emb_store):
    """reindex() result includes duration_ms."""
    result = await emb_store.reindex()
    assert result.duration_ms >= 0


async def test_model_id_returns_provider_id(emb_store):
    """model_id() returns the provider's model identifier."""
    assert emb_store.model_id() == "fake/test-model"
