"""REST endpoints for the auto-update service (Sprint 16 §29.5 D6).

Routes
------
GET  /api/update/status   — return current state (no network call)
POST /api/update/check    — query GitHub for a new release
POST /api/update/download — begin background download
POST /api/update/apply    — launch installer and exit
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.update.models import UpdateState
from app.update.service import get_update_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/update", tags=["update"])


@router.get("/status", response_model=UpdateState)
async def get_status() -> UpdateState:
    """Return the current update state without making any network calls."""
    try:
        return get_update_service().get_state()
    except RuntimeError:
        # Service not initialised (test / dev mode) → return idle defaults.
        return UpdateState()


@router.post("/check", response_model=UpdateState)
async def check_for_update() -> UpdateState:
    """Query GitHub Releases and return the updated state."""
    try:
        svc = get_update_service()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Update service not available.")
    return await svc.check()


@router.post("/download", response_model=UpdateState)
async def download_update() -> UpdateState:
    """Begin downloading the latest installer.

    Returns immediately with status ``downloading``; poll ``/status`` for
    progress updates.
    """
    try:
        svc = get_update_service()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Update service not available.")
    state = svc.get_state()
    if state.status not in ("available", "ready"):
        raise HTTPException(
            status_code=409,
            detail=f"No update available to download (status={state.status}).",
        )
    import asyncio
    asyncio.create_task(svc.download(), name="update-download")
    state.status = "downloading"
    return state


@router.post("/apply")
async def apply_update() -> dict[str, bool]:
    """Launch the installer and exit the running server process.

    This endpoint will *not* return a normal response — the process exits.
    """
    try:
        svc = get_update_service()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Update service not available.")
    state = svc.get_state()
    if state.status != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"No installer ready to apply (status={state.status}).",
        )
    try:
        await svc.apply()
    except (RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True}
