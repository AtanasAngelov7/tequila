"""Session store — CRUD, lifecycle state machine, idle detection (§3.2, §3.7, §20.3, §20.6).

Provides:
- :class:`SessionStore` — all database operations for sessions and per-session
  turn queues.
- Per-session :class:`asyncio.Queue` for turn serialisation (§20.6).
- Background idle-detection task (§3.7).

Design decisions:
- All mutating methods go through ``write_transaction`` (§20.2) and carry OCC
  version checks (``AND version = :v``) (§20.3b).
- Atomic SQL increments are used for ``message_count`` instead of read→add→write
  (§20.3a).
- Status transitions assert the expected current state in the WHERE clause to
  prevent double-transitions (§20.3c).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from app.constants import MAX_BUFFERED_MESSAGES, MAX_OCC_RETRIES
from app.db.connection import write_transaction
from app.db.schema import row_to_dict
from app.exceptions import ConflictError, DatabaseError, SessionNotFoundError
from app.sessions.models import Session

logger = logging.getLogger(__name__)


# ── Turn-queue storage ────────────────────────────────────────────────────────

# Per-session asyncio.Queue instances live here (process-wide, in-memory only).
# maxsize=MAX_BUFFERED_MESSAGES enforces the §20.6 turn queue depth.
_turn_queues: dict[str, asyncio.Queue[Any]] = {}


def get_turn_queue(session_key: str) -> asyncio.Queue[Any]:
    """Return (creating if necessary) the per-session turn queue."""
    if session_key not in _turn_queues:
        _turn_queues[session_key] = asyncio.Queue(maxsize=MAX_BUFFERED_MESSAGES)
    return _turn_queues[session_key]


def remove_turn_queue(session_key: str) -> None:
    """Discard the turn queue for *session_key*."""
    _turn_queues.pop(session_key, None)


# TD-206: Track active turns with a set, not queue emptiness.
# A turn that has been dequeued and is actively processing has an empty queue,
# so queue-based counting gives inverted results.
_active_turns: set[str] = set()


def mark_turn_active(session_key: str) -> None:
    """Mark *session_key* as having an active turn in progress."""
    _active_turns.add(session_key)


def mark_turn_inactive(session_key: str) -> None:
    """Mark the turn for *session_key* as finished."""
    _active_turns.discard(session_key)


def is_agent_turn_active(agent_id: str) -> bool:
    """Return True if **any** session associated with *agent_id* has an active turn.

    Since session_key contains the agent_id prefix by convention
    (``<agent_id>:<channel>:<user_or_id>``), we check for prefix matches.
    """
    prefix = f"{agent_id}:"
    return any(k.startswith(prefix) or k == agent_id for k in _active_turns)


def active_turn_count() -> int:
    """Return the number of sessions that currently have an active turn.

    Used by the ``GET /api/system/status`` health endpoint without exposing the
    private ``_active_turns`` set to external callers.
    """
    return len(_active_turns)


# ── SessionStore ──────────────────────────────────────────────────────────────


class SessionStore:
    """Database operations for the ``sessions`` table.

    Pass an open :class:`aiosqlite.Connection` at construction time.  Every
    write method serialises through :func:`write_transaction`, reads go
    directly to the connection (WAL mode allows concurrent reads).

    ``MAX_OCC_RETRIES`` controls how many times an OCC update is retried before
    a :class:`~app.exceptions.ConflictError` is raised (§20.3b).
    """

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # ── Create ────────────────────────────────────────────────────────────────

    async def create(
        self,
        *,
        session_key: str | None = None,
        kind: str = "user",
        agent_id: str = "main",
        channel: str = "webchat",
        policy: dict[str, Any] | None = None,
        parent_session_key: str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        """Insert a new session and return the fully hydrated model.

        *session_key* defaults to ``user:main`` when *kind* is ``"user"`` and
        no key is supplied; callers should normalise keys before calling for
        non-default session types.
        """
        import json

        from app.sessions.policy import SessionPolicy

        session_id = str(uuid.uuid4())
        if session_key is None:
            # Use a unique suffix to prevent collisions when multiple sessions
            # share the same agent_id (§3.2 session_key uniqueness).
            session_key = f"{kind}:{agent_id}:{session_id[:8]}"

        # ── Default title (D3, §3.2) ──────────────────────────────────────
        if title is None:
            meta = metadata or {}
            if kind == "channel":
                sender = meta.get("sender") or meta.get("from") or "unknown"
                title = f"{channel.capitalize()}: {sender}"
            elif kind == "cron":
                title = meta.get("job_name") or "Scheduled Task"
            elif kind == "webhook":
                title = meta.get("webhook_label") or "Webhook Task"
            elif kind == "agent":
                title = f"Agent: {agent_id}"
            else:  # "user" or any future kind
                title = "New Session"

        policy_obj = SessionPolicy(**(policy or {}))
        now_iso = datetime.now(timezone.utc).isoformat()

        row: dict[str, Any] = {
            "session_id": session_id,
            "session_key": session_key,
            "kind": kind,
            "agent_id": agent_id,
            "channel": channel,
            "policy": policy_obj.model_dump_json(),
            "status": "active",
            "parent_session_key": parent_session_key,
            "title": title,
            "summary": None,
            "message_count": 0,
            "last_message_at": None,
            "metadata": json.dumps(metadata or {}),
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
        }

        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT INTO sessions (
                    session_id, session_key, kind, agent_id, channel, policy,
                    status, parent_session_key, title, summary,
                    message_count, last_message_at, metadata,
                    created_at, updated_at, version
                ) VALUES (
                    :session_id, :session_key, :kind, :agent_id, :channel, :policy,
                    :status, :parent_session_key, :title, :summary,
                    :message_count, :last_message_at, :metadata,
                    :created_at, :updated_at, :version
                )
                """,
                row,
            )
        logger.debug(
            "Session created",
            extra={"session_id": session_id, "session_key": session_key},
        )
        session = await self.get_by_id(session_id)
        return session

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_by_id(self, session_id: str) -> Session:
        """Fetch a session by its UUID primary key.

        Raises :class:`~app.exceptions.SessionNotFoundError` when absent.
        """
        async with self._db.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise SessionNotFoundError(session_id)
        return Session.from_row(row_to_dict(row))

    async def get_by_key(self, session_key: str) -> Session:
        """Fetch a session by its natural key (§3.1).

        Raises :class:`~app.exceptions.SessionNotFoundError` when absent.
        """
        async with self._db.execute(
            "SELECT * FROM sessions WHERE session_key = ?", (session_key,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise SessionNotFoundError(session_key)
        return Session.from_row(row_to_dict(row))

    async def list(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        agent_id: str | None = None,
        q: str | None = None,
        sort: str = "last_activity",
        order: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> list[Session]:
        """Return sessions filtered by params, sorted and paginated.

        Args:
            status: Filter by session status (active|idle|archived).
            kind: Filter by session kind (user|agent|channel|cron|webhook|workflow).
            agent_id: Filter by agent ID.
            q: Full-text search across title and summary (LIKE, upgraded to
               FTS5 in Sprint 09).
            sort: Sort column — ``last_activity`` | ``created`` |
                  ``message_count`` | ``title``.
            order: Sort direction — ``asc`` | ``desc``.
            limit: Maximum rows to return (1–200).
            offset: Pagination offset.
        """
        filters: list[str] = []
        params: list[Any] = []

        if status is not None:
            filters.append("status = ?")
            params.append(status)
        if kind is not None:
            filters.append("kind = ?")
            params.append(kind)
        if agent_id is not None:
            filters.append("agent_id = ?")
            params.append(agent_id)
        if q is not None:
            pattern = f"%{q}%"
            filters.append("(title LIKE ? OR summary LIKE ?)")
            params.extend([pattern, pattern])

        where = ("WHERE " + " AND ".join(filters)) if filters else ""

        # Safe whitelist for sort / order to prevent SQL injection.
        _sort_map = {
            "last_activity": "COALESCE(last_message_at, created_at)",
            "created": "created_at",
            "message_count": "message_count",
            "title": "COALESCE(title, '')",
        }
        _order_safe = "ASC" if order.lower() == "asc" else "DESC"
        order_expr = _sort_map.get(sort, "COALESCE(last_message_at, created_at)")

        params += [limit, offset]

        query = f"""
            SELECT * FROM sessions
            {where}
            ORDER BY {order_expr} {_order_safe}
            LIMIT ? OFFSET ?
        """
        async with self._db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [Session.from_row(row_to_dict(r)) for r in rows]

    async def count(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        agent_id: str | None = None,
        q: str | None = None,
    ) -> int:
        """Return total number of sessions matching filters (TD-161).

        Uses the same filter logic as :meth:`list` but executes ``COUNT(*)``
        instead of fetching rows, giving a true total for pagination.
        """
        filters: list[str] = []
        params: list[Any] = []

        if status is not None:
            filters.append("status = ?")
            params.append(status)
        if kind is not None:
            filters.append("kind = ?")
            params.append(kind)
        if agent_id is not None:
            filters.append("agent_id = ?")
            params.append(agent_id)
        if q is not None:
            pattern = f"%{q}%"
            filters.append("(title LIKE ? OR summary LIKE ?)")
            params.extend([pattern, pattern])

        where = ("WHERE " + " AND ".join(filters)) if filters else ""
        query = f"SELECT COUNT(*) FROM sessions {where}"
        async with self._db.execute(query, params) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0

    # ── Update ────────────────────────────────────────────────────────────────

    async def update(
        self,
        session_id: str,
        *,
        title: str | None = None,
        summary: str | None = None,
        metadata: dict[str, Any] | None = None,
        policy: Any | None = None,  # SessionPolicy or dict
    ) -> Session:
        """Update mutable display fields on a session (OCC, §20.3b).

        Supports *title*, *summary*, *metadata*, and *policy* (Sprint 07).
        Status transitions go through :meth:`archive` / :meth:`unarchive` /
        :meth:`mark_idle`.

        Raises:
            SessionNotFoundError: when session_id doesn't exist.
            ConflictError: after MAX_OCC_RETRIES version mismatches.
        """
        import json

        for attempt in range(MAX_OCC_RETRIES + 1):
            session = await self.get_by_id(session_id)

            # Build only the changed columns
            sets: list[str] = ["updated_at = :now", "version = version + 1"]
            params: dict[str, Any] = {
                "session_id": session_id,
                "expected_version": session.version,
                "now": datetime.now(timezone.utc).isoformat(),
            }

            if title is not None:
                sets.append("title = :title")
                params["title"] = title
            if summary is not None:
                sets.append("summary = :summary")
                params["summary"] = summary
            if metadata is not None:
                sets.append("metadata = :metadata")
                params["metadata"] = json.dumps(metadata)
            if policy is not None:
                # Accept SessionPolicy model or raw dict
                from app.sessions.policy import SessionPolicy as _SP
                policy_obj = policy if isinstance(policy, _SP) else _SP.model_validate(policy)
                sets.append("policy = :policy")
                params["policy"] = policy_obj.model_dump_json()

            if len(sets) == 2:  # only timestamps — nothing to update
                return session

            sql = (
                "UPDATE sessions SET "
                + ", ".join(sets)
                + " WHERE session_id = :session_id AND version = :expected_version"
            )

            # TD-351: Use SELECT changes() instead of total_changes, which counts
            # all rows changed on the connection (including triggers).
            async with write_transaction(self._db):
                await self._db.execute(sql, params)
                async with self._db.execute("SELECT changes()") as chg_cur:
                    chg_row = await chg_cur.fetchone()
                    affected = chg_row[0] if chg_row else 0

            if affected > 0:
                return await self.get_by_id(session_id)

            if attempt < MAX_OCC_RETRIES:
                logger.debug(
                    "OCC conflict on session update — retrying",
                    extra={"session_id": session_id, "attempt": attempt + 1},
                )
                await asyncio.sleep(0)
            else:
                raise ConflictError(
                    f"Session '{session_id}' version conflict after {MAX_OCC_RETRIES} retries."
                )

        raise DatabaseError("Unreachable")  # pragma: no cover

    async def update_last_message(self, session_id: str) -> None:
        """Atomically increment message_count and stamp last_message_at (§20.3a)."""
        now_iso = datetime.now(timezone.utc).isoformat()

        async with write_transaction(self._db):
            await self._db.execute(
                """
                UPDATE sessions
                SET
                    message_count = message_count + 1,
                    last_message_at = :now,
                    updated_at = :now
                WHERE session_id = :session_id
                """,
                {"session_id": session_id, "now": now_iso},
            )

    # ── Lifecycle state machine ───────────────────────────────────────────────

    async def mark_idle(self, session_id: str) -> bool:
        """Transition ``active → idle`` atomically (§20.3c).

        Returns ``True`` when the transition happened, ``False`` when the
        session was already idle/archived (idempotent).
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        before = self._db.total_changes

        async with write_transaction(self._db):
            await self._db.execute(
                """
                UPDATE sessions
                SET status = 'idle', updated_at = :now, version = version + 1
                WHERE session_id = :id AND status = 'active'
                """,
                {"id": session_id, "now": now_iso},
            )

        # TD-224 + TD-275: Clean up turn queue using session_key, not session_id
        try:
            session = await self.get_by_id(session_id)
            remove_turn_queue(session.session_key)
        except Exception:
            pass  # best-effort cleanup

        return self._db.total_changes > before

    async def archive(self, session_id: str) -> Session:
        """Transition any non-archived session to ``archived`` (§3.7).

        Raises SessionNotFoundError if the session doesn't exist.
        """
        # Verify existence first
        session = await self.get_by_id(session_id)
        if session.status == "archived":
            return session

        now_iso = datetime.now(timezone.utc).isoformat()

        async with write_transaction(self._db):
            await self._db.execute(
                """
                UPDATE sessions
                SET status = 'archived', updated_at = :now, version = version + 1
                WHERE session_id = :id
                """,
                {"id": session_id, "now": now_iso},
            )

        # TD-224 + TD-275: Clean up turn queue using session_key, not session_id
        remove_turn_queue(session.session_key)

        # Evict the runtime context budget for this session (TD-12)
        try:
            from app.agent.context import evict_budget
            evict_budget(session_id)
        except Exception:
            logger.warning("Failed to evict context budget for session %s", session_id, exc_info=True)

        # TD-296: Clean up in-memory session state from tool executor
        try:
            from app.tools.executor import get_tool_executor
            get_tool_executor().cleanup_session(session.session_key)
        except Exception:
            logger.debug("Tool executor cleanup skipped for %s", session_id)

        return await self.get_by_id(session_id)

    async def unarchive(self, session_id: str) -> Session:
        """Transition ``archived → active`` (§3.7).

        Raises SessionNotFoundError if the session doesn't exist.
        """
        session = await self.get_by_id(session_id)
        if session.status != "archived":
            return session

        now_iso = datetime.now(timezone.utc).isoformat()

        async with write_transaction(self._db):
            await self._db.execute(
                """
                UPDATE sessions
                SET status = 'active', updated_at = :now, version = version + 1
                WHERE session_id = :id AND status = 'archived'
                """,
                {"id": session_id, "now": now_iso},
            )

        return await self.get_by_id(session_id)

    async def delete(self, session_id: str) -> None:
        """Permanently delete a session and all its messages (§3.7).

        Raises SessionNotFoundError if the session doesn't exist.
        """
        session = await self.get_by_id(session_id)  # raises if not found
        session_key = session.session_key

        async with write_transaction(self._db):
            await self._db.execute(
                "DELETE FROM messages WHERE session_id = ?", (session_id,)
            )
            await self._db.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )
        # TD-275: Clean up turn queue using session_key, not session_id
        remove_turn_queue(session_key)
        # Evict the runtime context budget for this session (TD-12)
        try:
            from app.agent.context import evict_budget
            evict_budget(session_id)
        except Exception:
            logger.warning("Failed to evict context budget for session %s", session_id, exc_info=True)

        # TD-296: Clean up in-memory session state from tool executor
        try:
            from app.tools.executor import get_tool_executor
            get_tool_executor().cleanup_session(session_key)
        except Exception:
            logger.debug("Tool executor cleanup skipped for %s", session_id)

    # ── Idle detection ────────────────────────────────────────────────────────

    async def run_idle_check(self, idle_timeout_days: int = 7) -> int:
        """Mark all eligible active sessions as idle (§3.7).

        Sessions with ``last_message_at`` older than *idle_timeout_days* days
        (or never-messaged sessions created more than *idle_timeout_days* days
        ago) are transitioned to ``idle``.

        Returns the number of sessions transitioned.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=idle_timeout_days)
        ).isoformat()

        # Collect IDs first (separate read), then transition each individually.
        async with self._db.execute(
            """
            SELECT session_id FROM sessions
            WHERE status = 'active'
              AND (
                  (last_message_at IS NOT NULL AND last_message_at < :cutoff)
                  OR (last_message_at IS NULL AND created_at < :cutoff)
              )
            """,
            {"cutoff": cutoff},
        ) as cur:
            rows = await cur.fetchall()

        count = 0
        for (sid,) in rows:
            transitioned = await self.mark_idle(sid)
            if transitioned:
                count += 1
                logger.info(
                    "Session transitioned to idle", extra={"session_id": sid}
                )

        return count


# ── Process-wide session store singleton ──────────────────────────────────────


_store: SessionStore | None = None


def init_session_store(db: aiosqlite.Connection) -> SessionStore:
    """Initialise and return the process-wide session store singleton."""
    global _store  # noqa: PLW0603
    _store = SessionStore(db)
    return _store


def get_session_store() -> SessionStore:
    """Return the initialised session store singleton.

    Raises :class:`RuntimeError` if :func:`init_session_store` has not been
    called yet.
    """
    if _store is None:
        raise RuntimeError(
            "SessionStore has not been initialised. "
            "Call init_session_store() during application startup."
        )
    return _store


# ── Idle detection background task ────────────────────────────────────────────


async def idle_detection_task(
    interval_seconds: int = 900,  # 15 minutes
    idle_timeout_days: int = 7,
) -> None:
    """Long-running background task that periodically marks idle sessions (§3.7).

    Runs forever until cancelled. Start via ``asyncio.create_task()``.
    """
    logger.info(
        "Idle detection task started",
        extra={
            "interval_seconds": interval_seconds,
            "idle_timeout_days": idle_timeout_days,
        },
    )
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            store = get_session_store()
            n = await store.run_idle_check(idle_timeout_days=idle_timeout_days)
            if n:
                logger.info("Idle check complete", extra={"transitioned": n})
        except Exception:
            logger.exception("Idle detection task error — will retry next cycle")
