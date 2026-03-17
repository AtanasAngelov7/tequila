"""Sprint 04 — Integration tests for Agent REST API (§4.1)."""
from __future__ import annotations

import os

import pytest


# ── Create ────────────────────────────────────────────────────────────────────


async def test_create_agent_minimal(test_app):
    resp = await test_app.post("/api/agents", json={"name": "Test Agent"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Agent"
    assert data["status"] == "active"
    assert "agent_id" in data
    assert data["agent_id"].startswith("agent:")
    assert data["version"] == 1


async def test_create_agent_with_model(test_app):
    resp = await test_app.post(
        "/api/agents",
        json={
            "name": "Advanced Bot",
            "default_model": "anthropic:claude-opus-4-5",
            "persona": "a powerful assistant",
            "role": "support",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["default_model"] == "anthropic:claude-opus-4-5"
    assert data["role"] == "support"


async def test_create_agent_with_soul(test_app):
    resp = await test_app.post(
        "/api/agents",
        json={
            "name": "Soul Bot",
            "soul": {
                "persona": "a creative writer",
                "instructions": ["always rhyme"],
                "tone": "casual",
            },
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["soul"]["persona"] == "a creative writer"
    assert data["soul"]["tone"] == "casual"


# ── List ─────────────────────────────────────────────────────────────────────


async def test_list_agents_empty(test_app):
    resp = await test_app.get("/api/agents")
    assert resp.status_code == 200
    body = resp.json()
    assert "agents" in body
    assert isinstance(body["agents"], list)


async def test_list_agents_populated(test_app):
    await test_app.post("/api/agents", json={"name": "Agent Alpha"})
    await test_app.post("/api/agents", json={"name": "Agent Beta"})
    resp = await test_app.get("/api/agents")
    assert resp.status_code == 200
    names = [a["name"] for a in resp.json()["agents"]]
    assert "Agent Alpha" in names
    assert "Agent Beta" in names


async def test_list_agents_filter_by_role(test_app):
    await test_app.post("/api/agents", json={"name": "Main Bot", "role": "main"})
    await test_app.post("/api/agents", json={"name": "Cron Bot", "role": "cron"})
    resp = await test_app.get("/api/agents?role=cron")
    assert resp.status_code == 200
    agents = resp.json()["agents"]
    assert all(a["role"] == "cron" for a in agents)
    assert any(a["name"] == "Cron Bot" for a in agents)


# ── Get ──────────────────────────────────────────────────────────────────────


async def test_get_agent(test_app):
    create_resp = await test_app.post("/api/agents", json={"name": "Fetch Me"})
    agent_id = create_resp.json()["agent_id"]
    resp = await test_app.get(f"/api/agents/{agent_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Fetch Me"


async def test_get_agent_not_found(test_app):
    resp = await test_app.get("/api/agents/agent:nonexistent")
    assert resp.status_code == 404


# ── Update ───────────────────────────────────────────────────────────────────


async def test_update_agent_name(test_app):
    create_resp = await test_app.post("/api/agents", json={"name": "Old Name"})
    data = create_resp.json()
    agent_id = data["agent_id"]
    version = data["version"]

    resp = await test_app.patch(
        f"/api/agents/{agent_id}",
        json={"version": version, "name": "New Name"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"
    assert resp.json()["version"] == version + 1


async def test_update_agent_occ_conflict(test_app):
    create_resp = await test_app.post("/api/agents", json={"name": "OCC Test"})
    data = create_resp.json()
    agent_id = data["agent_id"]
    version = data["version"]

    # First update succeeds
    await test_app.patch(
        f"/api/agents/{agent_id}",
        json={"version": version, "name": "Updated"},
    )

    # Second update with stale version fails
    resp = await test_app.patch(
        f"/api/agents/{agent_id}",
        json={"version": version, "name": "Should fail"},
    )
    assert resp.status_code == 409


# ── Delete ───────────────────────────────────────────────────────────────────


async def test_delete_agent(test_app):
    create_resp = await test_app.post("/api/agents", json={"name": "Delete Me"})
    agent_id = create_resp.json()["agent_id"]

    del_resp = await test_app.delete(f"/api/agents/{agent_id}")
    assert del_resp.status_code == 204

    get_resp = await test_app.get(f"/api/agents/{agent_id}")
    assert get_resp.status_code == 404


async def test_delete_agent_not_found(test_app):
    resp = await test_app.delete("/api/agents/agent:ghost")
    assert resp.status_code == 404


# ── Clone ─────────────────────────────────────────────────────────────────────


async def test_clone_agent(test_app):
    create_resp = await test_app.post(
        "/api/agents",
        json={"name": "Original", "default_model": "openai:gpt-4o"},
    )
    agent_id = create_resp.json()["agent_id"]

    clone_resp = await test_app.post(
        f"/api/agents/{agent_id}/clone",
        json={"name": "Clone"},
    )
    assert clone_resp.status_code == 201
    cloned = clone_resp.json()
    assert cloned["name"] == "Clone"
    assert cloned["agent_id"] != agent_id
    assert cloned["default_model"] == "openai:gpt-4o"


# ── Soul ─────────────────────────────────────────────────────────────────────


async def test_get_soul(test_app):
    create_resp = await test_app.post(
        "/api/agents",
        json={"name": "Soul Test", "soul": {"persona": "a poet", "instructions": ["rhyme"]}},
    )
    agent_id = create_resp.json()["agent_id"]

    soul_resp = await test_app.get(f"/api/agents/{agent_id}/soul")
    assert soul_resp.status_code == 200
    soul = soul_resp.json()
    assert soul["persona"] == "a poet"


async def test_update_soul(test_app):
    create_resp = await test_app.post("/api/agents", json={"name": "Soul Updater"})
    data = create_resp.json()
    agent_id = data["agent_id"]
    version = data["version"]

    soul_put = await test_app.put(
        f"/api/agents/{agent_id}/soul",
        json={
            "version": version,
            "soul": {"persona": "a scientist", "instructions": ["explain clearly"]},
        },
    )
    assert soul_put.status_code == 200
    assert soul_put.json()["persona"] == "a scientist"


# ── Export / Import ───────────────────────────────────────────────────────────


async def test_export_agent(test_app):
    create_resp = await test_app.post("/api/agents", json={"name": "Exportable"})
    agent_id = create_resp.json()["agent_id"]

    export_resp = await test_app.get(f"/api/agents/{agent_id}/export")
    assert export_resp.status_code == 200
    exported = export_resp.json()
    assert "agent" in exported
    assert exported["schema_version"] == "04"
    # Exported agent should not have server-managed fields
    assert "agent_id" not in exported["agent"]


async def test_import_agent(test_app):
    payload = {
        "agent": {
            "name": "Imported Bot",
            "default_model": "anthropic:claude-haiku-4-5",
            "persona": "a helpful helper",
        }
    }
    resp = await test_app.post("/api/agents/import", json=payload)
    assert resp.status_code == 201
    assert resp.json()["name"] == "Imported Bot"


# ── Providers ─────────────────────────────────────────────────────────────────


async def test_list_providers(test_app):
    resp = await test_app.get("/api/providers")
    assert resp.status_code == 200
    body = resp.json()
    assert "providers" in body
    providers = body["providers"]
    provider_ids = [p["provider_id"] for p in providers]
    assert "anthropic" in provider_ids
    # openai requires OPENAI_API_KEY to initialise; skip check when not set
    if os.environ.get("OPENAI_API_KEY"):
        assert "openai" in provider_ids
    assert "ollama" in provider_ids


async def test_get_provider_anthropic(test_app):
    resp = await test_app.get("/api/providers/anthropic")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider_id"] == "anthropic"
    assert "models" in body
    assert len(body["models"]) > 0


async def test_get_provider_not_found(test_app):
    resp = await test_app.get("/api/providers/nonexistent")
    assert resp.status_code == 404
