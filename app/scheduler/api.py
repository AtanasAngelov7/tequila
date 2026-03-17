"""FastAPI router for the Tequila v2 scheduler API (§7.2).

Endpoints:
    GET    /api/scheduled-tasks            — list all tasks
    POST   /api/scheduled-tasks            — create task
    GET    /api/scheduled-tasks/{id}       — get task detail
    PATCH  /api/scheduled-tasks/{id}       — update / enable / disable
    DELETE /api/scheduled-tasks/{id}       — delete task
    POST   /api/scheduled-tasks/{id}/run   — run immediately
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_gateway_token, get_db_dep as get_db
from app.scheduler.cronparser import validate_cron, next_run
from app.scheduler.engine import get_scheduler
from app.scheduler.models import (
    CreateTaskRequest,
    ScheduledTask,
    UpdateTaskRequest,
    RunNowRequest,
)
from app.scheduler.store import (
    delete_task,
    load_all_tasks,
    load_task,
    save_task,
    update_next_run,
)

router = APIRouter(
    prefix="/api/scheduled-tasks",
    tags=["scheduler"],
    dependencies=[Depends(require_gateway_token)],
)
logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _compute_next(expr: str) -> datetime | None:
    try:
        return next_run(expr, after=datetime.now(tz=timezone.utc))
    except Exception:
        return None


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[ScheduledTask])
async def list_tasks(db=Depends(get_db)) -> list[ScheduledTask]:
    """List all scheduled tasks."""
    return await load_all_tasks(db)


@router.post("", response_model=ScheduledTask, status_code=201)
async def create_task(req: CreateTaskRequest, db=Depends(get_db)) -> ScheduledTask:
    """Create a new scheduled task."""
    if not validate_cron(req.cron_expression):
        raise HTTPException(400, f"Invalid cron expression: {req.cron_expression!r}")

    now = datetime.utcnow()
    task = ScheduledTask(
        id=str(uuid.uuid4()),
        name=req.name,
        description=req.description,
        cron_expression=req.cron_expression,
        agent_id=req.agent_id,
        prompt_template=req.prompt_template,
        enabled=req.enabled,
        announce=req.announce,
        next_run_at=_compute_next(req.cron_expression) if req.enabled else None,
        created_at=now,
        updated_at=now,
    )
    await save_task(task, db)
    return task


@router.get("/{task_id}", response_model=ScheduledTask)
async def get_task(task_id: str, db=Depends(get_db)) -> ScheduledTask:
    """Get a scheduled task by ID."""
    task = await load_task(task_id, db)
    if task is None:
        raise HTTPException(404, f"Task {task_id!r} not found")
    return task


@router.patch("/{task_id}", response_model=ScheduledTask)
async def update_task(task_id: str, req: UpdateTaskRequest, db=Depends(get_db)) -> ScheduledTask:
    """Update a scheduled task."""
    task = await load_task(task_id, db)
    if task is None:
        raise HTTPException(404, f"Task {task_id!r} not found")

    if req.cron_expression is not None and not validate_cron(req.cron_expression):
        raise HTTPException(400, f"Invalid cron expression: {req.cron_expression!r}")

    # Apply updates
    updates = req.model_dump(exclude_none=True)
    updated = task.model_copy(update=updates)
    updated.updated_at = datetime.utcnow()

    # Recompute next_run if expression or enabled status changed
    if req.cron_expression is not None or req.enabled is not None:
        if updated.enabled:
            updated.next_run_at = _compute_next(updated.cron_expression)
        else:
            updated.next_run_at = None

    await save_task(updated, db)
    return updated


@router.delete("/{task_id}", status_code=204)
async def remove_task(task_id: str, db=Depends(get_db)) -> None:
    """Delete a scheduled task."""
    task = await load_task(task_id, db)
    if task is None:
        raise HTTPException(404, f"Task {task_id!r} not found")
    await delete_task(task_id, db)


@router.post("/{task_id}/run", status_code=202)
async def run_task_now(
    task_id: str, req: RunNowRequest | None = None, db=Depends(get_db)
) -> dict:
    """Trigger a scheduled task immediately."""
    task = await load_task(task_id, db)
    if task is None:
        raise HTTPException(404, f"Task {task_id!r} not found")

    try:
        scheduler = get_scheduler()
    except RuntimeError:
        raise HTTPException(503, "Scheduler not running")

    override = req.override_prompt if req else None
    session_key = await scheduler.trigger_now(task, override_prompt=override)
    return {"session_key": session_key, "task_id": task_id}
