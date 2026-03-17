"""Tests for app/sessions/policy.py — SessionPolicy and presets."""
from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.sessions.policy import SessionPolicy, SessionPolicyPresets


# ── allows_tool / allows_channel / allows_path ────────────────────────────────


def test_admin_allows_all_tools() -> None:
    policy = SessionPolicyPresets.ADMIN
    assert policy.allows_tool("anything") is True
    assert policy.allows_tool("code_exec") is True


def test_read_only_blocks_all_tools() -> None:
    policy = SessionPolicyPresets.READ_ONLY
    assert policy.allows_tool("fs_read_file") is False
    assert policy.allows_tool("web_search") is False


def test_code_runner_allows_only_its_tools() -> None:
    policy = SessionPolicyPresets.CODE_RUNNER
    assert policy.allows_tool("code_exec") is True
    # CODE_RUNNER allows fs_write_file but not web_search
    assert policy.allows_tool("web_search") is False


def test_standard_allows_channel_wildcard() -> None:
    policy = SessionPolicyPresets.STANDARD
    assert policy.allows_channel("slack") is True
    assert policy.allows_channel("teams") is True


def test_worker_blocks_all_channels() -> None:
    policy = SessionPolicyPresets.WORKER
    assert policy.allows_channel("slack") is False
    assert policy.allows_channel("anything") is False


def test_allows_path_wildcard() -> None:
    policy = SessionPolicyPresets.ADMIN
    assert policy.allows_path("/any/path/file.txt") is True


def test_allows_specific_path() -> None:
    policy = SessionPolicy(allowed_paths=["/safe/"])
    assert policy.allows_path("/safe/file.txt") is True
    assert policy.allows_path("/unsafe/file.txt") is False


# ── needs_confirmation ────────────────────────────────────────────────────────


def test_standard_requires_confirmation_for_code_exec() -> None:
    policy = SessionPolicyPresets.STANDARD
    assert policy.needs_confirmation("code_exec") is True


def test_standard_does_not_require_confirmation_for_web_search() -> None:
    policy = SessionPolicyPresets.STANDARD
    assert policy.needs_confirmation("web_search") is False


def test_admin_never_requires_confirmation() -> None:
    policy = SessionPolicyPresets.ADMIN
    assert policy.needs_confirmation("code_exec") is False
    assert policy.needs_confirmation("fs_delete") is False


# ── can_spawn / can_send_inter_session ────────────────────────────────────────


def test_worker_cannot_spawn() -> None:
    assert SessionPolicyPresets.WORKER.can_spawn_agents is False


def test_admin_can_spawn() -> None:
    assert SessionPolicyPresets.ADMIN.can_spawn_agents is True


def test_chat_only_cannot_spawn() -> None:
    assert SessionPolicyPresets.CHAT_ONLY.can_spawn_agents is False


# ── by_name ───────────────────────────────────────────────────────────────────


def test_by_name_returns_correct_preset() -> None:
    policy = SessionPolicyPresets.by_name("ADMIN")
    assert policy.allowed_tools == ["*"]
    assert policy.can_spawn_agents is True


def test_by_name_case_insensitive() -> None:
    assert SessionPolicyPresets.by_name("admin") is not None
    assert SessionPolicyPresets.by_name("Standard") is not None


def test_by_name_unknown_raises() -> None:
    """by_name with an invalid name should raise ValueError."""
    with pytest.raises(ValueError, match="Unknown preset"):
        SessionPolicyPresets.by_name("nonexistent")


# ── Custom policy validation ──────────────────────────────────────────────────


def test_max_tool_rounds_must_be_positive() -> None:
    with pytest.raises((PydanticValidationError, ValueError)):
        SessionPolicy(max_tool_rounds=0)


def test_policy_json_round_trip() -> None:
    policy = SessionPolicyPresets.STANDARD
    dumped = policy.model_dump()
    reloaded = SessionPolicy(**dumped)
    assert reloaded.allowed_tools == policy.allowed_tools
    assert reloaded.require_confirmation == policy.require_confirmation


# ── Sprint 07: PolicyResult + check_policy ────────────────────────────────────

from app.sessions.policy import PolicyResult, check_policy


# ── PolicyResult ──────────────────────────────────────────────────────────────


def test_policy_result_allowed_is_truthy() -> None:
    r = PolicyResult(allowed=True)
    assert bool(r) is True


def test_policy_result_denied_is_falsy() -> None:
    r = PolicyResult(allowed=False, reason="not allowed", error_code="tool_not_allowed")
    assert bool(r) is False


def test_policy_result_repr_allowed() -> None:
    r = PolicyResult(allowed=True)
    assert "True" in repr(r)


def test_policy_result_repr_denied() -> None:
    r = PolicyResult(allowed=False, reason="blocked", error_code="channel_blocked")
    assert "False" in repr(r)
    assert "channel_blocked" in repr(r)


# ── check_policy: tool_call ────────────────────────────────────────────────────


def test_check_policy_tool_call_wildcard_allowed() -> None:
    policy = SessionPolicyPresets.ADMIN  # allowed_tools=["*"]
    result = check_policy(policy, "tool_call", tool_name="anything")
    assert result.allowed is True


def test_check_policy_tool_call_explicit_allowed() -> None:
    policy = SessionPolicy(allowed_tools=["web_search"])
    result = check_policy(policy, "tool_call", tool_name="web_search")
    assert result.allowed is True


def test_check_policy_tool_call_denied() -> None:
    policy = SessionPolicy(allowed_tools=["web_search"])
    result = check_policy(policy, "tool_call", tool_name="code_exec")
    assert result.allowed is False
    assert result.error_code == "tool_not_allowed"


# ── check_policy: channel_send ─────────────────────────────────────────────────


def test_check_policy_channel_send_allowed() -> None:
    policy = SessionPolicyPresets.STANDARD  # allowed_channels=["*"]
    result = check_policy(policy, "channel_send", channel="slack")
    assert result.allowed is True


def test_check_policy_channel_send_denied() -> None:
    policy = SessionPolicy(allowed_channels=["email"])
    result = check_policy(policy, "channel_send", channel="slack")
    assert result.allowed is False
    assert result.error_code == "channel_blocked"


# ── check_policy: path_access ──────────────────────────────────────────────────


def test_check_policy_path_access_allowed() -> None:
    policy = SessionPolicy(allowed_paths=["/safe/"])
    result = check_policy(policy, "path_access", path="/safe/file.txt")
    assert result.allowed is True


def test_check_policy_path_access_denied() -> None:
    policy = SessionPolicy(allowed_paths=["/safe/"])
    result = check_policy(policy, "path_access", path="/etc/passwd")
    assert result.allowed is False
    assert result.error_code == "path_not_allowed"


# ── check_policy: spawn_agent / inter_session_send ────────────────────────────


def test_check_policy_spawn_agent_allowed() -> None:
    policy = SessionPolicyPresets.ADMIN
    result = check_policy(policy, "spawn_agent")
    assert result.allowed is True


def test_check_policy_spawn_agent_denied() -> None:
    policy = SessionPolicyPresets.WORKER
    result = check_policy(policy, "spawn_agent")
    assert result.allowed is False
    assert result.error_code == "spawn_denied"


def test_check_policy_inter_session_allowed() -> None:
    policy = SessionPolicyPresets.ADMIN
    result = check_policy(policy, "inter_session_send")
    assert result.allowed is True


def test_check_policy_inter_session_denied() -> None:
    policy = SessionPolicy(can_send_inter_session=False)
    result = check_policy(policy, "inter_session_send")
    assert result.allowed is False
    assert result.error_code == "inter_session_denied"


# ── check_policy: unknown event type ──────────────────────────────────────────


def test_check_policy_unknown_event_type_is_denied() -> None:
    """Security: unknown event types default to denied (TD-231)."""
    policy = SessionPolicyPresets.READ_ONLY
    result = check_policy(policy, "future_event_type_xyz")
    assert result.allowed is False
    assert result.error_code == "unknown_event_type"
