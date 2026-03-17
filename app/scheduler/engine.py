"""Scheduler engine for Tequila v2 (§7.1, §7.3, §20.8).

The ``SchedulerEngine`` is a singleton that:
1. Loads all enabled ``ScheduledTask`` rows from the DB at startup.
2. Runs an asyncio background loop that checks every 30 seconds whether any tasks
   are due (next_run_at ≤ now).
3. For each due task, creates a cron session (``kind="cron"``) and injects the
   prompt template as the first user message.
4. Enforces the §20.8 turn-contention rule: if the target agent's session is
   currently in-turn, defer up to 60 s, then skip and log ``scheduler.skipped``.
5. After each run, computes and stores the next_run_at via the cron parser.

Usage::

    engine = await init_scheduler(db)
    await engine.start()
    # ... serve requests ...
    await engine.stop()
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

import aiosqlite

from app.scheduler.cronparser import next_run, validate_cron
from app.scheduler.models import ScheduledTask
from app.scheduler.store import (
    load_enabled_tasks,
    update_next_run,
    update_task_run,
)

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 30    # check for due tasks every 30 s
_DEFER_INTERVAL_S = 10   # retry interval when a turn is in-flight
_DEFER_MAX_S = 60        # give up deferring after this long

# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: SchedulerEngine | None = None


def get_scheduler() -> SchedulerEngine:
    if _engine is None:
        raise RuntimeError("SchedulerEngine not initialised — call init_scheduler() first")
    return _engine


async def init_scheduler(db: aiosqlite.Connection) -> SchedulerEngine:
    global _engine  # noqa: PLW0603
    _engine = SchedulerEngine(db)
    await _engine._seed_next_runs()
    return _engine


# ── Engine ────────────────────────────────────────────────────────────────────


class SchedulerEngine:
    """Asyncio-based cron scheduler for Tequila v2."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db
        self._task: asyncio.Task[None] | None = None
        self._running = False

    # ── Public lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="scheduler_loop")
        logger.info("SchedulerEngine started.")

    async def stop(self) -> None:
        """Cancel the background loop gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SchedulerEngine stopped.")

    async def trigger_now(self, task: ScheduledTask, override_prompt: str | None = None) -> str:
        """Immediately fire a task and return the new session_key."""
        session_key = await self._fire_task(task, override_prompt=override_prompt)
        return session_key

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _seed_next_runs(self) -> None:
        """Compute next_run_at for all enabled tasks that don't have one."""
        tasks = await load_enabled_tasks(self._db)
        now = datetime.now(tz=timezone.utc)
        for t in tasks:
            if t.next_run_at is None:
                try:
                    nxt = next_run(t.cron_expression, after=now)
                    await update_next_run(t.id, nxt, self._db)
                except Exception as exc:
                    logger.warning("Cannot compute next_run for task %s: %s", t.id, exc)

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except Exception as exc:
                logger.error("Scheduler tick error: %s", exc, exc_info=True)
            await asyncio.sleep(_POLL_INTERVAL_S)

    async def _tick(self) -> None:
        """Check all enabled tasks and fire any that are due."""
        tasks = await load_enabled_tasks(self._db)
        now = datetime.now(tz=timezone.utc)
        for task in tasks:
            if task.next_run_at is None:
                continue
            # Make next_run_at timezone-aware for comparison
            nra = task.next_run_at
            if nra.tzinfo is None:
                nra = nra.replace(tzinfo=timezone.utc)
            if nra <= now:
                # TD-211: Update next_run_at BEFORE firing to prevent duplicate execution
                try:
                    nxt = next_run(task.cron_expression, after=now)
                    await update_next_run(task.id, nxt, self._db)
                except Exception as exc:
                    logger.warning("Cannot pre-compute next_run for task %s: %s", task.id, exc)
                asyncio.create_task(self._run_task_with_deferral(task))

    async def _run_task_with_deferral(self, task: ScheduledTask) -> None:
        """Fire the task, deferring if a turn is in-flight (§20.8)."""
        deferred = 0
        while deferred < _DEFER_MAX_S:
            if not self._is_turn_active(task.agent_id):
                break
            logger.debug(
                "Scheduler deferred task %s (agent turn active), retry in %ds",
                task.id, _DEFER_INTERVAL_S,
            )
            await asyncio.sleep(_DEFER_INTERVAL_S)
            deferred += _DEFER_INTERVAL_S

        if deferred >= _DEFER_MAX_S and self._is_turn_active(task.agent_id):
            logger.warning(
                "Scheduler skipping task %s after %ds deferral — turn still active",
                task.id, _DEFER_MAX_S,
            )
            await self._emit_skipped(task)
            await update_task_run(task.id, status="skipped", error="Turn contention — skipped after 60 s", db=self._db)
        else:
            try:
                await self._fire_task(task)
                await update_task_run(task.id, status="success", error=None, db=self._db)
            except Exception as exc:
                logger.error("Scheduler task %s failed: %s", task.id, exc, exc_info=True)
                await update_task_run(task.id, status="error", error=str(exc), db=self._db)

        # next_run_at already updated optimistically in _tick(); no re-computation needed

    async def _fire_task(self, task: ScheduledTask, override_prompt: str | None = None) -> str:
        """Create a cron session and inject the prompt."""
        from app.sessions.store import get_session_store
        from app.gateway.router import get_router
        from app.gateway.events import GatewayEvent, EventSource, ET

        session_store = get_session_store()
        session_key = f"cron:{task.id}:{uuid.uuid4().hex[:8]}"

        # Create the ephemeral cron session
        await session_store.create(
            session_key=session_key,
            agent_id=task.agent_id,
            kind="cron",
            title=f"[Scheduled] {task.name}",
        )
        logger.info(
            "Scheduler fired task %r → session %s", task.name, session_key,
            extra={"task_id": task.id, "agent_id": task.agent_id},
        )

        # Build prompt (substitutions)
        now_dt = datetime.now(tz=timezone.utc)
        prompt = override_prompt or task.prompt_template
        prompt = prompt.replace("{now}", now_dt.isoformat(timespec="seconds"))
        prompt = prompt.replace("{date}", now_dt.strftime("%Y-%m-%d"))
        prompt = prompt.replace("{time}", now_dt.strftime("%H:%M"))

        if prompt:
            router = get_router()
            event = GatewayEvent(
                event_type=ET.INBOUND_MESSAGE,
                session_key=session_key,
                payload={"session_id": session_key, "content": prompt, "role": "user"},
                source=EventSource(kind="scheduler", id=task.id),
            )
            await router.emit(event)

        return session_key

    def _is_turn_active(self, agent_id: str) -> bool:
        """Return True if the given agent currently has an active turn (§20.8)."""
        try:
            from app.sessions.store import is_agent_turn_active
            return is_agent_turn_active(agent_id)
        except Exception:
            return False  # If we can't check, don't block

    async def _emit_skipped(self, task: ScheduledTask) -> None:
        """Emit a scheduler.skipped event on the gateway."""
        try:
            from app.gateway.router import get_router
            from app.gateway.events import GatewayEvent, EventSource, ET
            event = GatewayEvent(
                event_type=ET.SCHEDULER_SKIPPED,
                session_key="",
                payload={"task_id": task.id, "task_name": task.name},
                source=EventSource(kind="scheduler", id=task.id),
            )
            await get_router().emit(event)
        except Exception as exc:
            logger.debug("Could not emit scheduler.skipped: %s", exc)
