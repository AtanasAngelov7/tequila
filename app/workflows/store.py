"""Workflow database store — CRUD for workflow definitions and runs (§10.3, Sprint 08)."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

import aiosqlite

from app.db.connection import write_transaction
from app.db.schema import row_to_dict
from app.exceptions import NotFoundError
from app.workflows.models import Workflow, WorkflowRun, WorkflowStep

logger = logging.getLogger(__name__)


# ── WorkflowStore ──────────────────────────────────────────────────────────────


class WorkflowStore:
    """Database operations for the ``workflows`` and ``workflow_runs`` tables."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # ── Workflow CRUD ──────────────────────────────────────────────────────────

    async def create_workflow(
        self,
        *,
        name: str,
        description: str = "",
        mode: str = "pipeline",
        steps: list[WorkflowStep] | None = None,
    ) -> Workflow:
        """Create and persist a new workflow definition."""
        now = datetime.now(timezone.utc).isoformat()
        wf_id = str(uuid.uuid4())
        steps_data = [s.model_dump() for s in (steps or [])]

        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT INTO workflows (id, name, description, mode, steps_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (wf_id, name, description, mode, json.dumps(steps_data), now, now),
            )

        return await self.get_workflow(wf_id)

    async def get_workflow(self, workflow_id: str) -> Workflow:
        """Return the workflow with *workflow_id* or raise ``NotFoundError``."""
        async with self._db.execute(
            "SELECT id, name, description, mode, steps_json, created_at, updated_at "
            "FROM workflows WHERE id = ?",
            (workflow_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise NotFoundError(resource="Workflow", id=workflow_id)
        return Workflow.from_row(row_to_dict(row))

    async def list_workflows(self, *, limit: int = 50, offset: int = 0) -> list[Workflow]:
        """Return all workflows ordered by creation time descending."""
        async with self._db.execute(
            "SELECT id, name, description, mode, steps_json, created_at, updated_at "
            "FROM workflows ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cur:
            rows = await cur.fetchall()
        return [Workflow.from_row(row_to_dict(r)) for r in rows]

    async def count_workflows(self) -> int:
        """Return the total number of workflow definitions in the DB (TD-72)."""
        async with self._db.execute("SELECT COUNT(*) FROM workflows") as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

    async def count_runs(self, workflow_id: str) -> int:
        """Return the total number of runs for *workflow_id* (TD-72)."""
        async with self._db.execute(
            "SELECT COUNT(*) FROM workflow_runs WHERE workflow_id = ?", (workflow_id,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

    async def update_workflow(
        self,
        workflow_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        mode: str | None = None,
        steps: list[WorkflowStep] | None = None,
    ) -> Workflow:
        """Update mutable fields on an existing workflow."""
        existing = await self.get_workflow(workflow_id)
        now = datetime.now(timezone.utc).isoformat()

        new_name = name if name is not None else existing.name
        new_desc = description if description is not None else existing.description
        new_mode = mode if mode is not None else existing.mode
        new_steps = steps if steps is not None else existing.steps
        steps_json = json.dumps([s.model_dump() for s in new_steps])

        async with write_transaction(self._db):
            await self._db.execute(
                """
                UPDATE workflows
                SET name = ?, description = ?, mode = ?, steps_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_name, new_desc, new_mode, steps_json, now, workflow_id),
            )

        return await self.get_workflow(workflow_id)

    async def delete_workflow(self, workflow_id: str) -> None:
        """Delete a workflow definition (and any associated runs)."""
        await self.get_workflow(workflow_id)  # raises NotFoundError if missing
        async with write_transaction(self._db):
            await self._db.execute(
                "DELETE FROM workflow_runs WHERE workflow_id = ?", (workflow_id,)
            )
            await self._db.execute(
                "DELETE FROM workflows WHERE id = ?", (workflow_id,)
            )

    # ── WorkflowRun CRUD ───────────────────────────────────────────────────────

    async def create_run(self, workflow_id: str) -> WorkflowRun:
        """Create a new pending run for *workflow_id*."""
        now = datetime.now(timezone.utc).isoformat()
        run_id = str(uuid.uuid4())
        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT INTO workflow_runs
                    (id, workflow_id, status, step_results_json, current_step,
                     error, started_at, completed_at, created_at)
                VALUES (?, ?, 'pending', '{}', NULL, NULL, NULL, NULL, ?)
                """,
                (run_id, workflow_id, now),
            )
        return await self.get_run(run_id)

    async def get_run(self, run_id: str) -> WorkflowRun:
        """Return the run with *run_id* or raise ``NotFoundError``."""
        async with self._db.execute(
            """
            SELECT id, workflow_id, status, step_results_json, current_step,
                   error, started_at, completed_at, created_at
            FROM workflow_runs WHERE id = ?
            """,
            (run_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise NotFoundError(resource="WorkflowRun", id=run_id)
        return WorkflowRun.from_row(row_to_dict(row))

    async def list_runs(
        self, workflow_id: str, *, limit: int = 20, offset: int = 0
    ) -> list[WorkflowRun]:
        """Return runs for *workflow_id* ordered most-recent first."""
        async with self._db.execute(
            """
            SELECT id, workflow_id, status, step_results_json, current_step,
                   error, started_at, completed_at, created_at
            FROM workflow_runs
            WHERE workflow_id = ?
            ORDER BY created_at DESC LIMIT ? OFFSET ?
            """,
            (workflow_id, limit, offset),
        ) as cur:
            rows = await cur.fetchall()
        return [WorkflowRun.from_row(row_to_dict(r)) for r in rows]

    async def update_run_status(
        self,
        run_id: str,
        *,
        status: str,
        current_step: str | None = None,
        step_results: dict[str, str] | None = None,
        error: str | None = None,
    ) -> WorkflowRun:
        """Update run status, progress, and results in one write.

        If the run is already in a terminal state (``completed``, ``failed``,
        ``cancelled``) the write is skipped to avoid overwriting the terminal
        status — implementing an optimistic concurrency guard (TD-59).
        """
        now = datetime.now(timezone.utc).isoformat()
        run = await self.get_run(run_id)

        _TERMINAL = frozenset({"completed", "failed", "cancelled"})
        if run.status in _TERMINAL and status not in _TERMINAL:
            # Non-terminal transition rejected — return current state unchanged
            logger.debug(
                "update_run_status: run %s is already %r; ignoring transition to %r",
                run_id, run.status, status,
            )
            return run

        merged_results = dict(run.step_results)
        if step_results:
            merged_results.update(step_results)

        started_at = run.started_at.isoformat() if run.started_at else None
        completed_at = run.completed_at.isoformat() if run.completed_at else None

        if status == "running" and run.started_at is None:
            started_at = now
        if status in ("completed", "failed", "cancelled"):
            completed_at = now

        async with write_transaction(self._db):
            await self._db.execute(
                """
                UPDATE workflow_runs
                SET status = ?, current_step = ?, step_results_json = ?,
                    error = ?, started_at = ?, completed_at = ?
                WHERE id = ? AND status NOT IN ('completed', 'failed', 'cancelled')
                """,
                (
                    status,
                    current_step if current_step is not None else run.current_step,
                    json.dumps(merged_results),
                    error if error is not None else run.error,
                    started_at,
                    completed_at,
                    run_id,
                ),
            )
        return await self.get_run(run_id)


# ── Singleton ──────────────────────────────────────────────────────────────────

_store: WorkflowStore | None = None


def init_workflow_store(db: aiosqlite.Connection) -> None:
    """Initialise the process-wide WorkflowStore singleton."""
    global _store
    _store = WorkflowStore(db)
    logger.info("WorkflowStore initialised.")


def get_workflow_store() -> WorkflowStore:
    """Return the process-wide WorkflowStore singleton.

    Raises ``RuntimeError`` if ``init_workflow_store()`` has not been called.
    """
    if _store is None:
        raise RuntimeError("WorkflowStore not initialised — call init_workflow_store() first")
    return _store
