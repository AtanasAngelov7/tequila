"""Backup REST API (§26.1–26.6, Sprint 14b D5).

Routes:
  GET    /api/backup/list       — list backup files
  POST   /api/backup/create     — trigger a new backup
  POST   /api/backup/restore    — restore from uploaded archive
  GET    /api/backup/config     — get schedule/retention config
  PATCH  /api/backup/config     — update config
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.api.deps import require_gateway_token
from app.backup import BackupConfig, BackupInfo, get_backup_manager

router = APIRouter(prefix="/api/backup", tags=["backup"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class BackupConfigIn(BaseModel):
    enabled: bool | None = None
    schedule_cron: str | None = None
    retention_count: int | None = None
    backup_dir: str | None = None


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get(
    "/list",
    response_model=list[BackupInfo],
    dependencies=[Depends(require_gateway_token)],
)
async def list_backups() -> list[BackupInfo]:
    mgr = get_backup_manager()
    return await mgr.list_backups()


@router.post("/create", dependencies=[Depends(require_gateway_token)])
async def create_backup() -> dict[str, Any]:
    mgr = get_backup_manager()
    path = await mgr.create_backup()
    return {
        "status": "created",
        "filename": path.name,
        "path": str(path),
    }


@router.post("/restore", dependencies=[Depends(require_gateway_token)])
async def restore_backup(file: UploadFile) -> dict[str, Any]:
    """Restore from an uploaded backup archive."""
    mgr = get_backup_manager()

    # Save upload to a temp file
    suffix = Path(file.filename or "backup.tar.gz").suffix if file.filename else ".tar.gz"
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        # TD-165: Use asyncio.to_thread to avoid blocking the event loop
        import asyncio
        await asyncio.to_thread(shutil.copyfileobj, file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        result = await mgr.restore_backup(tmp_path)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        tmp_path.unlink(missing_ok=True)

    return result


@router.get(
    "/config",
    response_model=BackupConfig,
    dependencies=[Depends(require_gateway_token)],
)
async def get_config() -> BackupConfig:
    mgr = get_backup_manager()
    return await mgr.get_config()


@router.patch(
    "/config",
    response_model=BackupConfig,
    dependencies=[Depends(require_gateway_token)],
)
async def update_config(body: BackupConfigIn) -> BackupConfig:
    mgr = get_backup_manager()
    current = await mgr.get_config()

    updates = body.model_dump(exclude_none=True)
    merged = current.model_copy(update=updates)
    return await mgr.set_config(merged)
