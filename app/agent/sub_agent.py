"""Sub-agent spawning and lifecycle management (§3.3, §20.7, Sprint 08).

Provides:
- ``spawn_sub_agent()`` — create a new agent session and emit an initial message.
- ``active_sub_agent_count()`` — count how many sub-agent sessions are currently tracked.
- ``_auto_archive()``         — background task that archives a sub-agent after a delay.

Concurrency limit
-----------------
``MAX_CONCURRENT_SUBAGENTS`` (from ``app.constants``) caps the number of active
sub-agent sessions per parent.  This is enforced at spawn time.  Independent of
the global ``asyncio.Semaphore`` that the workflow runtime uses for parallel steps.

Policy scoping
--------------
Spawned sub-agents inherit the ``WORKER`` preset by default:
- no external channel delivery
- cannot spawn further sub-agents (``can_spawn_agents=False``)
- cannot send inter-session messages (``can_send_inter_session=False``)

The caller may request a different preset via *policy_preset*.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from app.constants import MAX_CONCURRENT_SUBAGENTS
from app.gateway.router import get_router

logger = logging.getLogger(__name__)

# ── In-memory concurrency tracking ────────────────────────────────────────────

# parent_session_key → set of sub-agent session keys currently tracked
_active: dict[str, set[str]] = {}
# per-parent lock to make the count-check + register atomic (TD-58)
_spawn_locks: dict[str, asyncio.Lock] = {}


def get_active_count(parent_id: str | None = None) -> int:
    """Return the number of active sub-agents, optionally filtered by parent (TD-126).

    Parameters
    ----------
    parent_id:
        When provided, count only sub-agents under this parent.
        When ``None``, count all active sub-agents across all parents.
    """
    if parent_id is not None:
        return len(_active.get(parent_id, set()))
    return sum(len(v) for v in _active.values())


def active_sub_agent_count(parent_session_key: str) -> int:
    """Return the number of active sub-agent sessions for *parent_session_key*."""
    return len(_active.get(parent_session_key, set()))


def _register(parent: str, sub_key: str) -> None:
    _active.setdefault(parent, set()).add(sub_key)


def _unregister(parent: str, sub_key: str) -> None:
    bucket = _active.get(parent)
    if bucket:
        bucket.discard(sub_key)


def _get_spawn_lock(parent: str) -> asyncio.Lock:
    """Return (lazily creating) the per-parent spawn lock."""
    if parent not in _spawn_locks:
        _spawn_locks[parent] = asyncio.Lock()
    return _spawn_locks[parent]


# ── Core functions ─────────────────────────────────────────────────────────────


async def spawn_sub_agent(
    *,
    agent_id: str,
    initial_message: str | None = None,
    policy_preset: str = "worker",
    parent_session_key: str | None = None,
    auto_archive_minutes: int = 60,
) -> str:
    """Create a new sub-agent session and optionally trigger it with *initial_message*.

    Parameters
    ----------
    agent_id:
        The agent that will run in the new session.
    initial_message:
        If supplied, an ``inbound.message`` event is emitted immediately after
        the session is created, triggering a turn.
    policy_preset:
        Named ``SessionPolicyPresets`` preset to apply to the sub-agent session.
        Defaults to ``"worker"`` (no spawning, no external delivery).
    parent_session_key:
        The calling session key — used to enforce the per-parent concurrency
        limit and for ``parent_session_key`` on the new session.
    auto_archive_minutes:
        Archive the sub-agent session this many minutes after it is created.
        Set to 0 to disable auto-archive.

    Returns
    -------
    str
        The ``session_key`` of the newly created sub-agent session.

    Raises
    ------
    RuntimeError
        When the per-parent concurrency cap is reached.
    """
    # ── Concurrency limit check (atomic via per-parent lock — TD-58) ─────────
    parent = parent_session_key or "_orphan"
    async with _get_spawn_lock(parent):
        if active_sub_agent_count(parent) >= MAX_CONCURRENT_SUBAGENTS:
            raise RuntimeError(
                f"Concurrency limit ({MAX_CONCURRENT_SUBAGENTS}) reached for "
                f"parent session {parent!r}.  Wait for a sub-agent to finish."
            )

        # ── Build a unique session key ────────────────────────────────────────
        short_id = str(uuid.uuid4()).replace("-", "")[:8]
        sub_session_key = f"agent:{agent_id}:sub:{short_id}"

        # ── Resolve policy ────────────────────────────────────────────────────
        from app.sessions.policy import SessionPolicyPresets
        policy = SessionPolicyPresets.by_name(policy_preset).model_dump()

        # ── Create the session ────────────────────────────────────────────────
        from app.sessions.store import get_session_store
        store = get_session_store()
        await store.create(
            session_key=sub_session_key,
            kind="agent",
            agent_id=agent_id,
            parent_session_key=parent_session_key,
            policy=policy,
            title=f"sub:{agent_id}:{short_id}",
        )
        logger.info(
            "Sub-agent session created: %s (parent=%s, agent=%s)",
            sub_session_key, parent_session_key, agent_id,
        )

        # ── Track concurrency ────────────────────────────────────────────────
        _register(parent, sub_session_key)

    # ── Emit initial message to trigger the turn loop ─────────────────────────
    if initial_message:
        from app.gateway.events import ET, EventSource, GatewayEvent
        router = get_router()
        event = GatewayEvent(
            event_type=ET.INBOUND_MESSAGE,
            source=EventSource(kind="agent", id="sub_agent_spawner"),
            session_key=sub_session_key,
            payload={
                "session_id": sub_session_key,
                "content": initial_message,
                "provenance": "inter_session",
            },
        )
        router.emit_nowait(event)
        logger.debug("Initial message emitted for sub-agent session %s", sub_session_key)

    # ── Schedule auto-archive (always — to ensure _unregister is called; TD-70) ──
    # When auto_archive_minutes=0 we still schedule with delay_s=0 so the entry
    # is cleaned up after the current turn without an indefinite leak.
    delay_s = auto_archive_minutes * 60 if auto_archive_minutes > 0 else 0
    asyncio.create_task(
        _auto_archive(parent, sub_session_key, delay_s=delay_s),
        name=f"auto_archive:{sub_session_key}",
    )

    return sub_session_key


async def _auto_archive(parent: str, sub_session_key: str, delay_s: float) -> None:
    """Background task: archive *sub_session_key* after *delay_s* seconds.

    Always calls ``_unregister`` in its ``finally`` block so that the entry in
    ``_active`` is cleaned up even when *delay_s* is 0 (TD-70).
    """
    await asyncio.sleep(delay_s)
    try:
        if delay_s > 0:
            from app.sessions.store import get_session_store
            store = get_session_store()
            await store.archive(sub_session_key)
            logger.info("Sub-agent session auto-archived: %s", sub_session_key)
    except Exception:
        logger.warning(
            "Failed to auto-archive sub-agent session %s", sub_session_key, exc_info=True
        )
    finally:
        _unregister(parent, sub_session_key)
