"""Sprint 09 — Integration tests for Vault, Memory, and Entity API endpoints (§5.1-§5.4)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


# ── Vault CRUD ────────────────────────────────────────────────────────────────


async def test_create_note_returns_201(test_app: AsyncClient):
    """POST /api/vault/notes creates a note and returns 201."""
    resp = await test_app.post(
        "/api/vault/notes",
        json={"title": "Hello World", "content": "This is my first note.", "tags": ["intro"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Hello World"
    assert "note_id" in data
    assert data["tags"] == ["intro"]


async def test_get_note_returns_200(test_app: AsyncClient):
    """GET /api/vault/notes/{id} returns the created note."""
    create = await test_app.post(
        "/api/vault/notes",
        json={"title": "My Note", "content": "Note body text."},
    )
    note_id = create.json()["note_id"]

    resp = await test_app.get(f"/api/vault/notes/{note_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["note_id"] == note_id
    assert data["title"] == "My Note"
    assert data["content"] == "Note body text."


async def test_get_note_not_found_returns_404(test_app: AsyncClient):
    """GET /api/vault/notes/{id} returns 404 for a missing note."""
    resp = await test_app.get("/api/vault/notes/nonexistent-id")
    assert resp.status_code == 404


async def test_list_notes_returns_200(test_app: AsyncClient):
    """GET /api/vault/notes returns a list of notes."""
    await test_app.post("/api/vault/notes", json={"title": "Note A", "content": "a"})
    await test_app.post("/api/vault/notes", json={"title": "Note B", "content": "b"})
    resp = await test_app.get("/api/vault/notes")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 2


async def test_update_note_returns_200(test_app: AsyncClient):
    """PUT /api/vault/notes/{id} updates the note content."""
    create = await test_app.post("/api/vault/notes", json={"title": "Draft", "content": "v1"})
    note_id = create.json()["note_id"]

    resp = await test_app.put(
        f"/api/vault/notes/{note_id}",
        json={"content": "v2 updated content"},
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "v2 updated content"


async def test_delete_note_returns_204(test_app: AsyncClient):
    """DELETE /api/vault/notes/{id} returns 204 and removes the note."""
    create = await test_app.post("/api/vault/notes", json={"title": "Temp", "content": "delete me"})
    note_id = create.json()["note_id"]

    resp = await test_app.delete(f"/api/vault/notes/{note_id}")
    assert resp.status_code == 204

    get_resp = await test_app.get(f"/api/vault/notes/{note_id}")
    assert get_resp.status_code == 404


async def test_vault_graph_returns_nodes_and_edges(test_app: AsyncClient):
    """GET /api/vault/graph returns nodes and edges dict."""
    await test_app.post(
        "/api/vault/notes",
        json={"title": "Source", "content": "See also [[Target]]."},
    )
    await test_app.post("/api/vault/notes", json={"title": "Target", "content": "I am the target."})
    resp = await test_app.get("/api/vault/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "edges" in data
    assert isinstance(data["nodes"], list)
    assert isinstance(data["edges"], list)


async def test_vault_sync_returns_result(test_app: AsyncClient):
    """POST /api/vault/sync returns added/updated/deleted counts."""
    resp = await test_app.post("/api/vault/sync")
    assert resp.status_code == 200
    data = resp.json()
    assert "added" in data
    assert "updated" in data
    assert "deleted" in data


# ── Memory CRUD ───────────────────────────────────────────────────────────────


async def test_create_memory_returns_201(test_app: AsyncClient):
    """POST /api/memory creates a memory extract and returns 201."""
    resp = await test_app.post(
        "/api/memory",
        json={"content": "User prefers concise answers", "memory_type": "preference"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["content"] == "User prefers concise answers"
    assert data["memory_type"] == "preference"
    assert "memory_id" in data
    assert data["always_recall"] is True  # preference type default


async def test_get_memory_returns_200(test_app: AsyncClient):
    """GET /api/memory/{id} returns the created memory."""
    create = await test_app.post(
        "/api/memory",
        json={"content": "User is named Alice", "memory_type": "identity"},
    )
    memory_id = create.json()["memory_id"]

    resp = await test_app.get(f"/api/memory/{memory_id}")
    assert resp.status_code == 200
    assert resp.json()["memory_id"] == memory_id


async def test_list_memories_returns_200(test_app: AsyncClient):
    """GET /api/memory returns a list of memory extracts."""
    await test_app.post("/api/memory", json={"content": "fact 1", "memory_type": "fact"})
    resp = await test_app.get("/api/memory")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_patch_memory_returns_200(test_app: AsyncClient):
    """PATCH /api/memory/{id} updates content."""
    create = await test_app.post(
        "/api/memory",
        json={"content": "original content", "memory_type": "fact"},
    )
    memory_id = create.json()["memory_id"]

    resp = await test_app.patch(
        f"/api/memory/{memory_id}",
        json={"content": "updated content"},
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "updated content"


async def test_delete_memory_returns_204(test_app: AsyncClient):
    """DELETE /api/memory/{id} removes the memory."""
    create = await test_app.post("/api/memory", json={"content": "remove", "memory_type": "task"})
    memory_id = create.json()["memory_id"]

    resp = await test_app.delete(f"/api/memory/{memory_id}")
    assert resp.status_code == 204


# ── Entity CRUD ───────────────────────────────────────────────────────────────


async def test_create_entity_returns_201(test_app: AsyncClient):
    """POST /api/entities creates an entity and returns 201."""
    resp = await test_app.post(
        "/api/entities",
        json={"name": "Alice Johnson", "entity_type": "person", "summary": "A researcher."},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Alice Johnson"
    assert data["entity_type"] == "person"
    assert "entity_id" in data


async def test_get_entity_returns_200(test_app: AsyncClient):
    """GET /api/entities/{id} returns the created entity."""
    create = await test_app.post(
        "/api/entities", json={"name": "Bob Smith", "entity_type": "person"}
    )
    entity_id = create.json()["entity_id"]

    resp = await test_app.get(f"/api/entities/{entity_id}")
    assert resp.status_code == 200
    assert resp.json()["entity_id"] == entity_id


async def test_list_entities_returns_200(test_app: AsyncClient):
    """GET /api/entities returns a list of entities."""
    await test_app.post("/api/entities", json={"name": "Concept A", "entity_type": "concept"})
    resp = await test_app.get("/api/entities")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_entity_add_alias(test_app: AsyncClient):
    """POST /api/entities/{id}/aliases adds an alias."""
    create = await test_app.post(
        "/api/entities", json={"name": "International Business Machines", "entity_type": "organization"}
    )
    entity_id = create.json()["entity_id"]

    resp = await test_app.post(
        f"/api/entities/{entity_id}/aliases",
        json={"alias": "IBM"},
    )
    assert resp.status_code == 200
    assert "IBM" in resp.json()["aliases"]


async def test_delete_entity_returns_204(test_app: AsyncClient):
    """DELETE /api/entities/{id} removes the entity."""
    create = await test_app.post(
        "/api/entities", json={"name": "ToDelete", "entity_type": "concept"}
    )
    entity_id = create.json()["entity_id"]

    resp = await test_app.delete(f"/api/entities/{entity_id}")
    assert resp.status_code == 204


async def test_entity_ner_endpoint(test_app: AsyncClient):
    """POST /api/entities/ner returns a list of entity mentions."""
    resp = await test_app.post(
        "/api/entities/ner",
        json={"text": "Alice Smith works at OpenAI Inc on Project Atlas."},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "mentions" in data
    assert isinstance(data["mentions"], list)
