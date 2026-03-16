"""Entity API — CRUD and entity-memory linking (§5.4, Sprint 09).

Endpoints
---------
GET    /api/entities                        — list entities
POST   /api/entities                        — create entity
GET    /api/entities/{entity_id}            — get entity
PATCH  /api/entities/{entity_id}            — update entity
DELETE /api/entities/{entity_id}            — delete entity
POST   /api/entities/{entity_id}/aliases    — add alias
GET    /api/entities/{entity_id}/memories   — list linked memory IDs
POST   /api/entities/ner                    — extract entities from text (NER)
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.deps import require_gateway_token
from app.memory.entities import Entity, extract_entity_mentions
from app.memory.entity_store import get_entity_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/entities",
    tags=["entities"],
    dependencies=[Depends(require_gateway_token)],
)


# ── Request/response models ───────────────────────────────────────────────────


class EntityCreateRequest(BaseModel):
    name: str
    entity_type: str
    aliases: list[str] = []
    summary: str = ""
    properties: dict[str, Any] = {}


class EntityUpdateRequest(BaseModel):
    name: str | None = None
    aliases: list[str] | None = None
    summary: str | None = None
    properties: dict[str, Any] | None = None
    status: str | None = None
    merged_into: str | None = None


class AliasRequest(BaseModel):
    alias: str


class NERRequest(BaseModel):
    text: str


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[dict])
async def list_entities(
    entity_type: str | None = Query(default=None),
    status: str = Query(default="active"),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """List entities with optional filters."""
    store = get_entity_store()
    entities = await store.list(
        entity_type=entity_type,
        status=status,
        search=search,
        limit=limit,
        offset=offset,
    )
    return [_entity_dict(e) for e in entities]


@router.post("", response_model=dict, status_code=201)
async def create_entity(body: EntityCreateRequest) -> dict:
    """Create a new entity."""
    store = get_entity_store()
    entity = await store.create(
        name=body.name,
        entity_type=body.entity_type,
        aliases=body.aliases,
        summary=body.summary,
        properties=body.properties,
    )
    return _entity_dict(entity)


@router.get("/{entity_id}", response_model=dict)
async def get_entity(entity_id: str) -> dict:
    """Return a single entity by ID."""
    store = get_entity_store()
    entity = await store.get(entity_id)
    return _entity_dict(entity)


@router.patch("/{entity_id}", response_model=dict)
async def update_entity(entity_id: str, body: EntityUpdateRequest) -> dict:
    """Update selected fields on an entity."""
    store = get_entity_store()
    entity = await store.update(
        entity_id,
        name=body.name,
        aliases=body.aliases,
        summary=body.summary,
        properties=body.properties,
        status=body.status,
        merged_into=body.merged_into,
    )
    return _entity_dict(entity)


@router.delete("/{entity_id}", status_code=204)
async def delete_entity(entity_id: str) -> None:
    """Hard-delete an entity record."""
    store = get_entity_store()
    await store.delete(entity_id)


@router.post("/{entity_id}/aliases", response_model=dict)
async def add_alias(entity_id: str, body: AliasRequest) -> dict:
    """Add an alias to an entity."""
    store = get_entity_store()
    entity = await store.add_alias(entity_id, body.alias)
    return _entity_dict(entity)


@router.get("/{entity_id}/memories", response_model=dict)
async def get_entity_memories(entity_id: str) -> dict:
    """Return IDs of memories linked to *entity_id*."""
    store = get_entity_store()
    memory_ids = await store.get_memories(entity_id)
    return {"entity_id": entity_id, "memory_ids": memory_ids, "count": len(memory_ids)}


@router.post("/ner", response_model=dict)
async def run_ner(body: NERRequest) -> dict:
    """Run lightweight NER on *text* and return detected entity mentions."""
    mentions = extract_entity_mentions(body.text)
    return {"text": body.text, "mentions": mentions, "count": len(mentions)}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _entity_dict(entity: Entity) -> dict[str, Any]:
    return {
        "entity_id": entity.id,
        "id": entity.id,
        "name": entity.name,
        "entity_type": entity.entity_type,
        "aliases": entity.aliases,
        "summary": entity.summary,
        "properties": entity.properties,
        "first_seen": entity.first_seen.isoformat(),
        "last_referenced": entity.last_referenced.isoformat(),
        "reference_count": entity.reference_count,
        "status": entity.status,
        "merged_into": entity.merged_into,
        "updated_at": entity.updated_at.isoformat(),
    }
