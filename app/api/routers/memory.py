"""Memory API — CRUD for structured memory records (§5.3, §5.9, Sprints 09-11).

Endpoints
---------
GET    /api/memory                  — list memories (with filters)
POST   /api/memory                  — create memory
GET    /api/memory/{id}             — get memory
PATCH  /api/memory/{id}             — update memory
DELETE /api/memory/{id}             — delete memory
POST   /api/memory/reindex          — trigger full embedding reindex
GET    /api/memory/{id}/history     — audit event timeline for a memory (Sprint 11)
GET    /api/memory-events           — global memory-event feed (Sprint 11)
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import require_gateway_token
from app.knowledge.embeddings import get_embedding_store
from app.memory.models import MEMORY_SCOPES, MEMORY_STATUSES, MEMORY_TYPES, SOURCE_TYPES, MemoryExtract
from app.memory.store import get_memory_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/memory",
    tags=["memory"],
    dependencies=[Depends(require_gateway_token)],
)


# ── Request/response models ───────────────────────────────────────────────────


class MemoryCreateRequest(BaseModel):
    content: str
    memory_type: MEMORY_TYPES
    always_recall: bool | None = None
    recall_weight: float | None = None
    pinned: bool = False
    expires_at: str | None = None
    source_type: SOURCE_TYPES = "user_created"
    source_session_id: str | None = None
    source_message_id: str | None = None
    confidence: float = 1.0
    entity_ids: list[str] = []
    tags: list[str] = []
    scope: MEMORY_SCOPES = "global"
    agent_id: str | None = None


class MemoryUpdateRequest(BaseModel):
    content: str | None = None
    pinned: bool | None = None
    recall_weight: float | None = None
    tags: list[str] | None = None
    entity_ids: list[str] | None = None
    status: MEMORY_STATUSES | None = None
    decay_score: float | None = None
    confidence: float | None = None


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[dict])
async def list_memories(
    memory_type: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    status: str = Query(default="active"),
    always_recall_only: bool = Query(default=False),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """List memory records with optional filters."""
    store = get_memory_store()
    memories = await store.list(
        memory_type=memory_type,
        scope=scope,
        agent_id=agent_id,
        status=status,
        always_recall_only=always_recall_only,
        search=search,
        limit=limit,
        offset=offset,
    )
    return [_mem_dict(m) for m in memories]


@router.post("", response_model=dict, status_code=201)
async def create_memory(body: MemoryCreateRequest) -> dict:
    """Create a new memory record."""
    from datetime import datetime

    store = get_memory_store()
    expires_at = None
    if body.expires_at:
        try:
            expires_dt = body.expires_at
            if expires_dt.endswith("Z"):
                expires_dt = expires_dt[:-1] + "+00:00"
            expires_at = datetime.fromisoformat(expires_dt)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid expires_at format: {body.expires_at!r}. Expected ISO 8601 datetime.",
            )

    mem = await store.create(
        content=body.content,
        memory_type=body.memory_type,
        always_recall=body.always_recall,
        recall_weight=body.recall_weight,
        pinned=body.pinned,
        expires_at=expires_at,
        source_type=body.source_type,
        source_session_id=body.source_session_id,
        source_message_id=body.source_message_id,
        confidence=body.confidence,
        entity_ids=body.entity_ids,
        tags=body.tags,
        scope=body.scope,
        agent_id=body.agent_id,
    )
    return _mem_dict(mem)


@router.get("/{memory_id}", response_model=dict)
async def get_memory(memory_id: str) -> dict:
    """Return a single memory record by ID."""
    store = get_memory_store()
    mem = await store.get(memory_id)
    return _mem_dict(mem)


@router.patch("/{memory_id}", response_model=dict)
async def update_memory(memory_id: str, body: MemoryUpdateRequest) -> dict:
    """Update selected fields on a memory record."""
    store = get_memory_store()
    mem = await store.update(
        memory_id,
        content=body.content,
        pinned=body.pinned,
        recall_weight=body.recall_weight,
        tags=body.tags,
        entity_ids=body.entity_ids,
        status=body.status,
        decay_score=body.decay_score,
        confidence=body.confidence,
    )
    return _mem_dict(mem)


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(memory_id: str) -> None:
    """Hard-delete a memory record."""
    store = get_memory_store()
    await store.delete(memory_id)


@router.post("/reindex", response_model=dict)
async def reindex_embeddings(
    source_type: str | None = Query(default=None, description="'memory', 'note', 'entity', or all if omitted"),
) -> dict:
    """Trigger a full embedding reindex for memory, note, and/or entity records."""
    emb = get_embedding_store()
    result = await emb.reindex(source_type=source_type)
    return {
        "total": result.total,
        "updated": result.updated,
        "errors": result.errors,
        "duration_ms": result.duration_ms,
    }


# ── Sprint 11: Audit history endpoints ───────────────────────────────────────

@router.get("/{memory_id}/history", response_model=list[dict])
async def get_memory_history(
    memory_id: str,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict]:
    """Return the audit event timeline for a specific memory (§5.9)."""
    try:
        from app.memory.audit import get_memory_audit
        audit = get_memory_audit()
        events = await audit.get_memory_history(memory_id, limit=limit)
        return [e.model_dump() for e in events]
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Audit system not initialized")


# Separate router for /api/memory-events (different prefix)
events_router = APIRouter(
    prefix="/api/memory-events",
    tags=["memory"],
    dependencies=[Depends(require_gateway_token)],
)


@events_router.get("", response_model=list[dict])
async def get_memory_events(
    event_type: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    since: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """Return the global memory-event feed with optional filters (§5.9)."""
    try:
        from app.memory.audit import get_memory_audit
        audit = get_memory_audit()
        events = await audit.get_global_feed(
            event_type=event_type,
            actor=actor,
            since=since,
            limit=limit,
            offset=offset,
        )
        return [e.model_dump() for e in events]
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Audit system not initialized")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mem_dict(mem: MemoryExtract) -> dict[str, Any]:
    return {
        "memory_id": mem.id,
        "id": mem.id,
        "content": mem.content,
        "memory_type": mem.memory_type,
        "always_recall": mem.always_recall,
        "recall_weight": mem.recall_weight,
        "pinned": mem.pinned,
        "created_at": mem.created_at.isoformat(),
        "updated_at": mem.updated_at.isoformat(),
        "last_accessed": mem.last_accessed.isoformat(),
        "access_count": mem.access_count,
        "expires_at": mem.expires_at.isoformat() if mem.expires_at else None,
        "decay_score": mem.decay_score,
        "source_type": mem.source_type,
        "source_session_id": mem.source_session_id,
        "source_message_id": mem.source_message_id,
        "confidence": mem.confidence,
        "entity_ids": mem.entity_ids,
        "tags": mem.tags,
        "scope": mem.scope,
        "agent_id": mem.agent_id,
        "status": mem.status,
        "version": mem.version,
    }
