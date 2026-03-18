"""Session-level capability policy model, presets, and enforcement (§2.7, §11.2).

``SessionPolicy``        — defines what an agent is allowed to do in a session.
``SessionPolicyPresets`` — named presets for common access patterns.
``PolicyResult``         — (Sprint 07) result object from a policy check.
``check_policy``         — (Sprint 07) gateway-level policy enforcement function.
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


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
        """Return ``True`` if *path* is within an allowed path prefix.

        TD-320: Paths are normalised via ``os.path.normpath`` to prevent
        ``../`` traversal bypasses.
        TD-352: Compare with trailing separator so ``/tmp/safe`` does not
        match ``/tmp/safety-bypass``.
        """
        import os
        if self.allowed_paths == ["*"]:
            return True
        norm = os.path.normpath(path)
        return any(
            norm == os.path.normpath(allowed)
            or norm.startswith(os.path.normpath(allowed) + os.sep)
            for allowed in self.allowed_paths
        )

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
        import copy
        return copy.deepcopy(preset_map[key])


# ── PolicyResult & check_policy (Sprint 07) ───────────────────────────────────


class PolicyResult:
    """Outcome of a gateway-level policy check.

    Attributes
    ----------
    allowed:
        ``True`` when the action is permitted; ``False`` when it is blocked.
    reason:
        Human-readable explanation (always set when ``allowed=False``).
    error_code:
        Machine-readable code for the denial reason.  One of:

        ``"tool_not_allowed"``      — tool absent from ``allowed_tools``.
        ``"channel_blocked"``       — channel absent from ``allowed_channels``.
        ``"path_not_allowed"``      — path outside ``allowed_paths``.
        ``"spawn_denied"``          — ``can_spawn_agents`` is ``False``.
        ``"inter_session_denied"``  — ``can_send_inter_session`` is ``False``.
    """

    __slots__ = ("allowed", "reason", "error_code")

    def __init__(
        self,
        allowed: bool,
        reason: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self.allowed = allowed
        self.reason = reason
        self.error_code = error_code

    def __bool__(self) -> bool:
        return self.allowed

    def __repr__(self) -> str:
        if self.allowed:
            return "PolicyResult(allowed=True)"
        return f"PolicyResult(allowed=False, error_code={self.error_code!r}, reason={self.reason!r})"


def check_policy(
    policy: "SessionPolicy",
    event_type: str,
    **kwargs: Any,
) -> PolicyResult:
    """Evaluate a gateway policy check and return a ``PolicyResult``.

    Parameters
    ----------
    policy:
        The ``SessionPolicy`` for the current session.
    event_type:
        Type of action being checked.  Supported values:

        * ``"tool_call"``         — ``tool_name`` kwarg required.
        * ``"channel_send"``      — ``channel`` kwarg required.
        * ``"path_access"``       — ``path`` kwarg required.
        * ``"spawn_agent"``       — no extra kwargs.
        * ``"inter_session_send"``— no extra kwargs.

    **kwargs:
        Action-specific parameters (see *event_type* above).

    Returns
    -------
    PolicyResult
        ``allowed=True`` when the action is permitted; ``allowed=False``
        (with ``reason`` and ``error_code`` set) when it is blocked.

    Examples
    --------
    ::

        result = check_policy(session.policy, "tool_call", tool_name="fs_write_file")
        if not result:
            raise AccessDeniedError(result.reason)
    """
    if event_type == "tool_call":
        tool_name: str = kwargs.get("tool_name", "")
        if not policy.allows_tool(tool_name):
            return PolicyResult(
                allowed=False,
                reason=f"Tool {tool_name!r} is not permitted in this session.",
                error_code="tool_not_allowed",
            )
        return PolicyResult(allowed=True)

    if event_type == "channel_send":
        channel: str = kwargs.get("channel", "")
        if not policy.allows_channel(channel):
            return PolicyResult(
                allowed=False,
                reason=f"Channel {channel!r} is not permitted in this session.",
                error_code="channel_blocked",
            )
        return PolicyResult(allowed=True)

    if event_type == "path_access":
        path: str = kwargs.get("path", "")
        if not policy.allows_path(path):
            return PolicyResult(
                allowed=False,
                reason=f"Path {path!r} is outside allowed paths for this session.",
                error_code="path_not_allowed",
            )
        return PolicyResult(allowed=True)

    if event_type == "spawn_agent":
        if not policy.can_spawn_agents:
            return PolicyResult(
                allowed=False,
                reason="This session is not permitted to spawn sub-agent sessions.",
                error_code="spawn_denied",
            )
        return PolicyResult(allowed=True)

    if event_type == "inter_session_send":
        if not policy.can_send_inter_session:
            return PolicyResult(
                allowed=False,
                reason="This session is not permitted to send inter-session messages.",
                error_code="inter_session_denied",
            )
        return PolicyResult(allowed=True)

    # TD-231: Unknown event types default to deny for security
    logger.warning("Unknown policy event_type %r — denying by default.", event_type)
    return PolicyResult(
        allowed=False,
        reason=f"Unknown event type {event_type!r} is not permitted.",
        error_code="unknown_event_type",
    )
