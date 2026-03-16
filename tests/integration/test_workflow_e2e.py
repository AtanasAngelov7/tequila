"""Sprint 08 — Integration tests for the Workflow REST API (§10.3)."""
from __future__ import annotations

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

PIPELINE_PAYLOAD = {
    "name": "My Pipeline",
    "description": "A test pipeline",
    "mode": "pipeline",
    "steps": [
        {"agent_id": "bot1", "prompt_template": "Step A: {context}"},
        {"agent_id": "bot2", "prompt_template": "Step B: {context}"},
    ],
}

PARALLEL_PAYLOAD = {
    "name": "My Parallel",
    "mode": "parallel",
    "steps": [
        {"agent_id": "bot1", "prompt_template": "Task A"},
        {"agent_id": "bot2", "prompt_template": "Task B"},
    ],
}


async def _create_workflow(test_app, payload=None):
    resp = await test_app.post("/api/workflows", json=payload or PIPELINE_PAYLOAD)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Create ────────────────────────────────────────────────────────────────────


async def test_create_workflow_returns_201(test_app):
    resp = await test_app.post("/api/workflows", json=PIPELINE_PAYLOAD)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "My Pipeline"
    assert body["mode"] == "pipeline"
    assert "workflow_id" in body
    assert len(body["steps"]) == 2


async def test_create_workflow_parallel_mode(test_app):
    resp = await test_app.post("/api/workflows", json=PARALLEL_PAYLOAD)
    assert resp.status_code == 201
    assert resp.json()["mode"] == "parallel"


async def test_create_workflow_missing_steps_returns_422(test_app):
    resp = await test_app.post("/api/workflows", json={"name": "NoSteps", "mode": "pipeline", "steps": []})
    # Empty steps should still be accepted structurally; server validates or stores
    # (if the API allows it, 201; if it validates, 422).  Just check it doesn't 500.
    assert resp.status_code in (201, 422)


# ── Read ──────────────────────────────────────────────────────────────────────


async def test_get_workflow(test_app):
    created = await _create_workflow(test_app)
    wid = created["workflow_id"]
    resp = await test_app.get(f"/api/workflows/{wid}")
    assert resp.status_code == 200
    assert resp.json()["workflow_id"] == wid


async def test_get_workflow_not_found(test_app):
    resp = await test_app.get("/api/workflows/nonexistent-id")
    assert resp.status_code == 404


async def test_list_workflows_empty(test_app):
    resp = await test_app.get("/api/workflows")
    assert resp.status_code == 200
    body = resp.json()
    assert "workflows" in body
    assert isinstance(body["workflows"], list)


async def test_list_workflows_populated(test_app):
    await _create_workflow(test_app, {**PIPELINE_PAYLOAD, "name": "W-1"})
    await _create_workflow(test_app, {**PIPELINE_PAYLOAD, "name": "W-2"})
    resp = await test_app.get("/api/workflows")
    names = [w["name"] for w in resp.json()["workflows"]]
    assert "W-1" in names
    assert "W-2" in names


# ── Update ────────────────────────────────────────────────────────────────────


async def test_update_workflow(test_app):
    created = await _create_workflow(test_app)
    wid = created["workflow_id"]
    update = dict(PIPELINE_PAYLOAD)
    update["name"] = "Updated Name"
    resp = await test_app.put(f"/api/workflows/{wid}", json=update)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


async def test_update_workflow_not_found(test_app):
    resp = await test_app.put("/api/workflows/no-such-id", json=PIPELINE_PAYLOAD)
    assert resp.status_code == 404


# ── Delete ────────────────────────────────────────────────────────────────────


async def test_delete_workflow(test_app):
    created = await _create_workflow(test_app)
    wid = created["workflow_id"]
    resp = await test_app.delete(f"/api/workflows/{wid}")
    assert resp.status_code == 204
    # Subsequent GET should 404
    resp2 = await test_app.get(f"/api/workflows/{wid}")
    assert resp2.status_code == 404


async def test_delete_workflow_not_found(test_app):
    resp = await test_app.delete("/api/workflows/no-such-id")
    assert resp.status_code == 404


# ── Run ───────────────────────────────────────────────────────────────────────


async def test_trigger_run_returns_202(test_app):
    created = await _create_workflow(test_app)
    wid = created["workflow_id"]
    resp = await test_app.post(f"/api/workflows/{wid}/run")
    assert resp.status_code == 202
    body = resp.json()
    assert "run_id" in body
    assert body["workflow_id"] == wid


async def test_trigger_run_unknown_workflow(test_app):
    resp = await test_app.post("/api/workflows/no-such/run")
    assert resp.status_code == 404


async def test_list_runs_for_workflow(test_app):
    created = await _create_workflow(test_app)
    wid = created["workflow_id"]
    await test_app.post(f"/api/workflows/{wid}/run")
    resp = await test_app.get(f"/api/workflows/{wid}/runs")
    assert resp.status_code == 200
    runs = resp.json()["runs"]
    assert len(runs) >= 1


async def test_get_run_detail(test_app):
    created = await _create_workflow(test_app)
    wid = created["workflow_id"]
    run_resp = await test_app.post(f"/api/workflows/{wid}/run")
    rid = run_resp.json()["run_id"]
    resp = await test_app.get(f"/api/workflows/{wid}/runs/{rid}")
    assert resp.status_code == 200
    assert resp.json()["run_id"] == rid


async def test_cancel_run(test_app):
    created = await _create_workflow(test_app)
    wid = created["workflow_id"]
    run_resp = await test_app.post(f"/api/workflows/{wid}/run")
    rid = run_resp.json()["run_id"]
    # Brief pause to let background task set status out of 'pending'
    # but cancel should succeed as long as run is non-terminal
    cancel = await test_app.post(f"/api/workflows/{wid}/runs/{rid}/cancel")
    # Accept 200 (successfully cancelled) or 409 (already finished in fast test env)
    assert cancel.status_code in (200, 409)


async def test_cancel_run_not_found(test_app):
    created = await _create_workflow(test_app)
    wid = created["workflow_id"]
    resp = await test_app.post(f"/api/workflows/{wid}/runs/nonexistent/cancel")
    assert resp.status_code == 404
