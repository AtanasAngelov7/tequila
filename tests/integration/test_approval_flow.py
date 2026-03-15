"""Integration tests for the approval flow — approval gate in ToolExecutor."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.agent.models import SessionPolicy
from app.tools.executor import ApprovalDenied, ToolExecutor
from tests.reset_helpers import reset_tool_executor
from app.tools.registry import ToolDefinition, ToolRegistry


# ── Helpers ───────────────────────────────────────────────────────────────────


SESSION_KEY = "user:approval_test"


def _make_executor(registry: ToolRegistry, router: Any = None) -> ToolExecutor:
    return ToolExecutor(registry=registry, router=router)


def _policy(**kwargs: Any) -> SessionPolicy:
    return SessionPolicy(**kwargs)


def _add_tool(
    registry: ToolRegistry,
    name: str,
    safety: str = "read_only",
    fn: Any = None,
) -> None:
    if fn is None:
        result = f"{name}_done"
        fn = lambda **kw: result  # noqa: E731
    registry.register(
        ToolDefinition(name=name, description="", parameters={}, safety=safety),  # type: ignore[arg-type]
        fn,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_destructive_tool_emits_approval_request_event() -> None:
    """Executing a destructive tool emits an approval_request stream event."""
    from app.gateway.events import ET
    from app.gateway.router import GatewayRouter as GR

    gw = GR()
    gw.start()

    received: list[Any] = []

    async def capture(event: Any) -> None:
        received.append(event)

    gw.on(ET.AGENT_RUN_STREAM, capture)

    registry = ToolRegistry()
    _add_tool(registry, "destructive_op", "destructive", lambda **kw: "deleted")
    ex = _make_executor(registry, router=gw)

    call_id = "call-emit-test"

    async def approve_after_short_delay() -> None:
        await asyncio.sleep(0.02)
        ex.resolve_approval(SESSION_KEY, call_id, approved=True)

    asyncio.create_task(approve_after_short_delay())

    result = await ex.execute(
        tool_call_id=call_id,
        tool_name="destructive_op",
        arguments={},
        policy=_policy(),
        session_key=SESSION_KEY,
    )

    assert result.success is True
    # The approval_request stream event should have been emitted
    approval_events = [
        e for e in received
        if isinstance(e.payload, dict) and e.payload.get("kind") == "approval_request"
    ]
    assert len(approval_events) >= 1
    assert approval_events[0].payload["tool_name"] == "destructive_op"


@pytest.mark.asyncio
async def test_approval_granted_allows_destructive_tool() -> None:
    """Approve a destructive tool → it executes successfully."""
    registry = ToolRegistry()
    _add_tool(registry, "danger", "destructive", lambda **kw: "danger_result")
    ex = _make_executor(registry)
    call_id = "call-grant"

    async def approve() -> None:
        await asyncio.sleep(0.01)
        ex.resolve_approval(SESSION_KEY, call_id, approved=True)

    asyncio.create_task(approve())

    result = await ex.execute(
        tool_call_id=call_id,
        tool_name="danger",
        arguments={},
        policy=_policy(),
        session_key=SESSION_KEY,
    )
    assert result.success is True
    assert result.result == "danger_result"


@pytest.mark.asyncio
async def test_approval_denied_returns_failed_result() -> None:
    """Deny a destructive tool → result is failure with 'denied' message."""
    registry = ToolRegistry()
    _add_tool(registry, "banned_op", "destructive")
    ex = _make_executor(registry)
    call_id = "call-deny"

    async def deny() -> None:
        await asyncio.sleep(0.01)
        ex.resolve_approval(SESSION_KEY, call_id, approved=False)

    asyncio.create_task(deny())

    result = await ex.execute(
        tool_call_id=call_id,
        tool_name="banned_op",
        arguments={},
        policy=_policy(),
        session_key=SESSION_KEY,
    )
    assert result.success is False
    assert "denied" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_allow_all_skips_approval_for_second_tool() -> None:
    """After allow_all, subsequent destructive tools execute without approval."""
    registry = ToolRegistry()
    _add_tool(registry, "first_op", "destructive", lambda **kw: "first")
    _add_tool(registry, "second_op", "critical", lambda **kw: "second")
    ex = _make_executor(registry)

    call_id_1 = "call-first"
    call_id_2 = "call-second"

    # Approve first tool with allow_all=True (simulates user clicking "Allow All")
    async def approve_with_allow_all() -> None:
        await asyncio.sleep(0.01)
        ex.set_allow_all(SESSION_KEY, True)
        ex.resolve_approval(SESSION_KEY, call_id_1, approved=True)

    asyncio.create_task(approve_with_allow_all())

    # First tool call (requires approval, user approves + sets allow_all)
    r1 = await ex.execute(
        tool_call_id=call_id_1,
        tool_name="first_op",
        arguments={},
        policy=_policy(),
        session_key=SESSION_KEY,
    )
    assert r1.success is True

    # Second tool call — should be auto-approved via allow_all (no pending needed)
    r2 = await asyncio.wait_for(
        ex.execute(
            tool_call_id=call_id_2,
            tool_name="second_op",
            arguments={},
            policy=_policy(),
            session_key=SESSION_KEY,
        ),
        timeout=1.0,
    )
    assert r2.success is True
    assert r2.result == "second"


@pytest.mark.asyncio
async def test_clear_turn_state_resets_allow_all() -> None:
    """clear_turn_state() removes allow_all so next turn requires approval again."""
    registry = ToolRegistry()
    _add_tool(registry, "the_op", "destructive")
    ex = _make_executor(registry)

    # Set allow_all, clear it, then try destructive tool without resolving
    ex.set_allow_all(SESSION_KEY, True)
    ex.clear_turn_state(SESSION_KEY)

    call_id = "call-after-clear"

    # Deny immediately so test doesn't hang
    async def deny_quickly() -> None:
        await asyncio.sleep(0.02)
        ex.resolve_approval(SESSION_KEY, call_id, approved=False)

    asyncio.create_task(deny_quickly())

    result = await ex.execute(
        tool_call_id=call_id,
        tool_name="the_op",
        arguments={},
        policy=_policy(),
        session_key=SESSION_KEY,
    )
    # After clearing, approval required → denied → failure
    assert result.success is False


@pytest.mark.asyncio
async def test_auto_approve_list_bypasses_approval() -> None:
    """A tool in auto_approve list executes without waiting for approval."""
    registry = ToolRegistry()
    _add_tool(registry, "safe_critical", "critical", lambda **kw: "ok")
    ex = _make_executor(registry)

    result = await asyncio.wait_for(
        ex.execute(
            tool_call_id="call-auto",
            tool_name="safe_critical",
            arguments={},
            policy=_policy(auto_approve=["safe_critical"]),
            session_key=SESSION_KEY,
        ),
        timeout=1.0,
    )
    assert result.success is True
    assert result.result == "ok"


@pytest.mark.asyncio
async def test_approval_timeout_auto_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    """When approval times out, the tool is auto-denied."""
    monkeypatch.setattr("app.tools.executor.APPROVAL_TIMEOUT_SECONDS", 0.05)

    registry = ToolRegistry()
    _add_tool(registry, "slow_approve", "destructive")
    ex = _make_executor(registry)

    result = await ex.execute(
        tool_call_id="call-timeout",
        tool_name="slow_approve",
        arguments={},
        policy=_policy(),
        session_key="user:timeout_session",
    )
    assert result.success is False
