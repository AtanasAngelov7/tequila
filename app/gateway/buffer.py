"""Per-session message buffer for turn serialisation (§2.5, §20.6).

When a session is busy (agent turn in-flight), incoming messages are held here
rather than dropped.  Each ``SessionBuffer`` has a capacity of
``MAX_BUFFERED_MESSAGES`` (default 10).  If the buffer is full, ``enqueue``
returns ``False`` and the gateway returns a ``busy`` response to the sender.
"""
from __future__ import annotations

import logging
from collections import deque

from app.constants import MAX_BUFFERED_MESSAGES
from app.gateway.events import GatewayEvent

logger = logging.getLogger(__name__)

# ── Per-session buffer ────────────────────────────────────────────────────────


class SessionBuffer:
    """FIFO queue holding pending ``GatewayEvent`` objects for one session.

    Thread-safety is guaranteed by Python's GIL for single-threaded asyncio;
    no additional locking is needed.
    """

    def __init__(self, session_key: str, capacity: int = MAX_BUFFERED_MESSAGES) -> None:
        self._session_key = session_key
        self._capacity = capacity
        self._queue: deque[GatewayEvent] = deque()

    def enqueue(self, event: GatewayEvent) -> bool:
        """Add *event* to the tail of the queue.

        Returns:
            ``True`` if the event was accepted.
            ``False`` if the buffer is at capacity (event is *not* stored).
        """
        if len(self._queue) >= self._capacity:
            logger.warning(
                "Session buffer full — event dropped",
                extra={
                    "session_key": self._session_key,
                    "event_type": event.event_type,
                    "event_id": event.event_id,
                    "capacity": self._capacity,
                },
            )
            return False
        self._queue.append(event)
        return True

    def dequeue(self) -> GatewayEvent | None:
        """Remove and return the oldest event, or ``None`` if the buffer is empty."""
        return self._queue.popleft() if self._queue else None

    def is_empty(self) -> bool:
        """Return ``True`` when the buffer contains no events."""
        return len(self._queue) == 0

    def size(self) -> int:
        """Return the current number of buffered events."""
        return len(self._queue)

    def clear(self) -> None:
        """Discard all buffered events."""
        self._queue.clear()


# ── Registry ──────────────────────────────────────────────────────────────────


class BufferRegistry:
    """Process-wide store of ``SessionBuffer`` instances keyed by session key.

    Buffers are created lazily on first access and removed explicitly when
    a session is closed or archived.
    """

    def __init__(self) -> None:
        self._buffers: dict[str, SessionBuffer] = {}

    def get(self, session_key: str) -> SessionBuffer:
        """Return the buffer for *session_key*, creating it if necessary."""
        if session_key not in self._buffers:
            self._buffers[session_key] = SessionBuffer(session_key)
        return self._buffers[session_key]

    def remove(self, session_key: str) -> None:
        """Remove and discard the buffer for *session_key* (if it exists)."""
        self._buffers.pop(session_key, None)

    def active_count(self) -> int:
        """Return the number of sessions with an active buffer."""
        return len(self._buffers)


# ── Process-wide singleton ────────────────────────────────────────────────────

_registry: BufferRegistry | None = None


def get_buffer_registry() -> BufferRegistry:
    """Return the process-wide ``BufferRegistry`` singleton (lazy init)."""
    global _registry  # noqa: PLW0603
    if _registry is None:
        _registry = BufferRegistry()
    return _registry
