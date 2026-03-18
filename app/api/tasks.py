"""TD-326: Background task tracker — prevents fire-and-forget warnings.

All ``asyncio.create_task`` calls that are intentionally "fire and forget"
should go through ``track_task()`` so that:

1. The task reference is held until it completes (no GC).
2. Unhandled exceptions are logged, not silently swallowed.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Coroutine

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task[Any]] = set()


def track_task(coro: Coroutine[Any, Any, Any], *, name: str | None = None) -> asyncio.Task[Any]:
    """Create an asyncio task, keep a reference, and log exceptions on completion."""
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_task_done)
    return task


def _task_done(task: asyncio.Task[Any]) -> None:
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "Background task %r raised: %s",
            task.get_name(),
            exc,
            exc_info=exc,
        )
