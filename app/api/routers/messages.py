"""REST API for session messages (§3.4, §3.6, §13.1) — Sprint 05.

Endpoints:
  GET    /api/sessions/{session_id}/messages   — list messages (paginated)
  POST   /api/sessions/{session_id}/messages   — insert a message (echo, triggers turn loop)
  PATCH  /api/messages/{message_id}/feedback   — set thumbs up/down feedback
  DELETE /api/messages/{message_id}/feedback   — clear feedback
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import require_gateway_token
from app.exceptions import NotFoundError
from app.sessions.messages import get_message_store
from app.sessions.models import Message
from app.sessions.store import get_session_store

router = APIRouter(tags=["messages"])


# ── Request / Response schemas ────────────────────────────────────────────────


class CreateMessageRequest(BaseModel):
    role: str = "user"
    content: str
    trigger_turn: bool = True
    """If True and role=user, trigger the agent turn loop after inserting."""


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    note: str | None = None


class ContentBlockOut(BaseModel):
    type: str
    text: str | None = None
    file_id: str | None = None
    mime_type: str | None = None
    alt_text: str | None = None


class ToolCallOut(BaseModel):
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    result: Any = None
    success: bool | None = None
    execution_time_ms: int | None = None
    approval_status: str | None = None


class FeedbackOut(BaseModel):
    rating: str
    note: str | None
    created_at: str


class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    content_blocks: list[ContentBlockOut] = []
    tool_calls: list[ToolCallOut] | None = None
    tool_call_id: str | None = None
    file_ids: list[str] = []
    parent_id: str | None = None
    active: bool = True
    provenance: str = "user_input"
    compressed: bool = False
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    feedback: FeedbackOut | None = None
    created_at: str
    updated_at: str | None


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]
    total: int


def _message_to_response(m: Message) -> MessageResponse:
    feedback_out: FeedbackOut | None = None
    if m.feedback is not None:
        feedback_out = FeedbackOut(
            rating=m.feedback.rating,
            note=m.feedback.note,
            created_at=m.feedback.created_at.isoformat(),
        )

    return MessageResponse(
        id=m.id,
        session_id=m.session_id,
        role=m.role,
        content=m.content,
        content_blocks=[ContentBlockOut(**cb.model_dump()) for cb in m.content_blocks],
        tool_calls=(
            [ToolCallOut(**tc.model_dump()) for tc in m.tool_calls]
            if m.tool_calls else None
        ),
        tool_call_id=m.tool_call_id,
        file_ids=m.file_ids,
        parent_id=m.parent_id,
        active=m.active,
        provenance=m.provenance,
        compressed=m.compressed,
        model=m.model,
        input_tokens=m.input_tokens,
        output_tokens=m.output_tokens,
        feedback=feedback_out,
        created_at=m.created_at.isoformat(),
        updated_at=m.updated_at.isoformat() if m.updated_at else None,
    )


# ── Session-scoped message endpoints ─────────────────────────────────────────


@router.get("/api/sessions/{session_id}/messages", response_model=MessageListResponse)
async def list_messages(
    session_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    active_only: bool = Query(True),
    _token: None = Depends(require_gateway_token),
) -> MessageListResponse:
    """List messages for a session, oldest first."""
    await get_session_store().get_by_id(session_id)
    store = get_message_store()
    messages = await store.list_by_session(
        session_id,
        limit=limit,
        offset=offset,
        active_only=active_only,
    )
    return MessageListResponse(
        messages=[_message_to_response(m) for m in messages],
        total=len(messages),
    )


@router.post("/api/sessions/{session_id}/messages", response_model=MessageResponse, status_code=201)
async def create_message(
    session_id: str,
    body: CreateMessageRequest,
    _token: None = Depends(require_gateway_token),
) -> MessageResponse:
    """Insert a message into a session and optionally trigger the turn loop."""
    session = await get_session_store().get_by_id(session_id)

    store = get_message_store()
    message = await store.insert(
        session_id=session_id,
        role=body.role,
        content=body.content,
        provenance="user_input" if body.role == "user" else "assistant_response",
    )

    # Trigger turn loop for user messages when requested
    if body.role == "user" and body.trigger_turn:
        try:
            from app.agent.turn_loop import get_turn_loop
            turn_loop = get_turn_loop()
            import asyncio
            asyncio.create_task(
                turn_loop.run_turn_from_api(
                    session_id=session_id,
                    session_key=session.session_key,
                    user_content=body.content,
                )
            )
        except Exception:
            # Turn loop not yet wired — ignore for backward compat
            pass

    return _message_to_response(message)


# ── Message-level endpoints ───────────────────────────────────────────────────


@router.patch("/api/messages/{message_id}/feedback", response_model=MessageResponse)
async def set_feedback(
    message_id: str,
    body: FeedbackRequest,
    _token: None = Depends(require_gateway_token),
) -> MessageResponse:
    """Set thumbs-up or thumbs-down feedback on a message."""
    store = get_message_store()
    try:
        message = await store.update_feedback(
            message_id,
            rating=body.rating,
            note=body.note,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Message not found")
    return _message_to_response(message)


@router.delete("/api/messages/{message_id}/feedback", response_model=MessageResponse)
async def delete_feedback(
    message_id: str,
    _token: None = Depends(require_gateway_token),
) -> MessageResponse:
    """Clear feedback from a message."""
    store = get_message_store()
    try:
        message = await store.update_feedback(message_id, rating=None)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Message not found")
    return _message_to_response(message)
