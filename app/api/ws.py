"""WebSocket endpoint for the Tequila gateway (§13.2, §2.5, §2.5a).

Single connection at ``WS /api/ws``.

Wire protocol (§2.5):
- Client → Server: ``{ id, method, params }`` (``WSClientFrame``)
- Server → Client responses: ``{ id, ok, payload, error }`` (``WSServerResponse``)
- Server push events: ``{ event, payload, seq }`` (``WSServerEvent``)

Connect handshake (§2.5a):
- Client sends ``{ method: "connect", params: { last_seq: N } }``
- Server replays buffered events with ``seq > last_seq`` (or sends
  ``resync_required`` if ``last_seq`` is too old).

Heartbeat (§2.5a):
- Server sends ``{ event: "ping", seq: N }`` every 30 s.
- Client responds with ``{ method: "pong" }``.

Supported methods:
  connect            — initial handshake, optional reconnect replay
  pong               — heartbeat response (no reply)
  session.create     — create a new session
  session.resume     — resume / switch to an existing session by session_key
  message.send       — post a message to the active session (echoed in Sprint 02)
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.api.deps import require_ws_gateway_token
from app.gateway.buffer import EventBuffer

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

HEARTBEAT_INTERVAL_S = 30
WS_EVENT_BUFFER = EventBuffer(max_events=200, max_age_s=120.0)

# ── Router ────────────────────────────────────────────────────────────────────

router = APIRouter(tags=["websocket"])


# ── Frame helpers ─────────────────────────────────────────────────────────────


def _push(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Build a server push frame and record it in the event buffer.

    Returns the frame dict (caller sends it to the WebSocket).
    """
    frame: dict[str, Any] = {"event": event, "payload": payload}
    seq = WS_EVENT_BUFFER.push(frame)
    frame["seq"] = seq
    return frame


def _response(
    frame_id: str,
    *,
    ok: bool = True,
    payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build a response frame (not seq-numbered)."""
    return {
        "id": frame_id,
        "ok": ok,
        "payload": payload or {},
        "error": error,
    }


# ── WebSocket handler ─────────────────────────────────────────────────────────


@router.websocket("/api/ws")
async def websocket_endpoint(
    ws: WebSocket,
    _token: None = Depends(require_ws_gateway_token),
) -> None:
    """Main WebSocket handler."""
    await ws.accept()
    logger.info("WebSocket client connected", extra={"client": ws.client})

    # Per-connection state
    active_session_id: str | None = None
    active_session_key: str | None = None
    connected: bool = False

    async def send_json(data: dict[str, Any]) -> None:
        try:
            await ws.send_text(json.dumps(data))
        except WebSocketDisconnect:
            pass  # Connection already closed
        except RuntimeError:
            pass  # Starlette raises RuntimeError on a closed WS transport
        except Exception:
            logger.warning("Unexpected error in send_json", exc_info=True)

    # ── Heartbeat task ────────────────────────────────────────────────────────

    async def heartbeat() -> None:
        """Send a ping frame every HEARTBEAT_INTERVAL_S seconds."""
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)
            try:
                ping_frame = _push("ping", {})
                await ws.send_text(json.dumps(ping_frame))
            except Exception:
                break  # Connection closed

    heartbeat_task = asyncio.create_task(heartbeat())

    # ── Message dispatch ──────────────────────────────────────────────────────

    async def handle_connect(frame_id: str, params: dict[str, Any]) -> None:
        nonlocal connected

        last_seq: int = params.get("last_seq", 0)

        # Replay missed events or request resync
        if last_seq > 0:
            events, resync_required = WS_EVENT_BUFFER.events_since(last_seq)
            if resync_required:
                await send_json(_push("resync_required", {"reason": "buffer_expired"}))
            else:
                for ev in events:
                    await send_json(ev)

        connected = True
        await send_json(_response(frame_id, ok=True, payload={"connected": True}))
        # Push a connected event
        await send_json(_push("connected", {"next_seq": WS_EVENT_BUFFER.next_seq}))

    async def handle_session_create(frame_id: str, params: dict[str, Any]) -> None:
        nonlocal active_session_id, active_session_key

        from app.sessions.store import get_session_store

        try:
            store = get_session_store()
            session = await store.create(
                session_key=params.get("session_key"),
                kind=params.get("kind", "user"),
                agent_id=params.get("agent_id", "main"),
                channel="webchat",
                title=params.get("title"),
            )
            active_session_id = session.session_id
            active_session_key = session.session_key
            payload = {
                "session_id": session.session_id,
                "session_key": session.session_key,
                "status": session.status,
            }
            await send_json(_response(frame_id, ok=True, payload=payload))
            await send_json(_push("session.created", payload))
        except Exception as exc:
            logger.exception("session.create failed")
            await send_json(_response(frame_id, ok=False, error=str(exc)))

    async def handle_session_resume(frame_id: str, params: dict[str, Any]) -> None:
        nonlocal active_session_id, active_session_key

        from app.sessions.store import get_session_store
        from app.exceptions import SessionNotFoundError

        session_key: str = params.get("session_key", "")
        try:
            store = get_session_store()
            session = await store.get_by_key(session_key)
            active_session_id = session.session_id
            active_session_key = session.session_key
            payload = {
                "session_id": session.session_id,
                "session_key": session.session_key,
                "status": session.status,
            }
            await send_json(_response(frame_id, ok=True, payload=payload))
        except SessionNotFoundError:
            await send_json(
                _response(frame_id, ok=False, error=f"Session '{session_key}' not found")
            )
        except Exception as exc:
            logger.exception("session.resume failed")
            await send_json(_response(frame_id, ok=False, error=str(exc)))

    async def handle_message_send(frame_id: str, params: dict[str, Any]) -> None:
        """Persist message and trigger the agent turn loop (Sprint 05)."""
        if not active_session_id:
            await send_json(
                _response(frame_id, ok=False, error="No active session. Send session.create first.")
            )
            return

        from app.sessions.messages import get_message_store

        content: str = params.get("content", "")
        role: str = "user"  # TD-229: Force role=user for client-sent messages

        try:
            msg_store = get_message_store()
            message = await msg_store.insert(
                session_id=active_session_id,
                role=role,
                content=content,
                provenance="user_input" if role == "user" else "assistant_response",
            )
            msg_payload = {
                "id": message.id,
                "session_id": message.session_id,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at.isoformat(),
            }
            await send_json(_response(frame_id, ok=True, payload=msg_payload))
            # Push the persisted message as a server event
            await send_json(_push("message.created", msg_payload))

            # Trigger the turn loop for user messages (Sprint 05)
            if role == "user" and active_session_key:
                try:
                    from app.agent.turn_loop import get_turn_loop
                    turn_loop = get_turn_loop()
                    # TD-326: Track task reference to prevent GC and log exceptions
                    from app.api.tasks import track_task
                    track_task(
                        turn_loop.run_turn_from_api(
                            session_id=active_session_id,
                            session_key=active_session_key,
                            user_content=content,
                        ),
                        name=f"turn_loop_{message.id[:8]}",
                    )
                except RuntimeError:
                    pass  # Turn loop not initialised (test / early startup)

        except Exception as exc:
            logger.exception("message.send failed")
            await send_json(_response(frame_id, ok=False, error=str(exc)))

    async def handle_approval_respond(frame_id: str, params: dict[str, Any]) -> None:
        """User responds to a pending approval request."""
        tool_call_id: str = params.get("tool_call_id", "")
        approved: bool = bool(params.get("approved", False))
        allow_all: bool = bool(params.get("allow_all", False))

        if not active_session_key:
            await send_json(_response(frame_id, ok=False, error="No active session."))
            return

        try:
            from app.tools.executor import get_tool_executor
            executor = get_tool_executor()

            if allow_all:
                executor.set_allow_all(active_session_key, True)

            if tool_call_id:
                executor.resolve_approval(active_session_key, tool_call_id, approved)

            await send_json(_response(frame_id, ok=True, payload={"acknowledged": True}))
        except Exception as exc:
            logger.exception("approval.respond failed")
            await send_json(_response(frame_id, ok=False, error=str(exc)))

    # ── Main receive loop ─────────────────────────────────────────────────────

    # Per-connection gateway event forwarder (Sprint 05).
    # Filters by the active session_key and forwards all gateway events
    # as server push frames to this WebSocket client.
    async def _gateway_forwarder(event: Any) -> None:
        if active_session_key and event.session_key == active_session_key:
            await send_json(_push(event.event_type, event.payload))

    # Register on the gateway (if available)
    _gateway_registered = False
    try:
        from app.gateway.router import get_router as _get_router
        _gr = _get_router()
        _gr.on("*", _gateway_forwarder)
        _gateway_registered = True
    except RuntimeError:
        pass  # Gateway not started in tests / early startup

    try:
        while True:
            raw = await ws.receive_text()
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                await send_json(
                    {"id": "?", "ok": False, "payload": {}, "error": "Invalid JSON"}
                )
                continue

            frame_id: str = frame.get("id", "")
            method: str = frame.get("method", "")
            params: dict[str, Any] = frame.get("params", frame.get("payload", {}))

            # Require connect before any other method (except pong)
            if not connected and method not in ("connect", "pong"):
                await send_json(
                    _response(frame_id, ok=False, error="Must send 'connect' first")
                )
                continue

            if method == "connect":
                await handle_connect(frame_id, params)
            elif method == "pong":
                pass  # Nothing to do — heartbeat acknowledged
            elif method == "session.create":
                await handle_session_create(frame_id, params)
            elif method == "session.resume":
                await handle_session_resume(frame_id, params)
            elif method == "message.send":
                await handle_message_send(frame_id, params)
            elif method == "approval.respond":
                await handle_approval_respond(frame_id, params)
            else:
                await send_json(
                    _response(frame_id, ok=False, error=f"Unknown method: {method!r}")
                )

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected", extra={"client": ws.client})
    except Exception:
        logger.exception("WebSocket error")
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

        # Deregister gateway forwarder
        if _gateway_registered:
            try:
                from app.gateway.router import get_router as _get_router2
                _get_router2().off("*", _gateway_forwarder)
            except RuntimeError:
                pass
