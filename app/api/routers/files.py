"""File management REST API (§21.6, §21.7, Sprint 15).

Routes:
  GET    /api/files/stats                    — storage statistics
  POST   /api/files/cleanup                  — trigger manual cleanup pass
  GET    /api/sessions/{id}/files            — list files for a session
  GET    /api/files/{file_id}/download       — download file with Content-Disposition
  GET    /api/files/{file_id}/preview        — thumbnail or first-page render
  POST   /api/files/{file_id}/pin            — pin file (exempt from cleanup)
  DELETE /api/files/{file_id}/pin            — unpin file
  POST   /api/files/{file_id}/open           — open file with OS default app
  POST   /api/files/{file_id}/reveal         — reveal file in file manager
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app.api.deps import get_db_dep, require_gateway_token
from app.exceptions import NotFoundError, ValidationError
from app.files.cleanup import get_file_cleanup_service
from app.files.export import FileExportService
from app.files.models import FileCard, FileStorageStats, SessionFileEntry
from app.files.store import get_file_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["files"])
sessions_files_router = APIRouter(prefix="/api", tags=["files"])


# ── Response schemas ──────────────────────────────────────────────────────────


class SessionFilesResponse(BaseModel):
    """Response for GET /api/sessions/{id}/files."""

    files: list[SessionFileEntry]
    """All non-deleted files for the session, filtered and sorted."""

    total: int
    """Total count (before any pagination — full list returned)."""


class FileActionResponse(BaseModel):
    """Response for open/reveal actions."""

    status: Literal["ok"] = "ok"


# ── Storage stats & cleanup ───────────────────────────────────────────────────


@router.get(
    "/files/stats",
    response_model=FileStorageStats,
    dependencies=[Depends(require_gateway_token)],
)
async def get_file_stats() -> FileStorageStats:
    """Return current storage statistics (§21.7)."""
    store = get_file_store()
    try:
        cleanup_svc = get_file_cleanup_service()
        quota_mb = cleanup_svc._config.max_storage_mb  # noqa: SLF001
    except RuntimeError:
        quota_mb = 5000
    return await store.get_storage_stats(quota_mb)


@router.post(
    "/files/cleanup",
    response_model=FileStorageStats,
    dependencies=[Depends(require_gateway_token)],
)
async def trigger_cleanup() -> FileStorageStats:
    """Trigger a manual cleanup pass (§21.7)."""
    try:
        svc = get_file_cleanup_service()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FileCleanupService not available.",
        ) from exc
    return await svc.run_once()


# ── Session files list ────────────────────────────────────────────────────────


@sessions_files_router.get(
    "/sessions/{session_id}/files",
    response_model=SessionFilesResponse,
    dependencies=[Depends(require_gateway_token)],
)
async def list_session_files(
    session_id: str,
    origin: str | None = None,
    mime_category: str | None = None,
    sort: str = "date",
) -> SessionFilesResponse:
    """List all files associated with a session (§9.2b).

    Query params:
    - ``origin``: ``upload`` | ``agent_generated``
    - ``mime_category``: ``image`` | ``document`` | ``audio`` | ``other``
    - ``sort``: ``date`` (default) | ``name`` | ``size``
    """
    _valid_origins = {"upload", "agent_generated", None}
    _valid_mime_categories = {"image", "document", "audio", "other", None}
    _valid_sorts = {"date", "name", "size"}

    if origin not in _valid_origins:
        raise HTTPException(status_code=422, detail=f"Invalid origin: {origin!r}")
    if mime_category not in _valid_mime_categories:
        raise HTTPException(status_code=422, detail=f"Invalid mime_category: {mime_category!r}")
    if sort not in _valid_sorts:
        raise HTTPException(status_code=422, detail=f"Invalid sort: {sort!r}")

    store = get_file_store()
    try:
        files = await store.list_session_files(
            session_id=session_id,
            origin=origin,  # type: ignore[arg-type]
            mime_category=mime_category,  # type: ignore[arg-type]
            sort=sort,  # type: ignore[arg-type]
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("list_session_files error for session %s: %s", session_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not list session files.") from exc

    return SessionFilesResponse(files=files, total=len(files))


# ── Download & preview ────────────────────────────────────────────────────────


@router.get(
    "/files/{file_id}/download",
    dependencies=[Depends(require_gateway_token)],
)
async def download_file(file_id: str) -> FileResponse:
    """Download a file with ``Content-Disposition: attachment`` (§21.6)."""
    store = get_file_store()
    export_svc = FileExportService(store)
    try:
        path, mime_type, filename = await export_svc.get_download_info(file_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return FileResponse(
        path=str(path),
        media_type=mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get(
    "/files/{file_id}/preview",
    dependencies=[Depends(require_gateway_token)],
)
async def preview_file(file_id: str) -> Response:
    """Return a thumbnail or first-page preview (§21.6).

    Returns 404 if the file has no preview, 204 if preview generation returns None.
    """
    store = get_file_store()
    export_svc = FileExportService(store)
    try:
        result = await export_svc.get_preview(file_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=404, detail="Preview not available for this file type.")

    data, content_type = result
    return Response(content=data, media_type=content_type)


# ── Pin / unpin ───────────────────────────────────────────────────────────────


@router.post(
    "/files/{file_id}/pin",
    response_model=FileCard,
    dependencies=[Depends(require_gateway_token)],
)
async def pin_file(file_id: str) -> FileCard:
    """Pin a file to exempt it from cleanup (§21.7)."""
    store = get_file_store()
    try:
        record = await store.pin(file_id, pinned=True)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    export_svc = FileExportService(store)
    return await export_svc.to_file_card(record)


@router.delete(
    "/files/{file_id}/pin",
    response_model=FileCard,
    dependencies=[Depends(require_gateway_token)],
)
async def unpin_file(file_id: str) -> FileCard:
    """Remove the pin from a file (§21.7)."""
    store = get_file_store()
    try:
        record = await store.pin(file_id, pinned=False)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    export_svc = FileExportService(store)
    return await export_svc.to_file_card(record)


# ── OS-level actions (local-only) ─────────────────────────────────────────────


@router.post(
    "/files/{file_id}/open",
    response_model=FileActionResponse,
    dependencies=[Depends(require_gateway_token)],
)
async def open_file(file_id: str) -> FileActionResponse:
    """Open the file with the OS default application (§21.6).

    Only meaningful when the API is accessed locally (always true for Tequila).
    """
    store = get_file_store()
    export_svc = FileExportService(store)
    try:
        await export_svc.open_file(file_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning("open_file error for %s: %s", file_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not open file.") from exc
    return FileActionResponse()


@router.post(
    "/files/{file_id}/reveal",
    response_model=FileActionResponse,
    dependencies=[Depends(require_gateway_token)],
)
async def reveal_file(file_id: str) -> FileActionResponse:
    """Reveal the file in the OS file manager (§21.6)."""
    store = get_file_store()
    export_svc = FileExportService(store)
    try:
        await export_svc.reveal_file(file_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning("reveal_file error for %s: %s", file_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not reveal file.") from exc
    return FileActionResponse()
