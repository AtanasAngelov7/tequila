"""Per-session message buffer for turn serialisation (§2.5, §20.6), and
seq-based event buffer for WebSocket reconnection (§2.5a).

Two independent buffer classes live here:

``SessionBuffer``
    FIFO queue holding pending :class:`~app.gateway.events.GatewayEvent`
    objects while a turn is in-flight.  Capacity = ``MAX_BUFFERED_MESSAGES``
    (default 10).

``EventBuffer``
    Ring buffer keyed by monotonic sequence number.  Holds the last N server
    push events so that reconnecting WebSocket clients can replay missed events
    by sending ``last_seq``.  Bounded to ``max_events`` (default 200) items
    and ``max_age_s`` (default 120 s) per event.

``BufferRegistry``
    Process-wide registry of :class:`SessionBuffer` instances.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

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

    def evict_stale(self, active_keys: set[str]) -> int:
        """Remove buffers whose session_key is NOT in *active_keys* (TD-205).

        Returns the number of evicted buffers.
        """
        stale = [k for k in self._buffers if k not in active_keys]
        for k in stale:
            self._buffers.pop(k, None)
        return len(stale)

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


# ── EventBuffer (WS reconnection, §2.5a) ─────────────────────────────────────


class _EventEntry:
    """A single entry in the :class:`EventBuffer` ring buffer."""

    __slots__ = ("seq", "event", "ts")

    def __init__(self, seq: int, event: dict[str, Any]) -> None:
        self.seq = seq
        self.event = event
        self.ts = time.monotonic()


class EventBuffer:
    """Seq-numbered ring buffer for WebSocket server-push events (§2.5a).

    The server assigns a monotonically increasing *seq* to every event it
    sends to a client.  When the client reconnects it sends ``last_seq``; the
    buffer replays all events with ``seq > last_seq``.

    Bounded by two limits:
    - ``max_events`` — oldest entry evicted when the ring is full.
    - ``max_age_s`` — entries older than this are considered expired; a
      ``resync_required`` response is sent to the client if its ``last_seq``
      falls before the oldest surviving entry.

    Thread-safety: asyncio single-event-loop — the Python GIL is sufficient.
    """

    def __init__(
        self,
        max_events: int = 200,
        max_age_s: float = 120.0,
    ) -> None:
        self._max_events = max_events
        self._max_age_s = max_age_s
        self._ring: deque[_EventEntry] = deque()
        self._next_seq: int = 1

    # ── Write ─────────────────────────────────────────────────────────────────

    def push(self, event: dict[str, Any]) -> int:
        """Append *event* and return the assigned seq number.

        Evicts the oldest entry when the ring is full.
        """
        seq = self._next_seq
        self._next_seq += 1
        entry = _EventEntry(seq, event)
        if len(self._ring) >= self._max_events:
            self._ring.popleft()
        self._ring.append(entry)
        return seq

    # ── Read ──────────────────────────────────────────────────────────────────

    def events_since(
        self, last_seq: int
    ) -> tuple[list[dict[str, Any]], bool]:
        """Return events with seq > *last_seq*.

        Also purges expired entries before inspecting the ring.

        Returns:
            A pair ``(events, resync_required)``.

            *resync_required* is ``True`` when *last_seq* is older than the
            oldest surviving entry — the client has missed events that are no
            longer in the buffer and must perform a full state refresh.
        """
        self._purge_expired()

        if not self._ring:
            # Empty buffer — nothing to replay, no resync needed
            return [], False

        oldest_seq = self._ring[0].seq
        if last_seq < oldest_seq:
            # TD-216: Fixed off-by-one — resync when last_seq < oldest surviving seq
            return [], True

        events = [
            entry.event
            for entry in self._ring
            if entry.seq > last_seq
        ]
        return events, False

    @property
    def next_seq(self) -> int:
        """The sequence number that will be assigned to the next pushed event."""
        return self._next_seq

    def size(self) -> int:
        """Current number of entries in the ring."""
        return len(self._ring)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _purge_expired(self) -> None:
        """Remove entries older than ``max_age_s`` from the front of the ring."""
        now = time.monotonic()
        while self._ring and (now - self._ring[0].ts) > self._max_age_s:
            self._ring.popleft()
