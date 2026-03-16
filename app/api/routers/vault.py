"""Vault API — note CRUD and wiki-link graph (§5.10, Sprint 09).

Endpoints
---------
GET    /api/vault/notes                   — list notes (with optional search)
POST   /api/vault/notes                   — create note
GET    /api/vault/notes/{note_id}         — get note with content
PUT    /api/vault/notes/{note_id}         — update note
DELETE /api/vault/notes/{note_id}         — delete note
GET    /api/vault/graph                   — wiki-link graph (nodes + edges)
POST   /api/vault/sync                    — sync DB with disk (detect external edits)
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.deps import require_gateway_token
from app.knowledge.vault import VaultGraph, VaultNote, get_vault_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/vault",
    tags=["vault"],
    dependencies=[Depends(require_gateway_token)],
)


# ── Request/response models ───────────────────────────────────────────────────


class NoteCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = ""
    tags: list[str] = []


class NoteUpdateRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/notes", response_model=list[dict])
async def list_notes(
    search: str | None = Query(default=None, description="Filter by title (substring match)"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """List vault notes.  Omits full content for efficiency."""
    store = get_vault_store()
    notes = await store.list_notes(search=search, limit=limit, offset=offset)
    return [_note_dict(n) for n in notes]


@router.post("/notes", response_model=dict, status_code=201)
async def create_note(body: NoteCreateRequest) -> dict:
    """Create a new vault note."""
    store = get_vault_store()
    note = await store.create_note(
        title=body.title,
        content=body.content,
        tags=body.tags or None,
    )
    return _note_dict(note)


@router.get("/notes/{note_id}", response_model=dict)
async def get_note(note_id: str) -> dict:
    """Return note content and metadata."""
    store = get_vault_store()
    note = await store.get_note(note_id)
    return _note_dict(note)


@router.put("/notes/{note_id}", response_model=dict)
async def update_note(note_id: str, body: NoteUpdateRequest) -> dict:
    """Update note title, content, and/or tags."""
    store = get_vault_store()
    note = await store.update_note(
        note_id,
        title=body.title,
        content=body.content,
        tags=body.tags,
    )
    return _note_dict(note)


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(note_id: str) -> None:
    """Delete a vault note and its file from disk."""
    store = get_vault_store()
    await store.delete_note(note_id)


@router.get("/graph", response_model=dict)
async def get_graph() -> dict:
    """Return the wiki-link graph (nodes + edges)."""
    store = get_vault_store()
    graph = await store.get_graph()
    return {"nodes": graph.nodes, "edges": graph.edges}


@router.post("/sync", response_model=dict)
async def sync_vault() -> dict:
    """Sync the vault DB with the current state of the disk directory.

    Detects externally added/modified/deleted ``.md`` files and updates the DB.
    """
    store = get_vault_store()
    result = await store.sync_from_disk()
    return {"added": result.added, "updated": result.updated, "deleted": result.deleted}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _note_dict(note: VaultNote) -> dict:
    return {
        "note_id": note.id,
        "id": note.id,
        "title": note.title,
        "slug": note.slug,
        "filename": note.filename,
        "content": note.content,
        "content_hash": note.content_hash,
        "wikilinks": note.wikilinks,
        "tags": note.tags,
        "created_at": note.created_at.isoformat(),
        "updated_at": note.updated_at.isoformat(),
    }
