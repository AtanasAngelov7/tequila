"""Sprint 11 — Unit tests for agent memory tools (§5.7)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mock_memory(mid: str = "m001", content: str = "Test memory", **kwargs):
    m = MagicMock()
    m.id = mid
    m.memory_id = mid  # kept for compatibility with any legacy references
    m.content = content
    m.memory_type = kwargs.get("memory_type", "fact")
    m.pinned = kwargs.get("pinned", False)
    m.always_recall = kwargs.get("always_recall", False)
    m.status = kwargs.get("status", "active")
    m.decay_score = kwargs.get("decay_score", 1.0)
    m.entity_ids = kwargs.get("entity_ids", [])
    return m


def _mock_entity(eid: str = "e001", name: str = "Alice", **kwargs):
    e = MagicMock()
    e.entity_id = eid
    e.name = name
    e.entity_type = kwargs.get("entity_type", "person")
    e.summary = kwargs.get("summary", "")
    e.aliases = kwargs.get("aliases", [])
    e.status = "active"
    return e


# ── memory_save ───────────────────────────────────────────────────────────────


async def test_memory_save_success():
    """memory_save() returns a success message with the memory ID."""
    mock_store = AsyncMock()
    mock_store.create = AsyncMock(return_value=_mock_memory("m999", "Saved content"))

    with patch("app.memory.store.get_memory_store", return_value=mock_store):
        from app.tools.builtin.memory import memory_save
        result = await memory_save("Saved content", memory_type="fact")

    assert "m999" in result
    assert "saved" in result.lower()


async def test_memory_save_store_unavailable():
    """memory_save() returns a graceful error when the store is unavailable."""
    with patch("app.memory.store.get_memory_store", side_effect=RuntimeError):
        from app.tools.builtin.memory import memory_save
        result = await memory_save("some content")
    assert "not available" in result.lower()


# ── memory_update ─────────────────────────────────────────────────────────────


async def test_memory_update_success():
    """memory_update() calls store.update() and returns success message."""
    mock_store = AsyncMock()
    mock_store.get = AsyncMock(return_value=_mock_memory("m1", "old"))
    mock_store.update = AsyncMock(return_value=_mock_memory("m1", "new"))

    with patch("app.memory.store.get_memory_store", return_value=mock_store):
        from app.tools.builtin.memory import memory_update
        result = await memory_update("m1", content="new")

    mock_store.update.assert_called_once()
    assert "m1" in result


async def test_memory_update_no_args():
    """memory_update() with no changes returns an informative message."""
    with patch("app.memory.store.get_memory_store"):
        from app.tools.builtin.memory import memory_update
        result = await memory_update("m1")
    assert "nothing to update" in result.lower()


# ── memory_forget ─────────────────────────────────────────────────────────────


async def test_memory_forget_calls_soft_delete():
    """memory_forget() calls store.soft_delete()."""
    mock_store = AsyncMock()
    mock_store.get = AsyncMock(return_value=_mock_memory())
    mock_store.soft_delete = AsyncMock()

    with patch("app.memory.store.get_memory_store", return_value=mock_store):
        from app.tools.builtin.memory import memory_forget
        result = await memory_forget("m001")

    mock_store.soft_delete.assert_called_once_with("m001")
    assert "forgotten" in result.lower()


# ── memory_search ─────────────────────────────────────────────────────────────


async def test_memory_search_uses_embedding_store():
    """memory_search() uses the embedding store when available."""
    hit = MagicMock()
    hit.source_id = "m001"
    hit.score = 0.78
    hit.content = "User likes coffee"

    mock_emb = AsyncMock()
    mock_emb.search = AsyncMock(return_value=[hit])

    with patch("app.knowledge.embeddings.get_embedding_store", return_value=mock_emb):
        from app.tools.builtin.memory import memory_search
        result = await memory_search("coffee preferences")

    assert "m001" in result
    assert "0.78" in result


async def test_memory_search_fallback_to_text():
    """memory_search() falls back to text search if embeddings unavailable."""
    mock_store = AsyncMock()
    mock_store.list = AsyncMock(return_value=[_mock_memory("m002", "coffee fact")])

    with patch("app.knowledge.embeddings.get_embedding_store", side_effect=RuntimeError):
        with patch("app.memory.store.get_memory_store", return_value=mock_store):
            from app.tools.builtin.memory import memory_search
            result = await memory_search("coffee")

    assert "m002" in result


async def test_memory_search_no_results():
    """memory_search() returns informative message when nothing matches."""
    mock_emb = AsyncMock()
    mock_emb.search = AsyncMock(return_value=[])
    mock_store = AsyncMock()
    mock_store.list = AsyncMock(return_value=[])

    with patch("app.knowledge.embeddings.get_embedding_store", return_value=mock_emb):
        with patch("app.memory.store.get_memory_store", return_value=mock_store):
            from app.tools.builtin.memory import memory_search
            result = await memory_search("nonexistent query thing")

    assert "no" in result.lower()


# ── memory_list ───────────────────────────────────────────────────────────────


async def test_memory_list_returns_formatted_list():
    """memory_list() formats and returns memories."""
    mems = [_mock_memory("m1", "Fact one"), _mock_memory("m2", "Fact two", pinned=True)]
    mock_store = AsyncMock()
    mock_store.list = AsyncMock(return_value=mems)

    with patch("app.memory.store.get_memory_store", return_value=mock_store):
        from app.tools.builtin.memory import memory_list
        result = await memory_list()

    assert "m1" in result
    assert "m2" in result
    assert "[pinned]" in result


async def test_memory_list_empty():
    """memory_list() returns informative message when empty."""
    mock_store = AsyncMock()
    mock_store.list = AsyncMock(return_value=[])

    with patch("app.memory.store.get_memory_store", return_value=mock_store):
        from app.tools.builtin.memory import memory_list
        result = await memory_list()

    assert "no" in result.lower()


# ── memory_pin / memory_unpin ─────────────────────────────────────────────────


async def test_memory_pin():
    """memory_pin() calls store.update() with pinned=True."""
    mock_store = AsyncMock()
    mock_store.update = AsyncMock(return_value=_mock_memory(pinned=True))

    with patch("app.memory.store.get_memory_store", return_value=mock_store):
        from app.tools.builtin.memory import memory_pin
        result = await memory_pin("m001")

    mock_store.update.assert_called_once_with("m001", pinned=True)
    assert "pinned" in result.lower()


async def test_memory_unpin():
    """memory_unpin() calls store.update() with pinned=False."""
    mock_store = AsyncMock()
    mock_store.update = AsyncMock(return_value=_mock_memory())

    with patch("app.memory.store.get_memory_store", return_value=mock_store):
        from app.tools.builtin.memory import memory_unpin
        result = await memory_unpin("m001")

    mock_store.update.assert_called_once_with("m001", pinned=False)
    assert "unpinned" in result.lower()


# ── memory_link ───────────────────────────────────────────────────────────────


async def test_memory_link_entity():
    """memory_link() with entity_id calls store.link_entity()."""
    mock_store = AsyncMock()
    mock_store.link_entity = AsyncMock()

    with patch("app.memory.store.get_memory_store", return_value=mock_store):
        with patch("app.knowledge.graph.get_graph_store", side_effect=RuntimeError):
            from app.tools.builtin.memory import memory_link
            result = await memory_link("m001", entity_id="e001")

    mock_store.link_entity.assert_called_once_with("m001", "e001")
    assert "e001" in result


async def test_memory_link_graph_edge():
    """memory_link() with target_id creates a graph edge."""
    mock_gs = AsyncMock()
    mock_gs.add_edge = AsyncMock(return_value=MagicMock())

    with patch("app.memory.store.get_memory_store", side_effect=RuntimeError):
        with patch("app.knowledge.graph.get_graph_store", return_value=mock_gs):
            from app.tools.builtin.memory import memory_link
            result = await memory_link("m001", target_id="m002", target_type="memory")

    mock_gs.add_edge.assert_called_once()
    assert "m002" in result


async def test_memory_link_no_args():
    """memory_link() with no entity or target returns informative message."""
    with patch("app.memory.store.get_memory_store"), \
         patch("app.knowledge.graph.get_graph_store"):
        from app.tools.builtin.memory import memory_link
        result = await memory_link("m001")

    assert "no action" in result.lower()


# ── entity_create ─────────────────────────────────────────────────────────────


async def test_entity_create_success():
    """entity_create() calls store.create() and returns entity ID."""
    mock_store = AsyncMock()
    mock_store.create = AsyncMock(return_value=_mock_entity("e42", "Bob"))

    with patch("app.memory.entity_store.get_entity_store", return_value=mock_store):
        from app.tools.builtin.memory import entity_create
        result = await entity_create("Bob", entity_type="person")

    assert "e42" in result
    assert "Bob" in result


# ── entity_merge ──────────────────────────────────────────────────────────────


async def test_entity_merge_combines_aliases():
    """entity_merge() merges aliases from source into target."""
    source = _mock_entity("src", "Alias Name", aliases=["AName", "a.n."])
    target = _mock_entity("tgt", "Target Entity")

    mock_store = AsyncMock()
    mock_store.get = AsyncMock(side_effect=lambda eid: source if eid == "src" else target)
    mock_store.add_alias = AsyncMock()
    mock_store.get_memories = AsyncMock(return_value=[])
    mock_store.update = AsyncMock()

    with patch("app.memory.entity_store.get_entity_store", return_value=mock_store):
        with patch("app.memory.store.get_memory_store", side_effect=RuntimeError):
            from app.tools.builtin.memory import entity_merge
            result = await entity_merge("src", "tgt")

    assert "merged" in result.lower()
    # add_alias should have been called for each alias + source name
    assert mock_store.add_alias.call_count >= len(source.aliases)


# ── entity_update ─────────────────────────────────────────────────────────────


async def test_entity_update_calls_store():
    """entity_update() calls store.update()."""
    mock_store = AsyncMock()
    mock_store.update = AsyncMock()

    with patch("app.memory.entity_store.get_entity_store", return_value=mock_store):
        from app.tools.builtin.memory import entity_update
        result = await entity_update("e001", summary="Updated summary")

    mock_store.update.assert_called_once()
    assert "updated" in result.lower()


# ── entity_search ─────────────────────────────────────────────────────────────


async def test_entity_search_returns_names():
    """entity_search() returns entity names and IDs."""
    entities = [_mock_entity("e1", "Alice"), _mock_entity("e2", "Bob")]
    mock_store = AsyncMock()
    mock_store.list = AsyncMock(return_value=entities)

    with patch("app.memory.entity_store.get_entity_store", return_value=mock_store):
        from app.tools.builtin.memory import entity_search
        result = await entity_search("person")

    assert "Alice" in result
    assert "Bob" in result


async def test_entity_search_empty():
    """entity_search() returns informative message when no entities found."""
    mock_store = AsyncMock()
    mock_store.list = AsyncMock(return_value=[])

    with patch("app.memory.entity_store.get_entity_store", return_value=mock_store):
        from app.tools.builtin.memory import entity_search
        result = await entity_search("nobody")

    assert "no" in result.lower()


# ── memory_extract_now ────────────────────────────────────────────────────────


async def test_memory_extract_now_success():
    """memory_extract_now() calls pipeline.run() and returns extraction summary."""
    extract_result = MagicMock()
    extract_result.memories_created = ["m1", "m2"]

    mock_pipeline = AsyncMock()
    mock_pipeline.run = AsyncMock(return_value=extract_result)

    with patch("app.memory.extraction.get_extraction_pipeline", return_value=mock_pipeline):
        from app.tools.builtin.memory import memory_extract_now
        result = await memory_extract_now("The user works at Acme Corp.")

    mock_pipeline.run.assert_called_once()
    assert "2" in result


async def test_memory_extract_now_pipeline_unavailable():
    """memory_extract_now() returns graceful error when pipeline unavailable."""
    with patch("app.memory.extraction.get_extraction_pipeline", side_effect=RuntimeError):
        from app.tools.builtin.memory import memory_extract_now
        result = await memory_extract_now("some text")

    assert "not available" in result.lower()
