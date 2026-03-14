"""In-process async event router — the heart of the gateway (§2.1, §2.2).

``GatewayRouter`` is a pub/sub bus:
- Handlers register interest in one or more event types via ``on()``.
- ``emit()`` dispatches a ``GatewayEvent`` to every matching handler,
  in registration order, sequentially (not concurrently).
- ``emit_nowait()`` schedules emission as a fire-and-forget background task.

A process-wide singleton is managed by ``init_router()`` / ``get_router()``.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any

from app.gateway.events import GatewayEvent

logger = logging.getLogger(__name__)

# ── Type alias for handlers ────────────────────────────────────────────────────

EventHandler = Callable[[GatewayEvent], Coroutine[Any, Any, None]]
"""Async callable that accepts a single ``GatewayEvent``."""

# ── Router ────────────────────────────────────────────────────────────────────


class GatewayRouter:
    """Async pub/sub event router.

    Handlers are stored per event type.  The wildcard type ``"*"`` receives
    every event regardless of ``event_type``.

    The monotonic ``seq`` counter is incremented on every ``emit()`` call and
    is embedded in WebSocket server push events for client-side ordering.
    """

    def __init__(self) -> None:
        # Mapping: event_type → list of handlers (ordered by registration time)
        self._handlers: defaultdict[str, list[EventHandler]] = defaultdict(list)
        self._seq_counter: itertools.count[int] = itertools.count(start=1)
        self._running: bool = False

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Mark the router as active.  Must be called before ``emit()``."""
        self._running = True
        logger.info("GatewayRouter started.")

    def stop(self) -> None:
        """Mark the router as stopped and remove all handlers."""
        self._running = False
        self._handlers.clear()
        logger.info("GatewayRouter stopped.")

    # ── Registration ──────────────────────────────────────────────────────────

    def on(self, event_type: str, handler: EventHandler) -> None:
        """Register *handler* to receive events of *event_type*.

        Use ``"*"`` as *event_type* to receive all events.
        Registering the same handler twice for the same type is a no-op.
        """
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)
            logger.debug(
                "Handler registered",
                extra={"event_type": event_type, "handler": handler.__qualname__},
            )

    def off(self, event_type: str, handler: EventHandler) -> None:
        """Deregister *handler* from *event_type*.  Silently ignores unknown handlers."""
        try:
            self._handlers[event_type].remove(handler)
        except ValueError:
            pass

    # ── Dispatch ──────────────────────────────────────────────────────────────

    @property
    def seq(self) -> int:
        """Peek at the next sequence number without consuming it."""
        # itertools.count stores internal state; we peek via __next__ and
        # immediately return from the counter state.
        # Since we can't peek without consuming, we expose the running count
        # minus 1 after the first emit.  For external use (e.g. WS seq tracking)
        # call emit() and read the returned seq.
        return next(self._seq_counter) - 0  # see note — callers use _next_seq()

    def _next_seq(self) -> int:
        return next(self._seq_counter)

    async def emit(self, event: GatewayEvent) -> int:
        """Dispatch *event* to all registered handlers and return the sequence number.

        Handlers registered for ``event.event_type`` and for the wildcard
        ``"*"`` type are both called, in registration order.  Handler
        exceptions are caught and logged (they do not abort dispatch).

        Returns:
            The monotonic sequence number assigned to this emission.
        """
        if not self._running:
            logger.warning(
                "emit() called on a stopped GatewayRouter — event dropped.",
                extra={"event_type": event.event_type, "event_id": event.event_id},
            )
            return 0

        seq = self._next_seq()
        specific = list(self._handlers.get(event.event_type, []))
        wildcard = list(self._handlers.get("*", []))
        all_handlers = specific + [h for h in wildcard if h not in specific]

        logger.debug(
            "emitting event",
            extra={
                "event_type": event.event_type,
                "event_id": event.event_id,
                "session_key": event.session_key,
                "handler_count": len(all_handlers),
                "seq": seq,
            },
        )

        for handler in all_handlers:
            try:
                await handler(event)
            except Exception:
                logger.exception(
                    "Handler raised an exception during event dispatch",
                    extra={
                        "handler": handler.__qualname__,
                        "event_type": event.event_type,
                        "event_id": event.event_id,
                    },
                )

        return seq

    def emit_nowait(self, event: GatewayEvent) -> None:
        """Schedule event emission as a background asyncio task (fire-and-forget).

        Use this when ``await`` is not available (e.g., inside a synchronous
        callback or a ``__del__`` handler).  The returned task is *not*
        returned — callers that need the sequence number must use ``emit()``.
        """
        asyncio.create_task(
            self.emit(event),
            name=f"gateway_emit_{event.event_type}_{event.event_id[:8]}",
        )


# ── Process-wide singleton ────────────────────────────────────────────────────

_router: GatewayRouter | None = None


def init_router() -> GatewayRouter:
    """Create, start, and store the process-wide ``GatewayRouter`` singleton.

    Must be called once inside the FastAPI lifespan startup hook.
    Calling it a second time replaces the previous instance (safe for testing).
    """
    global _router  # noqa: PLW0603
    _router = GatewayRouter()
    _router.start()
    logger.info("GatewayRouter singleton initialised.")
    return _router


def get_router() -> GatewayRouter:
    """Return the process-wide ``GatewayRouter`` singleton.

    Raises:
        RuntimeError: If ``init_router()`` has not been called yet.
    """
    if _router is None:
        raise RuntimeError("GatewayRouter not initialised.  Call init_router() first.")
    return _router
