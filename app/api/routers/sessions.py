"""REST API for session management (§3.2, §3.7, §13.1, §13.4) — Sprint 05 / 14b.

Endpoints:
  POST   /api/sessions                    — create session
  GET    /api/sessions                    — list sessions (filters, pagination)
  GET    /api/sessions/{session_id}       — retrieve single session
  PATCH  /api/sessions/{session_id}       — update title / summary / metadata
  DELETE /api/sessions/{session_id}       — permanently delete
  POST   /api/sessions/{session_id}/archive       — archive session
  POST   /api/sessions/{session_id}/unarchive     — restore from archive
  POST   /api/sessions/{session_id}/regenerate    — regenerate last response
  POST   /api/sessions/{session_id}/edit          — edit user message + resubmit
  GET    /api/sessions/{session_id}/export        — export transcript (§13.4)
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from app.api.deps import get_config_dep, require_gateway_token
from app.exceptions import SessionNotFoundError
from app.sessions.models import Session
from app.sessions.store import get_session_store

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


# ── Request / Response schemas ────────────────────────────────────────────────


class CreateSessionRequest(BaseModel):
    session_key: str | None = None
    kind: str = "user"
    agent_id: str | None = None  # None → resolved from setup.main_agent_id
    channel: str = "webchat"
    policy: dict[str, Any] | None = None
    parent_session_key: str | None = None
    title: str | None = None
    metadata: dict[str, Any] | None = None


class UpdateSessionRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    metadata: dict[str, Any] | None = None


class SessionResponse(BaseModel):
    session_id: str
    session_key: str
    kind: str
    agent_id: str
    channel: str
    status: str
    title: str | None
    summary: str | None
    message_count: int
    last_message_at: str | None
    created_at: str
    updated_at: str
    version: int
    metadata: dict[str, Any]
    policy: dict[str, Any]


def _session_to_response(s: Session) -> SessionResponse:
    return SessionResponse(
        session_id=s.session_id,
        session_key=s.session_key,
        kind=s.kind,
        agent_id=s.agent_id,
        channel=s.channel,
        status=s.status,
        title=s.title,
        summary=s.summary,
        message_count=s.message_count,
        last_message_at=s.last_message_at.isoformat() if s.last_message_at else None,
        created_at=s.created_at.isoformat(),
        updated_at=s.updated_at.isoformat(),
        version=s.version,
        metadata=s.metadata,
        policy=s.policy.model_dump(),
    )


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]
    total: int


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    _token: None = Depends(require_gateway_token),
) -> SessionResponse:
    """Create a new session."""
    # Resolve agent_id: if not explicitly provided, use the agent created during
    # setup; fall back to "main" for backwards compatibility.
    if body.agent_id:
        resolved_agent_id = body.agent_id
    else:
        try:
            resolved_agent_id = get_config_dep().get("setup.main_agent_id", "") or "main"
        except Exception:
            resolved_agent_id = "main"
    store = get_session_store()
    session = await store.create(
        session_key=body.session_key,
        kind=body.kind,
        agent_id=resolved_agent_id,
        channel=body.channel,
        policy=body.policy,
        parent_session_key=body.parent_session_key,
        title=body.title,
        metadata=body.metadata,
    )
    return _session_to_response(session)


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    status: str | None = Query(None, description="Filter by status: active|idle|archived"),
    kind: str | None = Query(None, description="Filter by kind: user|agent|channel|cron|webhook|workflow"),
    agent_id: str | None = Query(None),
    q: str | None = Query(None, description="Search across session title and summary"),
    sort: str = Query("last_activity", description="Sort by: last_activity|created|message_count|title"),
    order: str = Query("desc", description="Sort direction: asc|desc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _token: None = Depends(require_gateway_token),
) -> SessionListResponse:
    """List sessions with optional filters, search, and sort."""
    # Treat "all" as no filter so the frontend can use a consistent param.
    status_filter = None if status in (None, "all") else status
    store = get_session_store()
    sessions = await store.list(
        status=status_filter,
        kind=kind,
        agent_id=agent_id,
        q=q,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )
    # TD-161: Get true total from a count query, not page length
    total = await store.count(
        status=status_filter,
        kind=kind,
        agent_id=agent_id,
        q=q,
    )
    return SessionListResponse(
        sessions=[_session_to_response(s) for s in sessions],
        total=total,
    )


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    _token: None = Depends(require_gateway_token),
) -> SessionResponse:
    """Retrieve a single session by ID."""
    store = get_session_store()
    session = await store.get_by_id(session_id)
    return _session_to_response(session)


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str,
    body: UpdateSessionRequest,
    _token: None = Depends(require_gateway_token),
) -> SessionResponse:
    """Update title, summary, or metadata on a session."""
    store = get_session_store()
    session = await store.update(
        session_id,
        title=body.title,
        summary=body.summary,
        metadata=body.metadata,
    )
    return _session_to_response(session)


# ── Policy endpoint (Sprint 07) ───────────────────────────────────────────────


class UpdatePolicyRequest(BaseModel):
    """Request body for ``PATCH /api/sessions/{id}/policy``."""

    policy: dict[str, Any]
    """Full or partial ``SessionPolicy`` as a JSON object.

    Supplied fields are merged into the existing policy (a full replacement
    is performed — the entire policy is overwritten with the provided object).
    """

    preset: str | None = None
    """Optional named preset (``ADMIN``, ``STANDARD``, ``WORKER``, etc.).

    When *preset* is supplied, the preset policy is used as the base and any
    fields in *policy* are merged on top.
    """


class PolicyResponse(BaseModel):
    session_id: str
    policy: dict[str, Any]


@router.patch("/{session_id}/policy", response_model=PolicyResponse)
async def update_session_policy(
    session_id: str,
    body: UpdatePolicyRequest,
    _token: None = Depends(require_gateway_token),
) -> PolicyResponse:
    """Replace (or merge with a preset) the session policy (Sprint 07, §2.7).

    Returns the new effective policy.
    """
    from app.sessions.policy import SessionPolicy, SessionPolicyPresets
    from fastapi import HTTPException

    # Start from preset or current policy
    if body.preset:
        try:
            base = SessionPolicyPresets.by_name(body.preset)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        # Merge patch fields on top of preset
        merged = {**base.model_dump(), **body.policy}
    else:
        merged = body.policy

    try:
        new_policy = SessionPolicy.model_validate(merged)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid policy: {exc}")

    store = get_session_store()
    try:
        session = await store.update(session_id, policy=new_policy)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found.")

    return PolicyResponse(session_id=session_id, policy=session.policy.model_dump())


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    _token: None = Depends(require_gateway_token),
) -> None:
    """Permanently delete a session and all its messages."""
    store = get_session_store()
    await store.delete(session_id)


@router.post("/{session_id}/archive", response_model=SessionResponse)
async def archive_session(
    session_id: str,
    _token: None = Depends(require_gateway_token),
) -> SessionResponse:
    """Archive a session."""
    store = get_session_store()
    session = await store.archive(session_id)
    return _session_to_response(session)


@router.post("/{session_id}/unarchive", response_model=SessionResponse)
async def unarchive_session(
    session_id: str,
    _token: None = Depends(require_gateway_token),
) -> SessionResponse:
    """Restore an archived session to active status."""
    store = get_session_store()
    session = await store.unarchive(session_id)
    return _session_to_response(session)


# ── Branching & regeneration (§3.5, Sprint 05) ────────────────────────────────


class RegenerateRequest(BaseModel):
    message_id: str
    """The assistant message ID to regenerate from."""


class EditRequest(BaseModel):
    message_id: str
    """The user message ID to edit."""
    content: str
    """Replacement message content."""


class BranchResponse(BaseModel):
    status: str = "started"
    session_id: str


@router.post("/{session_id}/regenerate", response_model=BranchResponse, status_code=202)
async def regenerate_response(
    session_id: str,
    body: RegenerateRequest,
    _token: None = Depends(require_gateway_token),
) -> BranchResponse:
    """Deactivate *message_id* and all later messages, then re-run the turn loop.

    The turn runs asynchronously; the response is returned immediately with
    ``status="started"``.  Subscribe to the session's WebSocket stream for the
    new assistant response.
    """
    from app.exceptions import NotFoundError, ValidationError
    from fastapi import HTTPException
    import asyncio

    session = await get_session_store().get_by_id(session_id)

    from app.sessions.branching import regenerate
    # TD-162: Validate before create_task so errors propagate to caller
    try:
        from app.sessions.messages import get_message_store
        msg_store = get_message_store()
        msg = await msg_store.get(body.message_id)
        if msg is None:
            raise NotFoundError(f"Message {body.message_id} not found")
    except (NotFoundError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # TD-326: Track task reference
    from app.api.tasks import track_task
    track_task(
        regenerate(
            session_id=session_id,
            session_key=session.session_key,
            message_id=body.message_id,
        )
    )
    return BranchResponse(status="started", session_id=session_id)


# ── Export (§13.4) ────────────────────────────────────────────────────────────


@router.get(
    "/{session_id}/export",
    dependencies=[Depends(require_gateway_token)],
)
async def export_session(
    session_id: str,
    format: Literal["markdown", "json", "pdf"] = Query(default="markdown"),
    include_tool_calls: bool = Query(default=False),
    include_system_messages: bool = Query(default=False),
    include_costs: bool = Query(default=False),
) -> Response:
    """Export session transcript as Markdown, JSON, or PDF (§13.4)."""
    from app.sessions.export import ExportOptions, SessionExporter
    from app.sessions.messages import get_message_store

    opts = ExportOptions(
        include_tool_calls=include_tool_calls,
        include_system_messages=include_system_messages,
        include_costs=include_costs,
    )
    exporter = SessionExporter(get_session_store(), get_message_store())

    if format == "json":
        data = await exporter.export_json(session_id, opts)
        import json as _json
        return Response(content=_json.dumps(data, indent=2), media_type="application/json")
    elif format == "pdf":
        pdf_bytes = await exporter.export_pdf(session_id, opts)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=\"session_{session_id}.pdf\""},
        )
    else:
        md = await exporter.export_markdown(session_id, opts)
        return Response(content=md, media_type="text/markdown")

@router.post("/{session_id}/edit", response_model=BranchResponse, status_code=202)
async def edit_and_resubmit(
    session_id: str,
    body: EditRequest,
    _token: None = Depends(require_gateway_token),
) -> BranchResponse:
    """Edit a user message and resubmit the conversation from that point.

    Deactivates *message_id* and all later messages, then starts a new turn
    with *content* as the edited user message.
    """
    from app.exceptions import NotFoundError, ValidationError
    from fastapi import HTTPException
    import asyncio

    session = await get_session_store().get_by_id(session_id)

    from app.sessions.branching import edit_and_resubmit as _edit
    # TD-162: Validate before create_task so errors propagate to caller
    try:
        from app.sessions.messages import get_message_store
        msg_store = get_message_store()
        msg = await msg_store.get(body.message_id)
        if msg is None:
            raise NotFoundError(f"Message {body.message_id} not found")
    except (NotFoundError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # TD-326: Track task reference
    from app.api.tasks import track_task
    track_task(
        _edit(
            session_id=session_id,
            session_key=session.session_key,
            message_id=body.message_id,
            new_content=body.content,
        )
    )
    return BranchResponse(status="started", session_id=session_id)
