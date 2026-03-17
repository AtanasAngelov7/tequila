"""Database persistence layer for the Tequila v2 scheduler (§7.2).

All functions are async and accept an ``aiosqlite.Connection``.
Storage format follows the project conventions: ISO-8601 TEXT for
datetimes, INTEGER 0/1 for booleans, JSON TEXT for extended data.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import aiosqlite

from app.scheduler.models import ScheduledTask

logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _dt(s: str | None) -> datetime | None:
    if s is None:
        return None
    return datetime.fromisoformat(s)


def _row_to_task(row: Any) -> ScheduledTask:
    return ScheduledTask(
        id=row["id"],
        name=row["name"],
        description=row["description"] or "",
        cron_expression=row["cron_expression"],
        agent_id=row["agent_id"],
        prompt_template=row["prompt_template"] or "",
        enabled=bool(row["enabled"]),
        announce=bool(row["announce"]),
        last_run_at=_dt(row["last_run_at"]),
        last_run_status=row["last_run_status"],
        last_run_error=row["last_run_error"],
        next_run_at=_dt(row["next_run_at"]),
        run_count=int(row["run_count"]),
        created_at=_dt(row["created_at"]) or datetime.utcnow(),
        updated_at=_dt(row["updated_at"]) or datetime.utcnow(),
    )


# ── CRUD ──────────────────────────────────────────────────────────────────────


async def save_task(task: ScheduledTask, db: aiosqlite.Connection) -> None:
    """Insert or replace a scheduled task row."""
    now = datetime.utcnow().isoformat()
    await db.execute(
        """
        INSERT OR REPLACE INTO scheduled_tasks
            (id, name, description, cron_expression, agent_id, prompt_template,
             enabled, announce, last_run_at, last_run_status, last_run_error,
             next_run_at, run_count, created_at, updated_at)
        VALUES
            (?,  ?,    ?,           ?,               ?,        ?,
             ?,       ?,        ?,           ?,               ?,
             ?,           ?,         ?,          ?)
        """,
        (
            task.id,
            task.name,
            task.description,
            task.cron_expression,
            task.agent_id,
            task.prompt_template,
            1 if task.enabled else 0,
            1 if task.announce else 0,
            task.last_run_at.isoformat() if task.last_run_at else None,
            task.last_run_status,
            task.last_run_error,
            task.next_run_at.isoformat() if task.next_run_at else None,
            task.run_count,
            task.created_at.isoformat() if task.created_at else now,
            now,
        ),
    )
    await db.commit()


async def load_task(task_id: str, db: aiosqlite.Connection) -> ScheduledTask | None:
    """Return a ScheduledTask by ID, or None if not found."""
    async with db.execute(
        "SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)
    ) as cur:
        cur.row_factory = aiosqlite.Row
        row = await cur.fetchone()
    return _row_to_task(row) if row else None


async def load_all_tasks(db: aiosqlite.Connection) -> list[ScheduledTask]:
    """Return all scheduled tasks."""
    async with db.execute("SELECT * FROM scheduled_tasks ORDER BY name") as cur:
        cur.row_factory = aiosqlite.Row
        rows = await cur.fetchall()
    return [_row_to_task(r) for r in rows]


async def load_enabled_tasks(db: aiosqlite.Connection) -> list[ScheduledTask]:
    """Return only enabled tasks (used by scheduler engine)."""
    async with db.execute(
        "SELECT * FROM scheduled_tasks WHERE enabled = 1 ORDER BY next_run_at"
    ) as cur:
        cur.row_factory = aiosqlite.Row
        rows = await cur.fetchall()
    return [_row_to_task(r) for r in rows]


async def delete_task(task_id: str, db: aiosqlite.Connection) -> bool:
    """Delete a task. Return True if it existed."""
    await db.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
    await db.commit()
    return db.total_changes > 0


async def update_task_run(
    task_id: str,
    *,
    status: str,
    error: str | None,
    db: aiosqlite.Connection,
) -> None:
    """Record the outcome of an execution and increment run_count."""
    now = datetime.utcnow().isoformat()
    run_count_increment = 1 if status == "success" else 0
    await db.execute(
        """
        UPDATE scheduled_tasks
        SET last_run_at = ?,
            last_run_status = ?,
            last_run_error = ?,
            run_count = run_count + ?,
            updated_at = ?
        WHERE id = ?
        """,
        (now, status, error, run_count_increment, now, task_id),
    )
    await db.commit()


async def update_next_run(
    task_id: str,
    next_run_at: datetime | None,
    db: aiosqlite.Connection,
) -> None:
    """Store the computed next_run_at for a task."""
    await db.execute(
        "UPDATE scheduled_tasks SET next_run_at = ?, updated_at = ? WHERE id = ?",
        (
            next_run_at.isoformat() if next_run_at else None,
            datetime.utcnow().isoformat(),
            task_id,
        ),
    )
    await db.commit()
