"""Session-level capability policy model and presets for Tequila v2 (§2.7).

``SessionPolicy`` defines what an agent is allowed to do within a session.
``SessionPolicyPresets`` provides named presets for common access patterns.

Enforcement wiring (gateway-level checks before tool execution, delivery, etc.)
is added in Sprint 07.  This module is data-model-only: it defines the
structures and validates field values.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


# ── Policy model ──────────────────────────────────────────────────────────────


class SessionPolicy(BaseModel):
    """Capability policy controlling what an agent can do within a session.

    Sentinel convention (§spec):
    - ``["*"]`` means "all allowed" (no restriction).
    - ``[]`` means "nothing allowed".
    - ``None`` is never used as a sentinel here; all list fields default to
      ``["*"]`` or ``[]`` as appropriate.
    """

    allowed_channels: list[str] = Field(default_factory=lambda: ["*"])
    """Channels the agent is permitted to deliver messages to.

    ``["*"]`` = any channel.  ``[]`` = no outbound delivery allowed.
    """

    allowed_tools: list[str] = Field(default_factory=lambda: ["*"])
    """Tool names the agent is permitted to invoke.

    ``["*"]`` = all registered tools.  ``[]`` = no tool execution.
    """

    allowed_paths: list[str] = Field(default_factory=lambda: ["*"])
    """Filesystem path prefixes the agent is allowed to read/write.

    ``["*"]`` = unrestricted.  Specific paths restrict access to those
    subtrees only.
    """

    can_spawn_agents: bool = True
    """Whether the session may spawn sub-agent sessions via ``sessions_spawn``."""

    can_send_inter_session: bool = True
    """Whether the session may send messages to other sessions via ``sessions_send``."""

    max_tokens_per_run: int | None = None
    """Optional token budget cap per agent turn.  ``None`` = no cap."""

    max_tool_rounds: int = 25
    """Maximum number of tool call rounds the agent may execute per turn."""

    require_confirmation: list[str] = Field(default_factory=list)
    """Tool names that require explicit user approval before execution.

    Tools in this list will trigger an approval gate in the gateway unless
    they are also in ``auto_approve``.
    """

    auto_approve: list[str] = Field(default_factory=list)
    """Tools that bypass the confirmation gate in this session.

    Takes precedence over ``require_confirmation`` for the same tool name.
    """

    extra: dict[str, Any] = Field(default_factory=dict)
    """Forward-compatible extension fields (sprint-by-sprint additions)."""

    @model_validator(mode="after")
    def _validate_tool_round_positive(self) -> "SessionPolicy":
        if self.max_tool_rounds <= 0:
            raise ValueError("max_tool_rounds must be a positive integer.")
        return self

    def allows_tool(self, tool_name: str) -> bool:
        """Return ``True`` if *tool_name* is permitted by this policy.

        A tool is allowed when ``allowed_tools`` is ``["*"]`` or the tool
        name appears in the list.
        """
        if self.allowed_tools == ["*"]:
            return True
        return tool_name in self.allowed_tools

    def allows_channel(self, channel: str) -> bool:
        """Return ``True`` if delivery to *channel* is permitted."""
        if self.allowed_channels == ["*"]:
            return True
        return channel in self.allowed_channels

    def allows_path(self, path: str) -> bool:
        """Return ``True`` if *path* is within an allowed path prefix."""
        if self.allowed_paths == ["*"]:
            return True
        return any(path.startswith(allowed) for allowed in self.allowed_paths)

    def needs_confirmation(self, tool_name: str) -> bool:
        """Return ``True`` if *tool_name* must pass an approval gate.

        A confirmation is required when the tool is in ``require_confirmation``
        **and** not in ``auto_approve``.
        """
        return (
            tool_name in self.require_confirmation
            and tool_name not in self.auto_approve
        )


# ── Presets ───────────────────────────────────────────────────────────────────


class SessionPolicyPresets:
    """Named preset policies for common session types (§2.7)."""

    ADMIN: SessionPolicy = SessionPolicy()
    """Full access — no restrictions of any kind.  For the main user session."""

    STANDARD: SessionPolicy = SessionPolicy(
        require_confirmation=["code_exec", "fs_write_file", "fs_delete"],
    )
    """Default user session policy.  Dangerous tools require explicit approval."""

    WORKER: SessionPolicy = SessionPolicy(
        can_spawn_agents=False,
        can_send_inter_session=False,
        allowed_channels=[],
    )
    """Sub-agent policy: no external delivery, no inter-session messaging."""

    CODE_RUNNER: SessionPolicy = SessionPolicy(
        can_spawn_agents=False,
        can_send_inter_session=False,
        allowed_channels=[],
        allowed_tools=["code_exec", "fs_read_file", "fs_write_file", "fs_list_dir"],
    )
    """Restricted to code execution and file I/O tools only."""

    READ_ONLY: SessionPolicy = SessionPolicy(
        allowed_tools=[],
        can_spawn_agents=False,
        can_send_inter_session=False,
        allowed_channels=[],
    )
    """No writes, no tool execution — read-only session."""

    CHAT_ONLY: SessionPolicy = SessionPolicy(
        allowed_tools=[],
        can_spawn_agents=False,
    )
    """Text conversation only — no tool execution permitted."""

    @classmethod
    def by_name(cls, name: str) -> SessionPolicy:
        """Look up a preset by name string (case-insensitive).

        Args:
            name: One of ``ADMIN``, ``STANDARD``, ``WORKER``,
                ``CODE_RUNNER``, ``READ_ONLY``, ``CHAT_ONLY``.

        Raises:
            ValueError: When *name* does not match any preset.
        """
        preset_map: dict[str, SessionPolicy] = {
            "admin": cls.ADMIN,
            "standard": cls.STANDARD,
            "worker": cls.WORKER,
            "code_runner": cls.CODE_RUNNER,
            "read_only": cls.READ_ONLY,
            "chat_only": cls.CHAT_ONLY,
        }
        key = name.lower()
        if key not in preset_map:
            raise ValueError(
                f"Unknown preset '{name}'. Valid values: {list(preset_map.keys())}"
            )
        return preset_map[key]
