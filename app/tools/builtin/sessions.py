"""Sprint 08 — Session tools for agent-to-agent communication (§3.3).

Provides four tools:

- ``sessions_list``    — discover active sessions (``read_only``).
- ``sessions_history`` — read another session's transcript (``read_only``).
- ``sessions_send``    — inject a message into another session (``side_effect``).
- ``sessions_spawn``   — create a new sub-agent session (``side_effect``).

Visibility scoping
------------------
These tools use singleton stores (``get_session_store``, ``get_message_store``)
so they work both when called from the tool executor (runtime) and in tests that
inject custom stores via the singleton initialisation pattern.

``sessions_send`` with ``timeout_s > 0`` subscribes to ``agent.run.complete``
on the gateway router and waits up to *timeout_s* seconds for the target agent
to reply.  It then reads the most recent assistant message from the session.

``sessions_spawn`` delegates to ``app.agent.sub_agent.spawn_sub_agent`` which
enforces the per-parent concurrency limit (``MAX_CONCURRENT_SUBAGENTS``).
"""
from __future__ import annotations

import asyncio
import json
import logging

from app.gateway.events import ET, EventSource, GatewayEvent
from app.gateway.router import get_router
from app.sessions.messages import get_message_store
from app.sessions.store import get_session_store
from app.tools.registry import tool

logger = logging.getLogger(__name__)


# ── sessions_list ─────────────────────────────────────────────────────────────


@tool(
    description=(
        "List accessible sessions.  Returns session_key, kind, agent_id, title, "
        "and status for each session.  Optional filters: kind, agent_id."
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "description": "Filter by session kind: user|agent|channel|cron|webhook|workflow",
            },
            "agent_id": {
                "type": "string",
                "description": "Filter to sessions belonging to a specific agent.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of sessions to return (default 20, max 50).",
            },
        },
        "required": [],
    },
)
async def sessions_list(
    kind: str | None = None,
    agent_id: str | None = None,
    limit: int = 20,
) -> str:
    """Return a JSON list of accessible sessions."""
    store = get_session_store()
    limit = min(max(1, limit), 50)
    sessions = await store.list(kind=kind, agent_id=agent_id, limit=limit)
    result = [
        {
            "session_key": s.session_key,
            "kind": s.kind,
            "agent_id": s.agent_id,
            "title": s.title,
            "status": s.status,
        }
        for s in sessions
    ]
    return json.dumps(result)


# ── sessions_history ──────────────────────────────────────────────────────────


@tool(
    description=(
        "Read recent messages from another session.  Returns role, content, "
        "and created_at for each message, oldest-first."
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "session_key": {
                "type": "string",
                "description": "The session_key of the session to read history from.",
            },
            "limit": {
                "type": "integer",
                "description": "Number of most-recent messages to return (default 20, max 100).",
            },
        },
        "required": ["session_key"],
    },
)
async def sessions_history(
    session_key: str,
    limit: int = 20,
) -> str:
    """Return a JSON list of recent messages from *session_key*."""
    ss = get_session_store()
    ms = get_message_store()
    # Resolve session_key → internal UUID for the messages FK query.
    session = await ss.get_by_key(session_key)
    if session is None:
        return json.dumps([])
    limit = min(max(1, limit), 100)
    messages = await ms.list_by_session(session.session_id, limit=limit, active_only=True)
    result = [
        {
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]
    return json.dumps(result)


# ── sessions_send ─────────────────────────────────────────────────────────────


@tool(
    description=(
        "Send a message to another session, optionally waiting for the agent to reply.  "
        "Use timeout_s=0 for fire-and-forget.  Use timeout_s>0 to wait for a reply."
    ),
    safety="side_effect",
    parameters={
        "type": "object",
        "properties": {
            "session_key": {
                "type": "string",
                "description": "The session_key of the target session.",
            },
            "message": {
                "type": "string",
                "description": "The message text to send.",
            },
            "timeout_s": {
                "type": "integer",
                "description": (
                    "Seconds to wait for an agent reply.  "
                    "0 = fire-and-forget (default).  >0 = wait for reply."
                ),
            },
        },
        "required": ["session_key", "message"],
    },
)
async def sessions_send(
    session_key: str,
    message: str,
    timeout_s: int = 0,
) -> str:
    """Inject *message* into *session_key* and optionally wait for a reply."""
    router = get_router()

    # Build the gateway event
    event = GatewayEvent(
        event_type=ET.INBOUND_MESSAGE,
        source=EventSource(kind="agent", id="sessions_send_tool"),
        session_key=session_key,
        payload={
            "session_id": session_key,
            "content": message,
            "provenance": "inter_session",
        },
    )

    if timeout_s <= 0:
        # Fire-and-forget
        router.emit_nowait(event)
        return json.dumps({"status": "accepted", "session_key": session_key})

    # ── Wait for completion ───────────────────────────────────────────────────
    done = asyncio.Event()
    reply: dict = {}

    async def _on_complete(evt: GatewayEvent) -> None:
        if evt.session_key == session_key:
            reply["payload"] = evt.payload
            done.set()

    router.on(ET.AGENT_RUN_COMPLETE, _on_complete)
    try:
        router.emit_nowait(event)
        await asyncio.wait_for(done.wait(), timeout=float(timeout_s))
    except asyncio.TimeoutError:
        logger.warning(
            "sessions_send: timeout waiting for reply from session %s", session_key
        )
        return json.dumps({"status": "timeout", "session_key": session_key})
    finally:
        router.off(ET.AGENT_RUN_COMPLETE, _on_complete)

    # Read the last assistant message from the session
    try:
        msg_store = get_message_store()
        ss = get_session_store()
        _session = await ss.get_by_key(session_key)
        _sid = _session.session_id if _session else session_key
        messages = await msg_store.list_by_session(_sid, limit=1, active_only=True)
        last_msgs = [m for m in messages if m.role == "assistant"]
        if last_msgs:
            return json.dumps({
                "status": "reply",
                "session_key": session_key,
                "content": last_msgs[-1].content,
            })
    except Exception:
        logger.warning("sessions_send: could not read reply from session %s", session_key, exc_info=True)

    return json.dumps({"status": "completed", "session_key": session_key})


# ── sessions_spawn ────────────────────────────────────────────────────────────


@tool(
    description=(
        "Create a new sub-agent session with the specified agent.  "
        "Optionally provide an initial message to start the agent's first turn.  "
        "Returns the session_key of the new session immediately."
    ),
    safety="side_effect",
    parameters={
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "The agent_id to use for the new session.",
            },
            "initial_message": {
                "type": "string",
                "description": "Optional first message to send the sub-agent.",
            },
            "policy_preset": {
                "type": "string",
                "description": (
                    "Session policy preset: worker (default), read_only, code_runner. "
                    "Applies capability restrictions to the spawned agent."
                ),
            },
        },
        "required": ["agent_id"],
    },
)
async def sessions_spawn(
    agent_id: str,
    initial_message: str | None = None,
    policy_preset: str = "worker",
) -> str:
    """Create a sub-agent session and return its session_key."""
    from app.agent.sub_agent import spawn_sub_agent  # lazy to avoid early circular import

    try:
        sub_key = await spawn_sub_agent(
            agent_id=agent_id,
            initial_message=initial_message,
            policy_preset=policy_preset,
        )
        return json.dumps({"status": "spawned", "session_key": sub_key, "agent_id": agent_id})
    except RuntimeError as exc:
        logger.warning("sessions_spawn failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})
