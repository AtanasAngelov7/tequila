"""Sprint 07 — Integration tests for the end-to-end approval flow.

Covers:
* Persistent session approvals (grant / revoke / clear)
* Priority ordering in _needs_approval
* PATCH /api/sessions/{id}/policy endpoint
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.sessions.policy import SessionPolicy, SessionPolicyPresets
from app.tools.executor import ToolExecutor, reset_tool_executor
from app.tools.registry import ToolDefinition, ToolRegistry


# ── Helpers ───────────────────────────────────────────────────────────────────


SESSION_KEY = "user:e2e_approval_test"


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
        fn = lambda **kw: f"{name}_result"  # noqa: E731
    registry.register(
        ToolDefinition(name=name, description="", parameters={}, safety=safety),  # type: ignore[arg-type]
        fn,
    )


# ── Persistent session approvals ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_session_approval_persists_across_turn_clear() -> None:
    """grant_session_approval → tool auto-runs after clear_turn_state."""
    registry = ToolRegistry()
    _add_tool(registry, "danger", "destructive", fn=lambda **kw: "done")
    ex = _make_executor(registry)

    ex.grant_session_approval(SESSION_KEY, "danger")
    ex.clear_turn_state(SESSION_KEY)  # simulate end of turn

    # Should run without an approval pause (no resolver needed)
    result = await asyncio.wait_for(
        ex.execute(
            tool_call_id="call-session-grant",
            tool_name="danger",
            arguments={},
            policy=_policy(),
            session_key=SESSION_KEY,
        ),
        timeout=1.0,
    )
    assert result.success is True
    assert result.result == "done"


@pytest.mark.asyncio
async def test_revoke_session_approval_clears_one_tool() -> None:
    """revoking a specific tool removes it but keeps others."""
    registry = ToolRegistry()
    _add_tool(registry, "op_a", "destructive", fn=lambda **kw: "a")
    _add_tool(registry, "op_b", "destructive", fn=lambda **kw: "b")
    ex = _make_executor(registry)

    ex.grant_session_approval(SESSION_KEY, "op_a")
    ex.grant_session_approval(SESSION_KEY, "op_b")
    ex.revoke_session_approval(SESSION_KEY, "op_a")

    approvals = ex.get_session_approvals(SESSION_KEY)
    assert "op_a" not in approvals
    assert "op_b" in approvals


@pytest.mark.asyncio
async def test_revoke_all_session_approvals() -> None:
    """revoke_session_approval(tool_name=None) clears all approvals."""
    registry = ToolRegistry()
    ex = _make_executor(registry)

    ex.grant_session_approval(SESSION_KEY, "tool_x")
    ex.grant_session_approval(SESSION_KEY, "tool_y")
    ex.revoke_session_approval(SESSION_KEY, None)

    assert len(ex.get_session_approvals(SESSION_KEY)) == 0


@pytest.mark.asyncio
async def test_clear_session_state_removes_both_turn_and_session() -> None:
    """clear_session_state removes turn state AND session approvals."""
    registry = ToolRegistry()
    ex = _make_executor(registry)

    ex.set_allow_all(SESSION_KEY, True)
    ex.grant_session_approval(SESSION_KEY, "some_tool")
    ex.clear_session_state(SESSION_KEY)

    assert len(ex.get_session_approvals(SESSION_KEY)) == 0
    # allow_all should also be gone — next destructive call needs approval
    assert not ex._allow_all.get(SESSION_KEY)


# ── Priority ordering ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_approval_beats_require_confirmation() -> None:
    """Session approval takes priority over require_confirmation policy."""
    registry = ToolRegistry()
    _add_tool(registry, "confirmed_tool", "read_only", fn=lambda **kw: "ran")
    ex = _make_executor(registry)

    ex.grant_session_approval(SESSION_KEY, "confirmed_tool")

    result = await asyncio.wait_for(
        ex.execute(
            tool_call_id="call-prio",
            tool_name="confirmed_tool",
            arguments={},
            policy=_policy(require_confirmation=["confirmed_tool"]),
            session_key=SESSION_KEY,
        ),
        timeout=1.0,
    )
    assert result.success is True


@pytest.mark.asyncio
async def test_auto_approve_policy_beats_safety_default() -> None:
    """auto_approve in policy beats the destructive safety-default."""
    registry = ToolRegistry()
    _add_tool(registry, "risky_but_approved", "destructive", fn=lambda **kw: "ok")
    ex = _make_executor(registry)

    result = await asyncio.wait_for(
        ex.execute(
            tool_call_id="call-auto",
            tool_name="risky_but_approved",
            arguments={},
            policy=_policy(auto_approve=["risky_but_approved"]),
            session_key=SESSION_KEY,
        ),
        timeout=1.0,
    )
    assert result.success is True
    assert result.result == "ok"


# ── PATCH /api/sessions/{id}/policy endpoint ─────────────────────────────────


async def test_patch_policy_endpoint(test_app) -> None:
    """PATCH /api/sessions/{id}/policy updates and round-trips the policy."""
    # Create a session
    resp = await test_app.post(
        "/api/sessions",
        json={"session_key": "user:policy-patch-test", "title": "Policy Patch Test"},
    )
    assert resp.status_code == 201
    session_id = resp.json()["session_id"]

    # Patch the policy
    patch_resp = await test_app.patch(
        f"/api/sessions/{session_id}/policy",
        json={"policy": {"allowed_tools": ["web_search"], "can_spawn_agents": False}},
    )
    assert patch_resp.status_code == 200
    body = patch_resp.json()
    assert body["session_id"] == session_id
    assert body["policy"]["allowed_tools"] == ["web_search"]
    assert body["policy"]["can_spawn_agents"] is False


async def test_patch_policy_with_preset(test_app) -> None:
    """PATCH with a named preset e.g. READ_ONLY applies the preset policy."""
    resp = await test_app.post(
        "/api/sessions",
        json={"session_key": "user:policy-preset-test", "title": "Preset Test"},
    )
    session_id = resp.json()["session_id"]

    patch_resp = await test_app.patch(
        f"/api/sessions/{session_id}/policy",
        json={"preset": "READ_ONLY", "policy": {}},
    )
    assert patch_resp.status_code == 200
    body = patch_resp.json()
    # READ_ONLY should report can_spawn_agents=False
    assert body["policy"]["can_spawn_agents"] is False


async def test_patch_policy_invalid_preset_returns_4xx(test_app) -> None:
    """Unknown preset name should return 4xx."""
    resp = await test_app.post("/api/sessions", json={"session_key": "user:inv-preset"})
    session_id = resp.json()["session_id"]

    patch_resp = await test_app.patch(
        f"/api/sessions/{session_id}/policy",
        json={"preset": "NONEXISTENT_PRESET", "policy": {}},
    )
    assert patch_resp.status_code in (400, 422)


async def test_patch_policy_unknown_session_returns_404(test_app) -> None:
    """Patching a non-existent session returns 404."""
    patch_resp = await test_app.patch(
        "/api/sessions/99999/policy",
        json={"policy": {}},
    )
    assert patch_resp.status_code == 404
