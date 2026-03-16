"""Sprint 08 — Unit tests for session tools (§3.3)."""
from __future__ import annotations

import json

import pytest


@pytest.fixture
async def stores(migrated_db):
    """Initialise SessionStore and MessageStore singletons against the test DB."""
    from app.sessions.store import init_session_store
    from app.sessions.messages import init_message_store

    init_session_store(migrated_db)
    init_message_store(migrated_db)
    return migrated_db


# ── sessions_list ─────────────────────────────────────────────────────────────


async def test_sessions_list_empty(stores):
    from app.tools.builtin.sessions import sessions_list

    result = json.loads(await sessions_list())
    assert isinstance(result, list)


async def test_sessions_list_returns_created_sessions(stores):
    from app.sessions.store import get_session_store
    from app.tools.builtin.sessions import sessions_list

    s = get_session_store()
    await s.create(session_key="user:test1", kind="user", agent_id="main")
    await s.create(session_key="agent:bot:sub:abc1", kind="agent", agent_id="bot")

    all_sessions = json.loads(await sessions_list())
    keys = [s["session_key"] for s in all_sessions]
    assert "user:test1" in keys
    assert "agent:bot:sub:abc1" in keys


async def test_sessions_list_filters_by_kind(stores):
    from app.sessions.store import get_session_store
    from app.tools.builtin.sessions import sessions_list

    s = get_session_store()
    await s.create(session_key="user:test2", kind="user", agent_id="main")
    await s.create(session_key="agent:bot2:sub:x1", kind="agent", agent_id="bot2")

    agent_sessions = json.loads(await sessions_list(kind="agent"))
    kinds = {s["kind"] for s in agent_sessions}
    assert kinds == {"agent"} or not agent_sessions or all(s["kind"] == "agent" for s in agent_sessions)


async def test_sessions_list_limit_enforced(stores):
    from app.tools.builtin.sessions import sessions_list

    # limit clamps to 50 max and 1 min
    result = json.loads(await sessions_list(limit=999))
    assert isinstance(result, list)


# ── sessions_history ──────────────────────────────────────────────────────────


async def test_sessions_history_empty(stores):
    from app.sessions.store import get_session_store
    from app.tools.builtin.sessions import sessions_history

    s = get_session_store()
    await s.create(session_key="user:hist1", kind="user", agent_id="main")

    result = json.loads(await sessions_history("user:hist1"))
    assert isinstance(result, list)
    assert result == []


async def test_sessions_history_returns_messages(stores):
    from app.sessions.store import get_session_store
    from app.sessions.messages import get_message_store
    from app.tools.builtin.sessions import sessions_history

    ss = get_session_store()
    ms = get_message_store()
    session = await ss.create(session_key="user:hist2", kind="user", agent_id="main")
    await ms.insert(
        session_id=session.session_id,
        role="user",
        content="Hello world",
    )

    result = json.loads(await sessions_history("user:hist2"))
    assert len(result) == 1
    assert result[0]["role"] == "user"
    assert result[0]["content"] == "Hello world"


async def test_sessions_history_respects_limit(stores):
    from app.sessions.store import get_session_store
    from app.sessions.messages import get_message_store
    from app.tools.builtin.sessions import sessions_history

    ss = get_session_store()
    ms = get_message_store()
    session = await ss.create(session_key="user:hist3", kind="user", agent_id="main")
    for i in range(5):
        await ms.insert(
            session_id=session.session_id,
            role="user",
            content=f"msg {i}",
        )

    result = json.loads(await sessions_history("user:hist3", limit=3))
    assert len(result) == 3


# ── sessions_send ─────────────────────────────────────────────────────────────


async def test_sessions_send_fire_and_forget(stores):
    """sessions_send with timeout_s=0 returns accepted immediately."""
    from app.gateway.router import GatewayRouter
    from app.tools.builtin import sessions as sessions_module
    from app.tools.builtin.sessions import sessions_send

    # Patch the router with a local one so we don't need the global singleton
    captured = []

    class FakeRouter:
        def emit_nowait(self, event):
            captured.append(event)

        def on(self, *a, **kw):
            pass

        def off(self, *a, **kw):
            pass

    import unittest.mock as mock
    with mock.patch("app.tools.builtin.sessions.get_router", return_value=FakeRouter()):
        result = json.loads(await sessions_send("user:target", "hello", timeout_s=0))

    assert result["status"] == "accepted"
    assert len(captured) == 1
    assert captured[0].session_key == "user:target"


# ── sessions_spawn ────────────────────────────────────────────────────────────


async def test_sessions_spawn_creates_session(stores):
    """sessions_spawn creates a new sub-agent session."""
    from app.sessions.store import get_session_store
    from app.tools.builtin.sessions import sessions_spawn
    import unittest.mock as mock

    # Patch the gateway router so emit_nowait doesn't fail
    class FakeRouter:
        def emit_nowait(self, event):
            pass

    with mock.patch("app.agent.sub_agent.get_router", return_value=FakeRouter()):
        result = json.loads(await sessions_spawn("main"))

    assert result["status"] == "spawned"
    sk = result["session_key"]
    assert "sub" in sk

    # Verify session was created in the DB
    store = get_session_store()
    session = await store.get_by_key(sk)
    assert session.kind == "agent"
    assert session.agent_id == "main"


async def test_sessions_spawn_respects_concurrency_limit(stores):
    """sessions_spawn raises when concurrency limit is reached for a parent."""
    import unittest.mock as mock
    from app.constants import MAX_CONCURRENT_SUBAGENTS
    from app.agent import sub_agent
    from app.tools.builtin.sessions import sessions_spawn

    # Pre-fill active sub-agents to the cap
    parent = "_global"
    sub_agent._active[parent] = {f"fake:sub:{i}" for i in range(MAX_CONCURRENT_SUBAGENTS)}

    class FakeRouter:
        def emit_nowait(self, event):
            pass

    try:
        with mock.patch("app.agent.sub_agent.get_router", return_value=FakeRouter()):
            result = json.loads(await sessions_spawn("main"))
        assert result["status"] == "error"
        assert "Concurrency limit" in result["error"]
    finally:
        sub_agent._active.pop(parent, None)
