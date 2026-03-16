"""Sprint 11 — Integration tests for the knowledge graph API and GraphStore (§5.11)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


# ── Startup ───────────────────────────────────────────────────────────────────


async def test_graph_store_initialised(test_app: AsyncClient):
    """GraphStore is available after application startup."""
    from app.knowledge.graph import get_graph_store
    gs = get_graph_store()
    assert gs is not None


async def test_audit_log_initialised(test_app: AsyncClient):
    """MemoryAuditLog is available after application startup."""
    from app.memory.audit import get_memory_audit
    audit = get_memory_audit()
    assert audit is not None


# ── Edge CRUD via API ─────────────────────────────────────────────────────────


async def test_post_graph_edge(test_app: AsyncClient):
    """POST /api/graph/edges creates an edge and returns 201."""
    payload = {
        "source_id": "mem-api-1",
        "source_type": "memory",
        "target_id": "ent-api-1",
        "target_type": "entity",
        "edge_type": "extracted_from",
        "weight": 0.9,
    }
    resp = await test_app.post("/api/graph/edges", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["source_id"] == "mem-api-1"
    assert data["edge_type"] == "extracted_from"
    assert data["id"] is not None


async def test_get_full_graph(test_app: AsyncClient):
    """GET /api/graph returns edges with summary counts."""
    # Add an edge first
    await test_app.post("/api/graph/edges", json={
        "source_id": "s-full", "source_type": "memory",
        "target_id": "t-full", "target_type": "entity",
        "edge_type": "references",
    })
    resp = await test_app.get("/api/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert "edges" in data
    assert "total_edges" in data


async def test_get_graph_stats(test_app: AsyncClient):
    """GET /api/graph/stats returns statistics about the graph."""
    resp = await test_app.get("/api/graph/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_edges" in data
    assert "total_nodes" in data
    assert "edge_counts" in data


async def test_delete_graph_edge(test_app: AsyncClient):
    """DELETE /api/graph/edges/{id} removes an edge."""
    # Create first
    resp = await test_app.post("/api/graph/edges", json={
        "source_id": "del-src", "source_type": "memory",
        "target_id": "del-tgt", "target_type": "memory",
        "edge_type": "linked_to",
    })
    assert resp.status_code == 201
    edge_id = resp.json()["id"]

    resp2 = await test_app.delete(f"/api/graph/edges/{edge_id}")
    assert resp2.status_code == 204


async def test_get_node_neighborhood(test_app: AsyncClient):
    """GET /api/graph/node/{id}/neighborhood returns connected nodes."""
    # Build a 2-hop chain
    await test_app.post("/api/graph/edges", json={
        "source_id": "hub-nb", "source_type": "memory",
        "target_id": "spoke-nb1", "target_type": "memory",
        "edge_type": "semantic_similar", "weight": 0.88,
    })
    await test_app.post("/api/graph/edges", json={
        "source_id": "spoke-nb1", "source_type": "memory",
        "target_id": "spoke-nb2", "target_type": "memory",
        "edge_type": "semantic_similar", "weight": 0.88,
    })
    resp = await test_app.get("/api/graph/node/hub-nb/neighborhood?depth=2")
    assert resp.status_code == 200
    data = resp.json()
    assert "hub-nb" in data["center"]
    assert "spoke-nb2" in data["node_ids"]


# ── Audit trail via API ───────────────────────────────────────────────────────


async def test_memory_events_endpoint_available(test_app: AsyncClient):
    """GET /api/memory-events returns a list (empty or non-empty)."""
    resp = await test_app.get("/api/memory-events")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_memory_history_endpoint(test_app: AsyncClient):
    """GET /api/memory/{id}/history returns event list for a memory."""
    # Log an event directly
    from app.memory.audit import get_memory_audit
    audit = get_memory_audit()
    await audit.log(event_type="created", memory_id="hist-test", actor="agent")

    resp = await test_app.get("/api/memory/hist-test/history")
    assert resp.status_code == 200
    events = resp.json()
    assert any(e["event_type"] == "created" for e in events)


async def test_memory_events_filter_by_event_type(test_app: AsyncClient):
    """GET /api/memory-events?event_type=pinned returns only pinned events."""
    from app.memory.audit import get_memory_audit
    audit = get_memory_audit()
    await audit.log(event_type="pinned", memory_id="pin-ev-1", actor="agent")
    await audit.log(event_type="unpinned", memory_id="pin-ev-2", actor="agent")

    resp = await test_app.get("/api/memory-events?event_type=pinned")
    assert resp.status_code == 200
    events = resp.json()
    assert all(e["event_type"] == "pinned" for e in events)


# ── GraphStore direct tests ───────────────────────────────────────────────────


async def test_graph_store_add_and_retrieve(test_app: AsyncClient):
    """GraphStore.add_edge() persists and get_neighbors() retrieves edges."""
    from app.knowledge.graph import get_graph_store

    gs = get_graph_store()
    edge = await gs.add_edge(
        source_id="gs-test-src",
        source_type="memory",
        target_id="gs-test-tgt",
        target_type="entity",
        edge_type="extracted_from",
        weight=1.0,
    )
    assert edge.id is not None

    neighbours = await gs.get_neighbors("gs-test-src")
    target_ids = {e.target_id for e in neighbours}
    assert "gs-test-tgt" in target_ids


async def test_graph_orphans_endpoint(test_app: AsyncClient):
    """GET /api/graph/orphans returns a structured response."""
    resp = await test_app.get("/api/graph/orphans")
    assert resp.status_code == 200
    data = resp.json()
    assert "orphan_ids" in data
    assert "count" in data
