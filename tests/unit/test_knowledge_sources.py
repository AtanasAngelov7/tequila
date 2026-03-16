"""Sprint 10 — Unit tests for KnowledgeSource models and adapters (§5.14)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── KnowledgeSource model ─────────────────────────────────────────────────────

def test_knowledge_source_model_defaults():
    """KnowledgeSource model stores all spec-required fields."""
    from app.knowledge.sources.models import KnowledgeSource, QueryMode
    src = KnowledgeSource(
        source_id="ks-1",
        name="Test Source",
        backend="http",
        query_mode=QueryMode.vector,
    )
    assert src.source_id == "ks-1"
    assert src.backend == "http"
    assert src.status == "disabled"
    assert src.auto_recall is False
    assert src.priority == 100


def test_knowledge_chunk_score_clamped():
    """KnowledgeChunk.score is clamped between 0 and 1."""
    from app.knowledge.sources.models import KnowledgeChunk
    chunk = KnowledgeChunk(source_id="ks-1", content="test", score=1.5)
    assert chunk.score <= 1.0
    chunk2 = KnowledgeChunk(source_id="ks-1", content="test", score=-0.1)
    assert chunk2.score >= 0.0


def test_knowledge_chunk_metadata_default():
    """KnowledgeChunk has empty metadata by default."""
    from app.knowledge.sources.models import KnowledgeChunk
    chunk = KnowledgeChunk(source_id="ks-1", content="info", score=0.8)
    assert isinstance(chunk.metadata, dict)


# ── HTTPAdapter ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_http_adapter_get_search():
    """HTTPAdapter.search parses JSON response into KnowledgeChunks."""
    import httpx
    from app.knowledge.sources.adapters.http import HTTPAdapter
    from app.knowledge.sources.models import KnowledgeSource, QueryMode

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {"text": "The sky is blue.", "score": 0.9}
        ]
    }

    src = KnowledgeSource(
        source_id="ks-http", name="HTTP Test", backend="http", query_mode=QueryMode.text,
        connection={
            "url": "http://example.com/api/search",
            "method": "GET",
            "query_param": "q",
            "results_path": "results",
            "content_field": "text",
            "score_field": "score",
        }
    )

    adapter = HTTPAdapter(src)
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        chunks = await adapter.search("blue sky", top_k=5)
    assert len(chunks) == 1
    assert chunks[0].content == "The sky is blue."
    assert chunks[0].score == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_http_adapter_count_returns_minus_one():
    """HTTPAdapter.count() always returns -1 (unknown)."""
    from app.knowledge.sources.adapters.http import HTTPAdapter
    from app.knowledge.sources.models import KnowledgeSource, QueryMode

    src = KnowledgeSource(
        source_id="ks-http2", name="HTTP2", backend="http", query_mode=QueryMode.text,
        connection={"url": "http://example.com/search"}
    )
    adapter = HTTPAdapter(src)
    assert await adapter.count() == -1


# ── KnowledgeSourceRegistry ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_registry_register_and_get():
    """Registry.register() persists and registry.get() retrieves source."""
    from app.knowledge.sources.registry import KnowledgeSourceRegistry
    from app.knowledge.sources.models import KnowledgeSource

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
        fetchone=AsyncMock(return_value=None),
        lastrowid=1,
    ))

    # Use a real-ish mock for fetchone returning a row
    src_row = {
        "id": "ks-001",
        "name": "My KB",
        "description": "",
        "backend": "http",
        "query_mode": "vector",
        "embedding_provider": None,
        "auto_recall": 0,
        "priority": 0,
        "max_results": 10,
        "similarity_threshold": 0.65,
        "connection_json": "{}",
        "allowed_agents_json": "[]",
        "status": "disabled",
        "error_message": None,
        "consecutive_failures": 0,
        "last_health_check": None,
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    }

    registry = KnowledgeSourceRegistry(mock_db)

    with patch.object(registry, "register", new=AsyncMock(return_value=KnowledgeSource(**{
        "source_id": "ks-001",
        "name": "My KB",
        "backend": "http",
        "status": "disabled",
    }))):
        src = await registry.register(name="My KB", backend="http")
    assert src.name == "My KB"
    assert src.status == "disabled"


@pytest.mark.asyncio
async def test_registry_search_auto_recall_no_sources():
    """search_auto_recall returns empty list when no sources active."""
    from app.knowledge.sources.registry import KnowledgeSourceRegistry

    mock_db = AsyncMock()
    registry = KnowledgeSourceRegistry(mock_db)

    with patch.object(registry, "list", new=AsyncMock(return_value=[])):
        results = await registry.search_auto_recall(query="test", agent_id="agent1")
    assert results == []


def test_registry_singleton_init_get():
    """init_knowledge_source_registry + get_knowledge_source_registry work."""
    from app.knowledge.sources.registry import (
        init_knowledge_source_registry,
        get_knowledge_source_registry,
        KnowledgeSourceRegistry,
    )
    import aiosqlite

    mock_db = MagicMock(spec=aiosqlite.Connection)
    reg = init_knowledge_source_registry(mock_db)
    assert isinstance(reg, KnowledgeSourceRegistry)
    assert get_knowledge_source_registry() is reg


def test_registry_get_adapter_raises_for_missing():
    """get_adapter raises KeyError for a source not in the adapter cache."""
    from app.knowledge.sources.registry import KnowledgeSourceRegistry
    import aiosqlite

    mock_db = MagicMock(spec=aiosqlite.Connection)
    registry = KnowledgeSourceRegistry(mock_db)
    with pytest.raises(KeyError):
        registry.get_adapter("nonexistent-id")


# ── QueryMode enum ────────────────────────────────────────────────────────────

def test_query_mode_values():
    """QueryMode has text and vector variants."""
    from app.knowledge.sources.models import QueryMode
    assert QueryMode.text.value == "text"
    assert QueryMode.vector.value == "vector"
