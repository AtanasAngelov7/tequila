"""Sprint 08 — Unit tests for sub-agent management (§3.3, §20.7)."""
from __future__ import annotations

import pytest
import unittest.mock as mock


@pytest.fixture
async def stores(migrated_db):
    """Initialise SessionStore against the test DB."""
    from app.sessions.store import init_session_store
    from app.sessions.messages import init_message_store

    init_session_store(migrated_db)
    init_message_store(migrated_db)
    return migrated_db


@pytest.fixture(autouse=True)
def reset_active(stores):
    """Clear active-sub-agent tracking between tests."""
    from app.agent import sub_agent
    sub_agent._active.clear()
    yield
    sub_agent._active.clear()


# ── spawn_sub_agent ───────────────────────────────────────────────────────────


async def test_spawn_creates_session(stores):
    """Spawn creates a session with kind='agent' and matching agent_id."""
    from app.agent.sub_agent import spawn_sub_agent
    from app.sessions.store import get_session_store

    class FakeRouter:
        def emit_nowait(self, event):
            pass

    with mock.patch("app.agent.sub_agent.get_router", return_value=FakeRouter()):
        sub_key = await spawn_sub_agent(agent_id="bot", auto_archive_minutes=0)

    assert "sub" in sub_key
    assert "bot" in sub_key

    session = await get_session_store().get_by_key(sub_key)
    assert session.kind == "agent"
    assert session.agent_id == "bot"


async def test_spawn_applies_worker_policy_by_default(stores):
    """Spawned sub-agent uses WORKER preset (no spawning, no external delivery)."""
    from app.agent.sub_agent import spawn_sub_agent
    from app.sessions.store import get_session_store

    class FakeRouter:
        def emit_nowait(self, event):
            pass

    with mock.patch("app.agent.sub_agent.get_router", return_value=FakeRouter()):
        sub_key = await spawn_sub_agent(agent_id="bot", auto_archive_minutes=0)

    session = await get_session_store().get_by_key(sub_key)
    assert session.policy.can_spawn_agents is False
    assert session.policy.can_send_inter_session is False
    assert session.policy.allowed_channels == []


async def test_spawn_emits_initial_message(stores):
    """Spawn with initial_message emits an inbound.message event."""
    from app.agent.sub_agent import spawn_sub_agent

    emitted = []

    class FakeRouter:
        def emit_nowait(self, event):
            emitted.append(event)

    with mock.patch("app.agent.sub_agent.get_router", return_value=FakeRouter()):
        await spawn_sub_agent(
            agent_id="bot", initial_message="Do the thing", auto_archive_minutes=0
        )

    assert len(emitted) == 1
    assert emitted[0].payload["content"] == "Do the thing"
    assert emitted[0].payload["provenance"] == "inter_session"


async def test_spawn_no_message_no_event(stores):
    """Spawn without initial_message emits no gateway event."""
    from app.agent.sub_agent import spawn_sub_agent

    emitted = []

    class FakeRouter:
        def emit_nowait(self, event):
            emitted.append(event)

    with mock.patch("app.agent.sub_agent.get_router", return_value=FakeRouter()):
        await spawn_sub_agent(agent_id="bot", initial_message=None, auto_archive_minutes=0)

    assert emitted == []


# ── Concurrency limit ─────────────────────────────────────────────────────────


async def test_spawn_enforces_concurrency_limit(stores):
    """Spawn raises RuntimeError when per-parent cap is reached."""
    from app.agent import sub_agent
    from app.agent.sub_agent import spawn_sub_agent
    from app.constants import MAX_CONCURRENT_SUBAGENTS

    # Pre-fill to limit
    parent = "user:parent"
    sub_agent._active[parent] = {f"fake:sub:{i}" for i in range(MAX_CONCURRENT_SUBAGENTS)}

    class FakeRouter:
        def emit_nowait(self, event):
            pass

    with pytest.raises(RuntimeError, match="Concurrency limit"):
        with mock.patch("app.agent.sub_agent.get_router", return_value=FakeRouter()):
            await spawn_sub_agent(
                agent_id="bot",
                parent_session_key=parent,
                auto_archive_minutes=0,
            )


async def test_spawn_tracks_in_active_dict(stores):
    """After spawn, the sub-agent key appears in _active."""
    from app.agent import sub_agent
    from app.agent.sub_agent import spawn_sub_agent

    class FakeRouter:
        def emit_nowait(self, event):
            pass

    parent = "user:myparent"
    with mock.patch("app.agent.sub_agent.get_router", return_value=FakeRouter()):
        sub_key = await spawn_sub_agent(
            agent_id="bot",
            parent_session_key=parent,
            auto_archive_minutes=0,
        )

    assert sub_key in sub_agent._active.get(parent, set())


# ── active_sub_agent_count ────────────────────────────────────────────────────


def test_active_count_empty():
    from app.agent.sub_agent import active_sub_agent_count

    assert active_sub_agent_count("nonexistent") == 0


def test_active_count_tracks_correctly():
    from app.agent import sub_agent
    from app.agent.sub_agent import active_sub_agent_count

    sub_agent._active["parent:x"] = {"s1", "s2"}
    assert active_sub_agent_count("parent:x") == 2
    sub_agent._active.pop("parent:x")
