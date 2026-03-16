"""Sprint 08 -- Integration tests for multi-agent session tools."""
from __future__ import annotations

import json
import unittest.mock as mock

import pytest


async def test_sessions_list_visible_via_api(test_app):
    from app.tools.builtin.sessions import sessions_list

    await test_app.post("/api/sessions", json={"title": "Alpha", "session_key": "user:alpha"})
    await test_app.post("/api/sessions", json={"title": "Beta", "session_key": "user:beta"})

    sessions = json.loads(await sessions_list(limit=50))
    assert isinstance(sessions, list)
    keys = [s["session_key"] for s in sessions]
    assert "user:alpha" in keys
    assert "user:beta" in keys


async def test_sessions_list_kind_filter(test_app):
    from app.tools.builtin.sessions import sessions_list

    await test_app.post("/api/sessions", json={"kind": "agent", "session_key": "agent:tool-test", "agent_id": "tool-agent"})
    await test_app.post("/api/sessions", json={"session_key": "user:t1"})

    sessions = json.loads(await sessions_list(kind="agent", limit=20))
    assert isinstance(sessions, list)
    for sess in sessions:
        assert sess["kind"] == "agent"


async def test_sessions_history_returns_messages(test_app):
    cr = await test_app.post("/api/sessions", json={"session_key": "user:hist-test"})
    assert cr.status_code == 201
    sk = cr.json()["session_key"]
    sid = cr.json()["session_id"]

    await test_app.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "Hello history"})

    from app.tools.builtin.sessions import sessions_history

    messages = json.loads(await sessions_history(session_key=sk, limit=10))
    assert isinstance(messages, list)
    contents = [m["content"] for m in messages]
    assert "Hello history" in contents


async def test_sessions_history_empty_session(test_app):
    cr = await test_app.post("/api/sessions", json={"session_key": "user:empty-hist"})
    sk = cr.json()["session_key"]

    from app.tools.builtin.sessions import sessions_history

    messages = json.loads(await sessions_history(session_key=sk, limit=10))
    assert messages == []


async def test_sessions_spawn_creates_visible_session(test_app):
    from app.tools.builtin.sessions import sessions_spawn

    class FakeRouter:
        def __init__(self):
            self.emitted = []
        def emit_nowait(self, event):
            self.emitted.append(event)

    fake_router = FakeRouter()
    with mock.patch("app.agent.sub_agent.get_router", return_value=fake_router):
        result = json.loads(await sessions_spawn(agent_id="spawned-bot"))

    assert result["status"] == "spawned"
    spawned_key = result["session_key"]
    assert spawned_key.startswith("agent:spawned-bot:sub:")

    list_resp = await test_app.get("/api/sessions?kind=agent&limit=100")
    all_keys = [s["session_key"] for s in list_resp.json().get("sessions", [])]
    assert spawned_key in all_keys


async def test_sessions_spawn_concurrency_limit_enforced(test_app):
    from app.tools.builtin.sessions import sessions_spawn
    from app.agent import sub_agent
    from app.constants import MAX_CONCURRENT_SUBAGENTS

    parent = "_global"
    sub_agent._active[parent] = {f"fake:sub:{i}" for i in range(MAX_CONCURRENT_SUBAGENTS)}

    class FakeRouter:
        def emit_nowait(self, event):
            pass

    try:
        with mock.patch("app.agent.sub_agent.get_router", return_value=FakeRouter()):
            result = json.loads(await sessions_spawn("overflow-bot"))
        assert result["status"] == "error"
        assert "Concurrency limit" in result.get("error", "")
    finally:
        sub_agent._active.pop(parent, None)
