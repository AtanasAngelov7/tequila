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
