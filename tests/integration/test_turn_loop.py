"""Integration tests for TurnLoop — full turn cycle with MockProvider."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.agent.turn_loop import TurnLoop
from app.gateway.router import GatewayRouter
from app.providers.mock import MockProvider
from app.providers.registry import get_registry
from app.tools.executor import ToolExecutor, reset_tool_executor
from app.tools.registry import ToolDefinition, ToolRegistry


# ── Helpers ───────────────────────────────────────────────────────────────────


def _register_mock(provider: MockProvider) -> None:
    """Register *provider* in the singleton registry under its provider_id."""
    get_registry().register(provider)


def _make_gateway() -> GatewayRouter:
    r = GatewayRouter()
    r.start()
    return r


def _make_stores(migrated_db: Any) -> tuple[Any, Any, Any]:
    """Return (SessionStore, AgentStore, MessageStore) backed by migrated_db."""
    from app.sessions.store import SessionStore
    from app.agent.store import AgentStore
    from app.sessions.messages import MessageStore
    return SessionStore(migrated_db), AgentStore(migrated_db), MessageStore(migrated_db)


async def _make_session(
    session_store: Any,
    agent_store: Any,
    session_key: str = "user:tl_test",
) -> Any:
    """Create an agent using mock:mock-v1, then a session referencing it."""
    agent = await agent_store.create(name="test_agent", default_model="mock:mock-v1")
    return await session_store.create(session_key=session_key, agent_id=agent.agent_id)


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_turn_loop_simple_text_response(migrated_db: Any) -> None:
    """A simple text-only turn persists an assistant message in the DB."""
    mock = MockProvider(script=[[{"text": "Hello from mock!"}]], model_id="mock-v1")
    _register_mock(mock)

    session_store, agent_store, msg_store = _make_stores(migrated_db)
    session = await _make_session(session_store, agent_store)
    reset_tool_executor()

    registry = ToolRegistry()
    executor = ToolExecutor(registry=registry)
    gw = _make_gateway()

    loop = TurnLoop(
        router=gw,
        session_store=session_store,
        agent_store=agent_store,
        message_store=msg_store,
        tool_registry=registry,
        tool_executor=executor,
    )

    await loop.run_turn_from_api(
        session_id=session.session_id,
        session_key=session.session_key,
        user_content="Say hello",
        user_name="tester",
    )

    chain = await msg_store.get_active_chain(session.session_id)
    roles = [m.role for m in chain]
    assert "user" in roles
    assert "assistant" in roles

    assistant_msgs = [m for m in chain if m.role == "assistant"]
    assert any("Hello from mock!" in m.content for m in assistant_msgs)
    assert mock.calls_made == 1


@pytest.mark.asyncio
async def test_turn_loop_with_tool_call(migrated_db: Any) -> None:
    """Turn with one tool call: mock returns tool_call → executor → text."""
    # Script: turn 1 has a tool call, turn 2 has the final text
    mock = MockProvider(
        script=[
            [{"tool_call": {"name": "echo_tool", "arguments": {"msg": "hi"}}}],
            [{"text": "Tool result received."}],
        ],
        model_id="mock-v1",
    )
    _register_mock(mock)

    session_store, agent_store, msg_store = _make_stores(migrated_db)
    session = await _make_session(session_store, agent_store, "user:tl_tool_test")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="echo_tool", description="Echo", parameters={}, safety="read_only"),
        lambda msg="": f"ECHO:{msg}",
    )
    executor = ToolExecutor(registry=registry)
    reset_tool_executor()

    gw = _make_gateway()
    loop = TurnLoop(
        router=gw,
        session_store=session_store,
        agent_store=agent_store,
        message_store=msg_store,
        tool_registry=registry,
        tool_executor=executor,
    )

    await loop.run_turn_from_api(
        session_id=session.session_id,
        session_key=session.session_key,
        user_content="Use the echo tool",
    )

    chain = await msg_store.get_active_chain(session.session_id)
    roles = [m.role for m in chain]

    assert roles.count("user") >= 1
    assert roles.count("tool_result") >= 1
    assert "assistant" in roles
    assert mock.calls_made == 2


@pytest.mark.asyncio
async def test_turn_loop_emits_run_complete_event(migrated_db: Any) -> None:
    """Turn loop emits 'agent.run.complete' gateway event after finishing."""
    from app.gateway.events import ET

    mock = MockProvider(script=[[{"text": "Done."}]], model_id="mock-v1")
    _register_mock(mock)

    session_store, agent_store, msg_store = _make_stores(migrated_db)
    session = await _make_session(session_store, agent_store, "user:tl_event_test")
    reset_tool_executor()

    gw = _make_gateway()
    received_events: list[Any] = []

    async def capture(event: Any) -> None:
        received_events.append(event)

    gw.on(ET.AGENT_RUN_COMPLETE, capture)

    registry = ToolRegistry()
    loop = TurnLoop(
        router=gw,
        session_store=session_store,
        agent_store=agent_store,
        message_store=msg_store,
        tool_registry=registry,
        tool_executor=ToolExecutor(registry=registry, router=gw),
    )

    await loop.run_turn_from_api(
        session_id=session.session_id,
        session_key=session.session_key,
        user_content="Hello",
    )

    assert len(received_events) >= 1
    evt = received_events[0]
    assert evt.event_type == ET.AGENT_RUN_COMPLETE
    assert evt.payload.get("session_id") == session.session_id


@pytest.mark.asyncio
async def test_turn_loop_respects_max_tool_rounds(migrated_db: Any) -> None:
    """Turn loop stops after max_tool_rounds even if provider keeps calling tools."""
    # Provider always returns a tool call (never settles on text)
    script = [[{"tool_call": {"name": "inf_tool", "arguments": {}}}]] * 30
    mock = MockProvider(script=script, model_id="mock-v1")
    _register_mock(mock)

    session_store, agent_store, msg_store = _make_stores(migrated_db)
    # Create agent using mock provider; create session with max_tool_rounds=2
    agent = await agent_store.create(name="test_agent_rounds", default_model="mock:mock-v1")
    session = await session_store.create(
        session_key="user:tl_maxrounds",
        agent_id=agent.agent_id,
        policy={"max_tool_rounds": 2},
    )
    reset_tool_executor()

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="inf_tool", description="", parameters={}, safety="read_only"),
        lambda: "keep going",
    )
    gw = _make_gateway()
    loop = TurnLoop(
        router=gw,
        session_store=session_store,
        agent_store=agent_store,
        message_store=msg_store,
        tool_registry=registry,
        tool_executor=ToolExecutor(registry=registry, router=gw),
    )

    # Should complete within a few seconds
    await asyncio.wait_for(
        loop.run_turn_from_api(
            session_id=session.session_id,
            session_key=session.session_key,
            user_content="Loop infinitely",
        ),
        timeout=10,
    )

    # Capped at max_tool_rounds=2 (+ 1 initial call) = 3 provider calls at most
    assert mock.calls_made <= 4
