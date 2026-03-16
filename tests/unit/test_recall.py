"""Sprint 10 — Unit tests for RecallPipeline (§5.6)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Config model ───────────────────────────────────────────────────────────────

def test_recall_config_defaults():
    """RecallConfig has sensible defaults."""
    from app.memory.recall import RecallConfig
    cfg = RecallConfig()
    assert "identity" in cfg.always_recall_types
    assert "preference" in cfg.always_recall_types
    assert cfg.similarity_threshold == 0.65
    assert cfg.entity_match_bonus == 0.2
    assert cfg.max_per_turn_results == 15


def test_recall_config_custom():
    """RecallConfig accepts custom values."""
    from app.memory.recall import RecallConfig
    cfg = RecallConfig(similarity_threshold=0.8, max_per_turn_results=5)
    assert cfg.similarity_threshold == 0.8
    assert cfg.max_per_turn_results == 5


# ── Singleton ─────────────────────────────────────────────────────────────────

def test_init_recall_pipeline_returns_instance():
    """init_recall_pipeline() creates and returns the singleton."""
    from app.memory.recall import init_recall_pipeline, get_recall_pipeline
    pipe = init_recall_pipeline()
    assert pipe is not None
    assert get_recall_pipeline() is pipe


def test_get_recall_pipeline_raises_before_init(monkeypatch):
    """get_recall_pipeline() raises RuntimeError if not initialised."""
    import app.memory.recall as recall_mod
    orig = recall_mod._recall_pipeline
    recall_mod._recall_pipeline = None
    try:
        with pytest.raises(RuntimeError, match="not initialised"):
            recall_mod.get_recall_pipeline()
    finally:
        recall_mod._recall_pipeline = orig


# ── Helpers ───────────────────────────────────────────────────────────────────

def test_estimate_tokens():
    """_estimate_tokens returns a positive integer."""
    from app.memory.recall import _estimate_tokens
    assert _estimate_tokens("Hello world") > 0
    assert _estimate_tokens("") == 1  # floor of 1


def test_format_memory_block_empty():
    """_format_memory_block with empty list returns empty string."""
    from app.memory.recall import _format_memory_block
    assert _format_memory_block([]) == ""


def test_format_memory_block_content():
    """_format_memory_block renders memory rows."""
    from app.memory.recall import _format_memory_block
    rows = [{"content": "Alice likes cats", "memory_type": "preference", "confidence": 1.0}]
    out = _format_memory_block(rows)
    assert "Alice likes cats" in out
    assert "preference" in out


def test_format_knowledge_block_empty():
    """_format_knowledge_block with no chunks returns empty string."""
    from app.memory.recall import _format_knowledge_block
    assert _format_knowledge_block([]) == ""


def test_format_knowledge_block_renders_source_prefix():
    """_format_knowledge_block prefixes each chunk with source id."""
    from app.memory.recall import _format_knowledge_block
    chunk = MagicMock()
    chunk.source_id = "kb-001"
    chunk.content = "Python was created by Guido van Rossum."
    out = _format_knowledge_block([chunk])
    assert "[kb-001]" in out
    assert "Guido" in out
    assert "## Knowledge Sources" in out


def test_dedup_against_always():
    """_dedup_against_always removes candidates already in always content."""
    from app.memory.recall import _dedup_against_always
    always = "Alice likes blue"
    candidates = [
        {"content": "Alice likes blue", "id": "m1"},
        {"content": "Bob prefers red", "id": "m2"},
    ]
    result = _dedup_against_always(candidates, always)
    assert len(result) == 1
    assert result[0]["id"] == "m2"


def test_dedup_against_always_empty_always():
    """_dedup_against_always returns all candidates when always is empty."""
    from app.memory.recall import _dedup_against_always
    candidates = [{"content": "anything", "id": "x"}]
    assert _dedup_against_always(candidates, "") == candidates


# ── Stage 1: load_always_recall ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_load_always_recall_with_unavailable_store():
    """load_always_recall returns empty string when store is unavailable."""
    with patch("app.memory.store.get_memory_store") as mock_store_fn:
        mock_store_fn.side_effect = RuntimeError("not init")
        from app.memory.recall import RecallPipeline as RP
        r = await RP().load_always_recall("s1")
    assert r == ""


@pytest.mark.asyncio
async def test_load_always_recall_with_mock_store():
    """load_always_recall returns formatted block from memory store."""
    from app.memory.recall import RecallPipeline, RecallConfig

    mock_mem = MagicMock()
    mock_mem.id = "m1"
    mock_mem.content = "User prefers dark mode."
    mock_mem.memory_type = "preference"
    mock_mem.confidence = 1.0

    mock_store = AsyncMock()
    mock_store.list.return_value = [mock_mem]

    with patch("app.memory.store.get_memory_store", return_value=mock_store):
        pipe = RecallPipeline(config=RecallConfig(always_recall_types=["preference"]))
        result = await pipe.load_always_recall("session1")

    assert "dark mode" in result


# ── Stage 2: recall_for_turn ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recall_for_turn_degrades_gracefully():
    """recall_for_turn returns empty strings when all sub-systems fail."""
    from app.memory.recall import RecallPipeline

    pipe = RecallPipeline()
    with patch("app.knowledge.embeddings.get_embedding_store") as mock_es:
        mock_es.side_effect = RuntimeError("No embedding store")
        with patch("app.knowledge.sources.registry.get_knowledge_source_registry") as mock_kb:
            mock_kb.side_effect = RuntimeError("No KB registry")
            mem_str, kb_str = await pipe.recall_for_turn("hello", "s1")

    assert isinstance(mem_str, str)
    assert isinstance(kb_str, str)
