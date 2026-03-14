"""REST API for session messages (§3.4, §13.1).

Endpoints:
  GET  /api/sessions/{session_id}/messages — list messages (paginated)
  POST /api/sessions/{session_id}/messages — insert a message (echo, no LLM)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.deps import require_gateway_token
from app.sessions.messages import get_message_store
from app.sessions.models import Message
from app.sessions.store import get_session_store

router = APIRouter(prefix="/api/sessions", tags=["messages"])


# ── Request / Response schemas ────────────────────────────────────────────────


class CreateMessageRequest(BaseModel):
    role: str = "user"
    content: str


class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    created_at: str
    updated_at: str | None


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]
    total: int


def _message_to_response(m: Message) -> MessageResponse:
    return MessageResponse(
        id=m.id,
        session_id=m.session_id,
        role=m.role,
        content=m.content,
        created_at=m.created_at.isoformat(),
        updated_at=m.updated_at.isoformat() if m.updated_at else None,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/{session_id}/messages", response_model=MessageListResponse)
async def list_messages(
    session_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    active_only: bool = Query(True),
    _token: None = Depends(require_gateway_token),
) -> MessageListResponse:
    """List messages for a session, oldest first."""
    # Verify session exists
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


@router.post("/{session_id}/messages", response_model=MessageResponse, status_code=201)
async def create_message(
    session_id: str,
    body: CreateMessageRequest,
    _token: None = Depends(require_gateway_token),
) -> MessageResponse:
    """Insert a message into a session.

    In Sprint 02 this echoes the user message and inserts it directly — no LLM
    turn is triggered yet.  The agent turn loop is wired up in Sprint 05.
    """
    # Verify session exists
    await get_session_store().get_by_id(session_id)

    store = get_message_store()
    message = await store.insert(
        session_id=session_id,
        role=body.role,
        content=body.content,
    )
    return _message_to_response(message)
