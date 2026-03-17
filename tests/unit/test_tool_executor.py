"""Unit tests for app/tools/executor.py — policy enforcement, approval gate."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.agent.models import SessionPolicy
from app.tools.executor import (
    APPROVAL_TIMEOUT_SECONDS,
    ApprovalDenied,
    ToolExecutor,
    ToolNotFound,
)
from app.tools.registry import ToolDefinition, ToolRegistry


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    return registry


def _add_tool(
    registry: ToolRegistry,
    name: str,
    safety: str = "read_only",
    fn: Any = None,
) -> None:
    if fn is None:
        fn = lambda **kwargs: f"{name}_result"  # noqa: E731
    registry.register(
        ToolDefinition(name=name, description="", parameters={}, safety=safety),  # type: ignore[arg-type]
        fn,
    )


def _executor(registry: ToolRegistry, router: Any = None) -> ToolExecutor:
    return ToolExecutor(registry=registry, router=router)


def _policy(
    allowed_tools: list[str] | None = None,
    require_confirmation: list[str] | None = None,
    auto_approve: list[str] | None = None,
) -> SessionPolicy:
    return SessionPolicy(
        allowed_tools=allowed_tools or ["*"],
        require_confirmation=require_confirmation or [],
        auto_approve=auto_approve or [],
    )


SESSION_KEY = "user:test"
CALL_ID = "call-abc"


# ── _is_allowed ───────────────────────────────────────────────────────────────


def test_is_allowed_wildcard() -> None:
    ex = _executor(_make_registry())
    assert ex._is_allowed("any_tool", ["*"]) is True


def test_is_allowed_explicit() -> None:
    ex = _executor(_make_registry())
    assert ex._is_allowed("my_tool", ["my_tool", "other_tool"]) is True
    assert ex._is_allowed("blocked", ["my_tool"]) is False


# ── _needs_approval ───────────────────────────────────────────────────────────


def test_needs_approval_read_only_is_false() -> None:
    registry = _make_registry()
    _add_tool(registry, "read_it", "read_only")
    ex = _executor(registry)
    td, _ = registry.get("read_it")  # type: ignore[misc]
    assert ex._needs_approval(td, _policy(), SESSION_KEY) is False


def test_needs_approval_destructive_is_true() -> None:
    registry = _make_registry()
    _add_tool(registry, "del_file", "destructive")
    ex = _executor(registry)
    td, _ = registry.get("del_file")  # type: ignore[misc]
    assert ex._needs_approval(td, _policy(), SESSION_KEY) is True


def test_needs_approval_auto_approve_overrides() -> None:
    registry = _make_registry()
    _add_tool(registry, "del_file", "destructive")
    ex = _executor(registry)
    td, _ = registry.get("del_file")  # type: ignore[misc]
    assert ex._needs_approval(td, _policy(auto_approve=["del_file"]), SESSION_KEY) is False


def test_needs_approval_require_confirmation_low_safety() -> None:
    """A read_only tool listed in require_confirmation still needs approval."""
    registry = _make_registry()
    _add_tool(registry, "safe_but_confirm", "read_only")
    ex = _executor(registry)
    td, _ = registry.get("safe_but_confirm")  # type: ignore[misc]
    assert ex._needs_approval(td, _policy(require_confirmation=["safe_but_confirm"]), SESSION_KEY) is True


def test_needs_approval_allow_all_overrides_destructive() -> None:
    """allow_all bypasses approval for destructive tools."""
    registry = _make_registry()
    _add_tool(registry, "rm", "destructive")
    ex = _executor(registry)
    td, _ = registry.get("rm")  # type: ignore[misc]
    ex.set_allow_all(SESSION_KEY)
    assert ex._needs_approval(td, _policy(), SESSION_KEY) is False


def test_needs_approval_critical_always_requires() -> None:
    """TD-154: critical tools ALWAYS require approval, even with allow_all."""
    registry = _make_registry()
    _add_tool(registry, "crit", "critical")
    ex = _executor(registry)
    td, _ = registry.get("crit")  # type: ignore[misc]
    ex.set_allow_all(SESSION_KEY)
    assert ex._needs_approval(td, _policy(), SESSION_KEY) is True


# ── execute: allowed ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_read_only_tool() -> None:
    registry = _make_registry()
    _add_tool(registry, "greet", "read_only", lambda **kw: "hello")
    ex = _executor(registry)
    result = await ex.execute(
        tool_call_id=CALL_ID,
        tool_name="greet",
        arguments={},
        policy=_policy(),
        session_key=SESSION_KEY,
    )
    assert result.success is True
    assert result.result == "hello"


@pytest.mark.asyncio
async def test_execute_async_tool() -> None:
    registry = _make_registry()

    async def async_greet(**kw: Any) -> str:  # noqa: ANN401
        return "async_hello"

    registry.register(ToolDefinition(name="a", description="", parameters={}, safety="read_only"), async_greet)
    ex = _executor(registry)
    result = await ex.execute(
        tool_call_id=CALL_ID,
        tool_name="a",
        arguments={},
        policy=_policy(),
        session_key=SESSION_KEY,
    )
    assert result.success is True
    assert result.result == "async_hello"


# ── execute: blocked ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_tool_not_in_allowed_list() -> None:
    registry = _make_registry()
    _add_tool(registry, "some_tool", "read_only")
    ex = _executor(registry)
    result = await ex.execute(
        tool_call_id=CALL_ID,
        tool_name="some_tool",
        arguments={},
        policy=_policy(allowed_tools=["other_tool"]),
        session_key=SESSION_KEY,
    )
    assert result.success is False
    assert "not permitted" in (result.error or "")


@pytest.mark.asyncio
async def test_execute_unknown_tool_returns_error() -> None:
    ex = _executor(_make_registry())
    result = await ex.execute(
        tool_call_id=CALL_ID,
        tool_name="ghost",
        arguments={},
        policy=_policy(),
        session_key=SESSION_KEY,
    )
    assert result.success is False
    assert "not registered" in (result.error or "")


# ── execute: tool error ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_tool_that_raises() -> None:
    registry = _make_registry()

    def boom(**kw: Any) -> str:  # noqa: ANN401
        raise ValueError("Something broke")

    registry.register(ToolDefinition(name="boom", description="", parameters={}, safety="read_only"), boom)
    ex = _executor(registry)
    result = await ex.execute(
        tool_call_id=CALL_ID,
        tool_name="boom",
        arguments={},
        policy=_policy(),
        session_key=SESSION_KEY,
    )
    assert result.success is False
    assert "Something broke" in (result.error or "")


# ── execute: approval flow ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_destructive_approved() -> None:
    registry = _make_registry()
    _add_tool(registry, "rm", "destructive", lambda **kw: "deleted")
    ex = _executor(registry)

    async def approve_after_tiny_delay() -> None:
        await asyncio.sleep(0.01)
        ex.resolve_approval(SESSION_KEY, CALL_ID, approved=True)

    asyncio.create_task(approve_after_tiny_delay())
    result = await ex.execute(
        tool_call_id=CALL_ID,
        tool_name="rm",
        arguments={},
        policy=_policy(),
        session_key=SESSION_KEY,
    )
    assert result.success is True
    assert result.result == "deleted"


@pytest.mark.asyncio
async def test_execute_destructive_denied() -> None:
    registry = _make_registry()
    _add_tool(registry, "nuke", "destructive", lambda **kw: "nuked")
    ex = _executor(registry)

    async def deny_quickly() -> None:
        await asyncio.sleep(0.01)
        ex.resolve_approval(SESSION_KEY, CALL_ID, approved=False)

    asyncio.create_task(deny_quickly())
    result = await ex.execute(
        tool_call_id=CALL_ID,
        tool_name="nuke",
        arguments={},
        policy=_policy(),
        session_key=SESSION_KEY,
    )
    assert result.success is False
    assert "denied" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_execute_destructive_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeout causes auto-deny."""
    monkeypatch.setattr("app.tools.executor.APPROVAL_TIMEOUT_SECONDS", 0.05)
    registry = _make_registry()
    _add_tool(registry, "timeout_tool", "destructive")
    ex = _executor(registry)
    result = await ex.execute(
        tool_call_id=CALL_ID,
        tool_name="timeout_tool",
        arguments={},
        policy=_policy(),
        session_key=SESSION_KEY,
    )
    assert result.success is False


# ── set_allow_all and clear_turn_state ────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_allow_all_bypasses_approval_destructive() -> None:
    """allow_all bypasses approval for destructive (but not critical) tools."""
    registry = _make_registry()
    _add_tool(registry, "rm_tool", "destructive", lambda **kw: "deleted")
    ex = _executor(registry)
    ex.set_allow_all(SESSION_KEY)
    result = await ex.execute(
        tool_call_id=CALL_ID,
        tool_name="rm_tool",
        arguments={},
        policy=_policy(),
        session_key=SESSION_KEY,
    )
    assert result.success is True
    assert result.result == "deleted"


def test_clear_turn_state_removes_allow_all() -> None:
    ex = _executor(_make_registry())
    ex.set_allow_all(SESSION_KEY)
    ex.clear_turn_state(SESSION_KEY)
    assert ex._allow_all.get(SESSION_KEY) is None


# ── execute_many ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_many_order_preserved() -> None:
    registry = _make_registry()
    for name in ["a", "b", "c"]:
        n = name  # capture

        def _fn(n: str = n, **kw: Any) -> str:  # noqa: ANN401
            return f"{n}_done"

        registry.register(ToolDefinition(name=n, description="", parameters={}, safety="read_only"), _fn)

    ex = _executor(registry)
    tool_calls = [
        {"tool_call_id": "1", "tool_name": "a", "arguments": {}},
        {"tool_call_id": "2", "tool_name": "b", "arguments": {}},
        {"tool_call_id": "3", "tool_name": "c", "arguments": {}},
    ]
    results = await ex.execute_many(tool_calls, policy=_policy(), session_key=SESSION_KEY)
    assert [r.tool_call_id for r in results] == ["1", "2", "3"]
    assert [r.result for r in results] == ["a_done", "b_done", "c_done"]
