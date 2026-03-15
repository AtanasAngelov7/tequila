"""Tool executor — approval gate, parallel execution, ToolResult (§11.2).

Flow for each tool call
-----------------------
1. Check ``policy.allowed_tools`` (``["*"]`` = allow all).
2. Determine if approval is required:
   - Safety level is ``destructive`` or ``critical``, AND
   - Tool is NOT in ``policy.auto_approve``.
   - OR tool is in ``policy.require_confirmation`` and NOT in ``policy.auto_approve``.
3. If approval required → emit ``APPROVAL_REQUEST`` gateway event → wait on
   an ``asyncio.Event`` up to ``APPROVAL_TIMEOUT_SECONDS``.
4. Execute the tool function (sync or async).
5. Return ``ToolResult``.

Parallel execution
------------------
``execute_many()`` runs all tool calls via ``asyncio.gather`` simultaneously,
then returns results in the same order.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from app.providers.base import ToolResult
from app.tools.registry import ToolDefinition, ToolRegistry, get_tool_registry

logger = logging.getLogger(__name__)

APPROVAL_TIMEOUT_SECONDS = 300  # 5 minutes


class ApprovalDenied(Exception):
    """Raised when a user denies or a timeout expires on an approval request."""


class ToolNotFound(Exception):
    """Raised when the executor cannot locate a tool by name."""


class ToolNotAllowed(Exception):
    """Raised when a tool call is blocked by SessionPolicy."""


# ── Pending approval tracker ──────────────────────────────────────────────────


class _PendingApproval:
    """One outstanding approval request waiting for a user decision."""

    def __init__(self, tool_call_id: str, tool_name: str) -> None:
        self.tool_call_id = tool_call_id
        self.tool_name = tool_name
        self.event: asyncio.Event = asyncio.Event()
        self.approved: bool = False


# ── ToolExecutor ──────────────────────────────────────────────────────────────


class ToolExecutor:
    """Executes tool calls with policy enforcement and approval gating.

    Parameters
    ----------
    registry:
        Tool registry to look up implementations.
    router:
        ``GatewayRouter`` instance — used to emit approval request events.
    """

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        router: Any | None = None,
    ) -> None:
        self._registry = registry or get_tool_registry()
        self._router = router
        # session_key → list of pending approvals
        self._pending: dict[str, list[_PendingApproval]] = {}
        # session_key → turn-level allow-all flag (cleared after each turn)
        self._allow_all: dict[str, bool] = {}

    # ── Policy helpers ────────────────────────────────────────────────────────

    def _is_allowed(self, tool_name: str, allowed_tools: list[str]) -> bool:
        if "*" in allowed_tools:
            return True
        return tool_name in allowed_tools

    def _needs_approval(
        self,
        td: ToolDefinition,
        policy: Any,  # SessionPolicy
        session_key: str,
    ) -> bool:
        """Return True if this tool call must pause for user confirmation."""
        # Turn-level allow-all overrides everything
        if self._allow_all.get(session_key):
            return False

        auto = getattr(policy, "auto_approve", [])
        require = getattr(policy, "require_confirmation", [])

        if td.name in auto:
            return False

        if td.name in require:
            return True

        # Safety-level defaults: destructive + critical require approval
        return td.safety in ("destructive", "critical")

    # ── Approval gate ─────────────────────────────────────────────────────────

    async def _await_approval(
        self,
        tool_call_id: str,
        tool_name: str,
        session_key: str,
    ) -> None:
        """Emit approval_request and block until approved, denied, or timed out."""
        pending = _PendingApproval(tool_call_id, tool_name)

        bucket = self._pending.setdefault(session_key, [])
        bucket.append(pending)

        # Emit gateway event
        if self._router is not None:
            from app.gateway.events import ET, GatewayEvent, StreamPayload

            payload = StreamPayload(
                kind="approval_request",
                tool_name=tool_name,
                tool_call_id=tool_call_id,
            )
            event = GatewayEvent(
                event_type=ET.AGENT_RUN_STREAM,
                source={"kind": "system", "id": "tool_executor"},
                session_key=session_key,
                payload=payload.model_dump(),
            )
            await self._router.emit(event)
            logger.info(
                "Approval request emitted for tool %r (call_id=%s)",
                tool_name,
                tool_call_id,
            )

        try:
            approved = await asyncio.wait_for(
                pending.event.wait(), timeout=APPROVAL_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Approval timeout for tool %r — auto-denying", tool_name
            )
            pending.approved = False
        finally:
            if pending in bucket:
                bucket.remove(pending)

        if not pending.approved:
            raise ApprovalDenied(
                f"Tool {tool_name!r} was denied or timed out."
            )

    def resolve_approval(
        self, session_key: str, tool_call_id: str, approved: bool
    ) -> None:
        """Called by the approval API endpoint to unblock a pending tool call.

        Parameters
        ----------
        session_key:
            Session identifier to locate the pending approval.
        tool_call_id:
            ID of the tool call being resolved.
        approved:
            ``True`` = user approved; ``False`` = user denied.
        """
        bucket = self._pending.get(session_key, [])
        for p in bucket:
            if p.tool_call_id == tool_call_id:
                p.approved = approved
                p.event.set()
                logger.info(
                    "Approval resolved for tool %r: %s",
                    p.tool_name,
                    "APPROVED" if approved else "DENIED",
                )
                return
        logger.warning(
            "resolve_approval: no pending approval found for call_id=%s",
            tool_call_id,
        )

    def set_allow_all(self, session_key: str, value: bool = True) -> None:
        """Grant or revoke turn-level allow-all for *session_key*."""
        self._allow_all[session_key] = value

    def clear_turn_state(self, session_key: str) -> None:
        """Reset per-turn approval state after turn completion."""
        self._allow_all.pop(session_key, None)
        self._pending.pop(session_key, None)

    # ── Single execution ──────────────────────────────────────────────────────

    async def execute(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        policy: Any,  # SessionPolicy
        session_key: str,
    ) -> ToolResult:
        """Execute one tool call, enforcing policy and approval gates.

        Returns a ``ToolResult`` — never raises (errors become failed results).
        """
        entry = self._registry.get(tool_name)
        if entry is None:
            logger.error("Tool not found: %r", tool_name)
            return ToolResult(
                tool_call_id=tool_call_id,
                success=False,
                result="",
                error=f"Tool {tool_name!r} is not registered.",
            )

        td, fn = entry

        # Policy: allowed_tools check
        allowed = getattr(policy, "allowed_tools", ["*"])
        if not self._is_allowed(tool_name, allowed):
            logger.warning("Tool %r blocked by policy for session %s", tool_name, session_key)
            return ToolResult(
                tool_call_id=tool_call_id,
                success=False,
                result="",
                error=f"Tool {tool_name!r} is not permitted in this session.",
            )

        # Approval gate
        if self._needs_approval(td, policy, session_key):
            try:
                await self._await_approval(tool_call_id, tool_name, session_key)
            except ApprovalDenied as exc:
                return ToolResult(
                    tool_call_id=tool_call_id,
                    success=False,
                    result="",
                    error=str(exc),
                )

        # Execute
        start_ms = time.monotonic()
        try:
            if asyncio.iscoroutinefunction(fn):
                raw = await fn(**arguments)
            else:
                raw = await asyncio.to_thread(fn, **arguments)

            elapsed_ms = int((time.monotonic() - start_ms) * 1000)

            return ToolResult(
                tool_call_id=tool_call_id,
                success=True,
                result=raw if raw is not None else "",
                execution_time_ms=elapsed_ms,
            )

        except Exception as exc:  # noqa: BLE001
            elapsed_ms = int((time.monotonic() - start_ms) * 1000)
            logger.exception("Tool %r raised an error", tool_name)
            return ToolResult(
                tool_call_id=tool_call_id,
                success=False,
                result="",
                error=str(exc),
                execution_time_ms=elapsed_ms,
            )

    # ── Parallel execution ────────────────────────────────────────────────────

    async def execute_many(
        self,
        tool_calls: list[dict[str, Any]],
        *,
        policy: Any,
        session_key: str,
    ) -> list[ToolResult]:
        """Execute multiple tool calls in parallel via ``asyncio.gather``.

        Each item in *tool_calls* must have keys:
        ``tool_call_id``, ``tool_name``, ``arguments``.

        Results are returned in the same order as the input list.
        """
        tasks = [
            self.execute(
                tool_call_id=tc["tool_call_id"],
                tool_name=tc["tool_name"],
                arguments=tc.get("arguments", {}),
                policy=policy,
                session_key=session_key,
            )
            for tc in tool_calls
        ]
        return list(await asyncio.gather(*tasks))


# ── Singleton ─────────────────────────────────────────────────────────────────

_executor: ToolExecutor | None = None


def get_tool_executor() -> ToolExecutor:
    """Return the process-wide ``ToolExecutor`` singleton."""
    global _executor
    if _executor is None:
        _executor = ToolExecutor()
    return _executor


def reset_tool_executor() -> None:
    """Reset the singleton — used in tests."""
    global _executor
    _executor = None
