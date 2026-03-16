"""Sprint 08 — Workflow management API (§10.3).

Endpoints
---------
POST   /api/workflows                          — create workflow definition
GET    /api/workflows                          — list workflows
GET    /api/workflows/{workflow_id}            — get workflow
PUT    /api/workflows/{workflow_id}            — update workflow
DELETE /api/workflows/{workflow_id}            — delete workflow
POST   /api/workflows/{workflow_id}/run        — trigger a workflow run
GET    /api/workflows/{workflow_id}/runs       — list runs for a workflow
GET    /api/workflows/{workflow_id}/runs/{run_id}     — run detail + status
POST   /api/workflows/{workflow_id}/runs/{run_id}/cancel — cancel a running run
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import require_gateway_token
from app.exceptions import NotFoundError
from app.workflows.models import Workflow, WorkflowRun, WorkflowStep
from app.workflows.store import get_workflow_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/workflows",
    tags=["workflows"],
    dependencies=[Depends(require_gateway_token)],
)


# ── Request / Response models ─────────────────────────────────────────────────


class WorkflowStepRequest(BaseModel):
    """Step definition in a create/update request."""

    id: str | None = None
    """Step identifier.  Generated if not provided."""

    agent_id: str
    """Agent that executes this step."""

    prompt_template: str
    """Prompt sent to the agent.  Use ``{context}`` for previous step output."""

    timeout_s: int = 60
    """Timeout in seconds for this step."""

    retry: int = 0
    """How many times to retry on failure."""


class WorkflowCreateRequest(BaseModel):
    """Request body for ``POST /api/workflows``."""

    name: str
    """Human-readable workflow name."""

    description: str = ""
    """Optional description."""

    mode: str = "pipeline"
    """Execution mode: ``pipeline`` | ``parallel``."""

    steps: list[WorkflowStepRequest] = []
    """Ordered list of steps."""


class WorkflowUpdateRequest(BaseModel):
    """Request body for ``PUT /api/workflows/{workflow_id}``."""

    name: str | None = None
    description: str | None = None
    mode: str | None = None
    steps: list[WorkflowStepRequest] | None = None


def _step_from_req(req: WorkflowStepRequest) -> WorkflowStep:
    """Convert a request step model into a domain WorkflowStep."""
    import uuid
    return WorkflowStep(
        id=req.id or str(uuid.uuid4())[:8],
        agent_id=req.agent_id,
        prompt_template=req.prompt_template,
        timeout_s=req.timeout_s,
        retry=req.retry,
    )


def _workflow_dict(wf: Workflow) -> dict[str, Any]:
    d = wf.model_dump(mode="json")
    d["workflow_id"] = d["id"]  # convenience alias used by tests + clients
    return d


def _run_dict(run: WorkflowRun) -> dict[str, Any]:
    d = run.model_dump(mode="json")
    d["run_id"] = d["id"]  # convenience alias used by tests + clients
    return d


# ── Workflow CRUD ─────────────────────────────────────────────────────────────


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workflow(body: WorkflowCreateRequest) -> dict[str, Any]:
    """Create a new workflow definition."""
    if body.mode not in ("pipeline", "parallel"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="mode must be 'pipeline' or 'parallel'",
        )
    steps = [_step_from_req(s) for s in body.steps]
    store = get_workflow_store()
    wf = await store.create_workflow(
        name=body.name,
        description=body.description,
        mode=body.mode,
        steps=steps,
    )
    return _workflow_dict(wf)


@router.get("")
async def list_workflows(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List all workflow definitions."""
    store = get_workflow_store()
    workflows = await store.list_workflows(limit=limit, offset=offset)
    return {"workflows": [_workflow_dict(w) for w in workflows], "total": len(workflows)}


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str) -> dict[str, Any]:
    """Return a single workflow definition."""
    try:
        store = get_workflow_store()
        wf = await store.get_workflow(workflow_id)
        return _workflow_dict(wf)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")


@router.put("/{workflow_id}")
async def update_workflow(workflow_id: str, body: WorkflowUpdateRequest) -> dict[str, Any]:
    """Update mutable fields on an existing workflow."""
    if body.mode is not None and body.mode not in ("pipeline", "parallel"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="mode must be 'pipeline' or 'parallel'",
        )
    steps = [_step_from_req(s) for s in body.steps] if body.steps is not None else None
    try:
        store = get_workflow_store()
        wf = await store.update_workflow(
            workflow_id,
            name=body.name,
            description=body.description,
            mode=body.mode,
            steps=steps,
        )
        return _workflow_dict(wf)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: str) -> None:
    """Delete a workflow definition and all its runs."""
    try:
        store = get_workflow_store()
        await store.delete_workflow(workflow_id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")


# ── Run triggers ──────────────────────────────────────────────────────────────


@router.post("/{workflow_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def trigger_run(
    workflow_id: str,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Trigger a new workflow run.  Returns immediately; execution runs in the background."""
    try:
        store = get_workflow_store()
        wf = await store.get_workflow(workflow_id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    run = await store.create_run(workflow_id)

    async def _execute() -> None:
        from app.workflows.runtime import execute_workflow
        try:
            await execute_workflow(wf, run)
        except Exception:
            logger.exception("Workflow run %s failed unexpectedly", run.id)
            try:
                await store.update_run_status(run.id, status="failed", error="Internal error")
            except Exception:
                pass

    background_tasks.add_task(_execute)
    return _run_dict(run)


@router.get("/{workflow_id}/runs")
async def list_runs(
    workflow_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List runs for a workflow."""
    try:
        store = get_workflow_store()
        await store.get_workflow(workflow_id)  # verify workflow exists
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    runs = await store.list_runs(workflow_id, limit=limit, offset=offset)
    return {"runs": [_run_dict(r) for r in runs], "total": len(runs)}


@router.get("/{workflow_id}/runs/{run_id}")
async def get_run(workflow_id: str, run_id: str) -> dict[str, Any]:
    """Return the status and step results for a specific run."""
    try:
        store = get_workflow_store()
        run = await store.get_run(run_id)
        if run.workflow_id != workflow_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        return _run_dict(run)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")


@router.post("/{workflow_id}/runs/{run_id}/cancel")
async def cancel_run(workflow_id: str, run_id: str) -> dict[str, Any]:
    """Cancel a pending or running workflow run."""
    try:
        store = get_workflow_store()
        run = await store.get_run(run_id)
        if run.workflow_id != workflow_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        if run.status in ("completed", "failed", "cancelled"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Run is already in terminal state: {run.status}",
            )
        updated = await store.update_run_status(run_id, status="cancelled")
        return _run_dict(updated)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
