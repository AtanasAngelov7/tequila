"""Integration tests for Sprint 13 plugin features via the full FastAPI app.

Covers:
  - Scheduler API (CRUD + run-now)
  - Web policy API (GET + PUT + providers list)
  - Pipeline hooks engine basic wiring
  - Documents plugin install flow
"""
from __future__ import annotations

import pytest


# ── Scheduler API ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scheduler_list_empty(test_app):
    """GET /api/scheduled-tasks returns a list (empty on fresh DB)."""
    resp = await test_app.get("/api/scheduled-tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 0


@pytest.mark.asyncio
async def test_scheduler_create_task(test_app):
    """POST /api/scheduled-tasks creates a new task."""
    payload = {
        "name": "Integration Test Task",
        "cron_expression": "*/5 * * * *",
        "agent_id": "test-agent-1",
        "prompt_template": "Hello from integration test.",
        "enabled": True,
    }
    resp = await test_app.post("/api/scheduled-tasks", json=payload)
    assert resp.status_code in (200, 201), resp.text
    data = resp.json()
    assert data["name"] == "Integration Test Task"
    assert data["cron_expression"] == "*/5 * * * *"
    assert "id" in data
    return data["id"]


@pytest.mark.asyncio
async def test_scheduler_get_task(test_app):
    """GET /api/scheduled-tasks/{id} returns a specific task."""
    create_resp = await test_app.post("/api/scheduled-tasks", json={
        "name": "Get Test Task",
        "cron_expression": "0 8 * * *",
        "agent_id": "test-agent-1",
        "prompt_template": "Morning check",
    })
    assert create_resp.status_code in (200, 201)
    task_id = create_resp.json()["id"]

    resp = await test_app.get(f"/api/scheduled-tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == task_id


@pytest.mark.asyncio
async def test_scheduler_update_task(test_app):
    """PATCH /api/scheduled-tasks/{id} updates task properties."""
    create_resp = await test_app.post("/api/scheduled-tasks", json={
        "name": "Update Me",
        "cron_expression": "0 9 * * *",
        "agent_id": "test-agent-1",
        "prompt_template": "original",
    })
    task_id = create_resp.json()["id"]

    patch_resp = await test_app.patch(f"/api/scheduled-tasks/{task_id}", json={"enabled": False})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["enabled"] is False


@pytest.mark.asyncio
async def test_scheduler_delete_task(test_app):
    """DELETE /api/scheduled-tasks/{id} removes the task."""
    create_resp = await test_app.post("/api/scheduled-tasks", json={
        "name": "Delete Me",
        "cron_expression": "0 0 * * *",
        "agent_id": "test-agent-1",
        "prompt_template": "bye",
    })
    task_id = create_resp.json()["id"]

    del_resp = await test_app.delete(f"/api/scheduled-tasks/{task_id}")
    assert del_resp.status_code in (200, 204)

    get_resp = await test_app.get(f"/api/scheduled-tasks/{task_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_scheduler_create_invalid_cron(test_app):
    """POST with invalid cron expression must return 422."""
    resp = await test_app.post("/api/scheduled-tasks", json={
        "name": "Bad Task",
        "cron_expression": "not-a-cron",
        "prompt_template": "test",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_scheduler_run_now(test_app):
    """POST /api/scheduled-tasks/{id}/run should trigger the task immediately."""
    create_resp = await test_app.post("/api/scheduled-tasks", json={
        "name": "Run Now Task",
        "cron_expression": "0 0 1 1 *",  # Only runs Jan 1 00:00 — won't fire automatically
        "agent_id": "test-agent-1",
        "prompt_template": "Trigger me manually",
    })
    assert create_resp.status_code in (200, 201)
    task_id = create_resp.json()["id"]

    run_resp = await test_app.post(f"/api/scheduled-tasks/{task_id}/run")
    # Should return 200 or 202 (accepted) even if the underlying LLM call fails
    assert run_resp.status_code in (200, 202, 204), run_resp.text


# ── Web Policy API ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_web_policy_get(test_app):
    """GET /api/web-policy returns the current policy."""
    resp = await test_app.get("/api/web-policy")
    assert resp.status_code == 200
    data = resp.json()
    assert "default_provider" in data
    assert "max_results" in data


@pytest.mark.asyncio
async def test_web_policy_put(test_app):
    """PUT /api/web-policy updates the policy and returns updated values."""
    payload = {
        "default_provider": "duckduckgo",
        "max_results": 7,
        "safe_search": "off",
        "timeout_s": 20,
        "brave_api_key": "",
        "tavily_api_key": "",
        "google_api_key": "",
        "google_cx": "",
        "bing_api_key": "",
        "searxng_url": "http://localhost:8080",
        "url_blocklist": ["badsite.com"],
        "url_allowlist": [],
        "blocklist_mode": "blocklist",
        "requests_per_minute": 60,
    }
    resp = await test_app.put("/api/web-policy", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["max_results"] == 7
    assert data["safe_search"] == "off"


@pytest.mark.asyncio
async def test_web_policy_providers_list(test_app):
    """GET /api/web-policy/providers returns available search providers."""
    resp = await test_app.get("/api/web-policy/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert "providers" in data
    assert isinstance(data["providers"], list)
    names = [p["name"] for p in data["providers"]]
    assert "duckduckgo" in names


# ── Pipeline hooks wiring ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hook_engine_singleton_accessible():
    """The HookEngine singleton must be importable and operational."""
    from app.plugins.hooks.engine import get_hook_engine
    from app.plugins.hooks.models import HookContext

    engine = get_hook_engine()
    assert engine is not None

    # Running with no hooks registered should succeed without error
    ctx = HookContext(hook_point="pre_prompt_assembly", session_id="integration-test", data={"text": "hello"})
    result = await engine.run(ctx)
    assert result is not None


# ── Documents plugin ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_documents_plugin_install(test_app):
    """Documents plugin can be installed via the plugin API."""
    resp = await test_app.post("/api/plugins", json={"plugin_id": "documents"})
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["plugin_id"] == "documents"


@pytest.mark.asyncio
async def test_documents_plugin_get_after_install(test_app):
    await test_app.post("/api/plugins", json={"plugin_id": "documents"})
    resp = await test_app.get("/api/plugins/documents")
    assert resp.status_code == 200
    assert resp.json()["plugin_id"] == "documents"
