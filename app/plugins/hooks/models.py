"""Hook models for the pipeline hook system (Sprint 13, D5)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

# The six hook-points in the agent pipeline.
HookPoint = Literal[
    "pre_prompt",
    "post_prompt",
    "pre_tool",
    "post_tool",
    "pre_response",
    "post_response",
]


class HookContext(BaseModel):
    """Context passed to every hook function.

    Hooks may mutate ``data`` in-place or return a new :class:`HookResult`
    with ``modified_data`` set.
    """

    hook_point: HookPoint
    session_id: str
    agent_id: str | None = None
    data: dict[str, Any] = {}
    """Mutable payload for this hook point.

    - ``pre_prompt`` / ``post_prompt``: ``{messages: [...], system: str}``
    - ``pre_tool`` / ``post_tool``:  ``{tool_name: str, arguments: dict, result: Any}``
    - ``pre_response`` / ``post_response``: ``{text: str}``
    """


class HookResult(BaseModel):
    """Return value of a hook callable.

    If ``abort`` is True the pipeline step is skipped (and the agent
    receives an empty / default result).  If ``modified_data`` is set the
    pipeline continues with the updated data.
    """

    abort: bool = False
    modified_data: dict[str, Any] | None = None
    log_message: str | None = None


class PipelineHookSpec(BaseModel):
    """Metadata that ties a callable to a hook-point registration."""

    hook_point: HookPoint
    priority: int = 50
    """Lower numbers run first (0 = highest priority)."""
    plugin_id: str = ""
    description: str = ""
