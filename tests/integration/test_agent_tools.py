"""Integration tests — built-in tools registered and invokable via TurnLoop."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.turn_loop import TurnLoop
from app.gateway.router import GatewayRouter
from app.providers.mock import MockProvider
from app.providers.registry import get_registry
from app.tools.executor import ToolExecutor
from tests.reset_helpers import reset_tool_executor
from app.tools.registry import ToolRegistry, get_tool_registry


# ── Helpers (mirror test_turn_loop.py) ────────────────────────────────────────


def _register_mock(provider: MockProvider) -> None:
    get_registry().register(provider)


def _make_gateway() -> GatewayRouter:
    r = GatewayRouter()
    r.start()
    return r


def _make_stores(migrated_db: Any) -> tuple[Any, Any, Any]:
    from app.sessions.store import SessionStore
    from app.agent.store import AgentStore
    from app.sessions.messages import MessageStore
    return SessionStore(migrated_db), AgentStore(migrated_db), MessageStore(migrated_db)


async def _make_session(session_store, agent_store, key="user:tools_test"):
    agent = await agent_store.create(name="tools_agent", default_model="mock:mock-v1")
    return await session_store.create(session_key=key, agent_id=agent.agent_id)


# ── Tool registration ──────────────────────────────────────────────────────────


def test_register_all_builtin_tools_idempotent() -> None:
    """Calling register_all_builtin_tools() twice should not raise."""
    from app.tools.builtin import register_all_builtin_tools
    register_all_builtin_tools()
    register_all_builtin_tools()  # second call is safe

    reg = get_tool_registry()
    expected = {
        "fs_list_dir", "fs_read_file", "fs_write_file", "fs_search",
        "code_exec",
        "web_search", "web_fetch",
        "vision_describe", "vision_extract_text", "vision_compare", "vision_analyze",
    }
    registered = reg.names()
    assert expected.issubset(registered), f"Missing tools: {expected - registered}"


def test_all_builtin_tools_have_correct_safety() -> None:
    from app.tools.builtin import register_all_builtin_tools
    register_all_builtin_tools()
    reg = get_tool_registry()

    read_only = {"fs_list_dir", "fs_read_file", "fs_search", "web_search", "web_fetch",
                 "vision_describe", "vision_extract_text", "vision_compare", "vision_analyze"}
    side_effect = {"fs_write_file"}
    destructive = {"code_exec"}

    for name in read_only:
        td = reg.get_definition(name)
        assert td is not None, f"{name} not found"
        assert td.safety == "read_only", f"{name}: expected read_only, got {td.safety}"

    for name in side_effect:
        td = reg.get_definition(name)
        assert td is not None
        assert td.safety == "side_effect"

    for name in destructive:
        td = reg.get_definition(name)
        assert td is not None
        assert td.safety == "destructive"


# ── Filesystem tools via TurnLoop ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fs_read_file_via_turn_loop(migrated_db: Any, tmp_path: Path) -> None:
    """TurnLoop can invoke fs_read_file and inject the result back to the LLM."""
    from app.tools.builtin import register_all_builtin_tools
    from app.tools.builtin.filesystem import set_path_policy, PathPolicy

    set_path_policy(PathPolicy(allowed_roots=[tmp_path]))
    register_all_builtin_tools()

    test_file = tmp_path / "hello.txt"
    test_file.write_text("File content here")

    # Script: LLM calls fs_read_file, then gives a text response
    script = [
        [
            {"tool_call": {"name": "fs_read_file", "arguments": {"path": str(test_file)}}},
            {"text": "I read the file."},
        ],
        [{"text": "Done reading."}],
    ]
    mock = MockProvider(script=script, model_id="mock-v1")
    _register_mock(mock)

    session_store, agent_store, msg_store = _make_stores(migrated_db)
    session = await _make_session(session_store, agent_store, "user:fs_test")
    reset_tool_executor()

    registry = get_tool_registry()
    executor = ToolExecutor(registry=registry)
    executor.set_allow_all(session.session_key)  # no approval prompts in test
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
        user_content="Read the file",
        user_name="tester",
    )

    # Verify messages were stored
    messages = await msg_store.get_active_chain(session.session_id)
    roles = [m.role for m in messages]
    assert "user" in roles
    assert "assistant" in roles


@pytest.mark.asyncio
async def test_code_exec_via_turn_loop(migrated_db: Any) -> None:
    """TurnLoop invokes code_exec (destructive) with allow_all policy."""
    from app.tools.builtin import register_all_builtin_tools
    register_all_builtin_tools()

    script = [
        [
            {"tool_call": {"name": "code_exec", "arguments": {
                "language": "python",
                "code": "print('hello from code_exec')",
            }}},
            {"text": "Code executed successfully."},
        ],
        [{"text": "Done."}],
    ]
    mock = MockProvider(script=script, model_id="mock-v1")
    _register_mock(mock)

    session_store, agent_store, msg_store = _make_stores(migrated_db)
    session = await _make_session(session_store, agent_store, "user:code_test")
    reset_tool_executor()

    registry = get_tool_registry()
    executor = ToolExecutor(registry=registry)
    executor.set_allow_all(session.session_key)
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
        user_content="Run some Python",
        user_name="tester",
    )

    messages = await msg_store.get_active_chain(session.session_id)
    roles = [m.role for m in messages]
    assert "assistant" in roles


@pytest.mark.asyncio
async def test_web_search_via_turn_loop(migrated_db: Any) -> None:
    """TurnLoop invokes web_search with a mocked DuckDuckGo provider."""
    from app.tools.builtin import register_all_builtin_tools
    from app.tools.builtin.web_search import SearchProvider, get_search_registry, SearchConfig, set_search_config, get_search_config

    register_all_builtin_tools()

    # Inject a dummy search provider
    class FakeSearch(SearchProvider):
        def search(self, query, max_results, safe_search):
            return [{"title": "Fake Result", "url": "https://fake.com", "snippet": "x", "source": "fake"}]

    get_search_registry().register("fake", FakeSearch())
    original_cfg = get_search_config()
    set_search_config(SearchConfig(default_provider="fake"))

    try:
        script = [
            [
                {"tool_call": {"name": "web_search", "arguments": {"query": "test search"}}},
                {"text": "Found results."},
            ],
            [{"text": "Search done."}],
        ]
        mock = MockProvider(script=script, model_id="mock-v1")
        _register_mock(mock)

        session_store, agent_store, msg_store = _make_stores(migrated_db)
        session = await _make_session(session_store, agent_store, "user:wsearch_test")
        reset_tool_executor()

        registry = get_tool_registry()
        executor = ToolExecutor(registry=registry)
        executor.set_allow_all(session.session_key)
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
            user_content="Search for something",
            user_name="tester",
        )

        messages = await msg_store.get_active_chain(session.session_id)
        assert any(m.role == "assistant" for m in messages)
    finally:
        set_search_config(original_cfg)
