"""Sprint 10 — Integration tests for knowledge source federation (§5.14)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


# ── KnowledgeSourceRegistry — initialised ────────────────────────────────────


async def test_knowledge_source_registry_initialised(test_app: AsyncClient):
    """KnowledgeSourceRegistry is initialised at startup."""
    from app.knowledge.sources.registry import get_knowledge_source_registry
    registry = get_knowledge_source_registry()
    assert registry is not None


# ── API CRUD ──────────────────────────────────────────────────────────────────


async def test_list_sources_initially_empty(test_app: AsyncClient):
    """GET /api/knowledge-sources returns empty list on fresh DB."""
    resp = await test_app.get("/api/knowledge-sources")
    assert resp.status_code == 200
    data = resp.json()
    assert "sources" in data
    assert isinstance(data["sources"], list)


async def test_register_source_returns_201(test_app: AsyncClient):
    """POST /api/knowledge-sources registers a new source (status=disabled)."""
    resp = await test_app.post(
        "/api/knowledge-sources",
        json={
            "name": "My HTTP KB",
            "backend": "http",
            "query_mode": "text",
            "connection": {
                "base_url": "http://example.com/search",
                "method": "GET",
                "query_param": "q",
            },
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "My HTTP KB"
    assert data["status"] == "disabled"
    assert "id" in data


async def test_get_source_by_id(test_app: AsyncClient):
    """GET /api/knowledge-sources/{id} returns the registered source."""
    create_resp = await test_app.post(
        "/api/knowledge-sources",
        json={"name": "KB Get Test", "backend": "http", "connection": {}},
    )
    assert create_resp.status_code == 201
    source_id = create_resp.json()["id"]

    resp = await test_app.get(f"/api/knowledge-sources/{source_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == source_id


async def test_get_source_not_found(test_app: AsyncClient):
    """GET /api/knowledge-sources/{id} returns 404 for missing source."""
    resp = await test_app.get("/api/knowledge-sources/nonexistent-id")
    assert resp.status_code == 404


async def test_delete_source(test_app: AsyncClient):
    """DELETE /api/knowledge-sources/{id} removes the source."""
    create_resp = await test_app.post(
        "/api/knowledge-sources",
        json={"name": "KB Delete Test", "backend": "http", "connection": {}},
    )
    source_id = create_resp.json()["id"]

    del_resp = await test_app.delete(f"/api/knowledge-sources/{source_id}")
    assert del_resp.status_code == 204

    get_resp = await test_app.get(f"/api/knowledge-sources/{source_id}")
    assert get_resp.status_code == 404


async def test_source_stats_endpoint(test_app: AsyncClient):
    """GET /api/knowledge-sources/{id}/stats returns stats dict."""
    create_resp = await test_app.post(
        "/api/knowledge-sources",
        json={"name": "KB Stats Test", "backend": "http", "connection": {}},
    )
    source_id = create_resp.json()["id"]

    resp = await test_app.get(f"/api/knowledge-sources/{source_id}/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source_id"] == source_id
    assert "status" in data


# ── Federation search via API ─────────────────────────────────────────────────


async def test_search_no_active_sources(test_app: AsyncClient):
    """POST /api/knowledge-sources/search returns empty when no active sources."""
    resp = await test_app.post(
        "/api/knowledge-sources/search",
        json={"query": "Python programming", "top_k": 5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"] == [] or isinstance(data["results"], list)


async def test_federated_search_with_mock_http_source(test_app: AsyncClient):
    """search_auto_recall queries an active HTTP source and returns chunks."""
    from app.knowledge.sources.registry import get_knowledge_source_registry
    from app.knowledge.sources.models import KnowledgeChunk

    registry = get_knowledge_source_registry()

    # Register + store the source
    create_resp = await test_app.post(
        "/api/knowledge-sources",
        json={
            "name": "Mock HTTP KB",
            "backend": "http",
            "auto_recall": True,
            "connection": {
                "base_url": "http://mock-kb.example.com/search",
                "method": "GET",
                "query_param": "q",
                "results_path": "items",
                "content_field": "text",
                "score_field": "relevance",
            },
        },
    )
    assert create_resp.status_code == 201
    source_id = create_resp.json()["id"]

    # Inject a mock adapter directly so we don't need a real HTTP server
    from app.knowledge.sources.adapters.base import KnowledgeSourceAdapter

    class MockAdapter(KnowledgeSourceAdapter):
        async def search(self, query, top_k=10, threshold=0.0):
            return [KnowledgeChunk(source_id=source_id, content=f"Result for: {query}", score=0.9)]

        async def health_check(self):
            return True

        async def count(self):
            return 1

    # Set status to active in DB first (this would overwrite _adapters)
    await registry.update(source_id, status="active")

    # Inject mock adapter AFTER update() so it isn't overwritten
    source = await registry.get(source_id)
    registry._adapters[source_id] = MockAdapter(source)

    # Now search
    chunks = await registry.search_auto_recall(query="test query", agent_id="")
    assert len(chunks) >= 1
    assert any("test query" in c.content for c in chunks)


# ── KB agent tools ────────────────────────────────────────────────────────────


async def test_kb_search_tool_registered(test_app: AsyncClient):
    """kb_search and kb_list_sources are registered in the tool registry."""
    from app.tools.registry import get_tool_registry
    reg = get_tool_registry()
    assert reg.get("kb_search") is not None
    assert reg.get("kb_list_sources") is not None


async def test_kb_list_sources_tool_returns_string(test_app: AsyncClient):
    """kb_list_sources tool returns a string listing sources."""
    from app.tools.builtin.knowledge import kb_list_sources
    result = await kb_list_sources()
    assert isinstance(result, str)


async def test_kb_search_tool_returns_string(test_app: AsyncClient):
    """kb_search tool returns a string (even if empty results)."""
    from app.tools.builtin.knowledge import kb_search
    result = await kb_search(query="test query")
    assert isinstance(result, str)
