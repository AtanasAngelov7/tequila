"""Message store — insert and query session messages (§3.4).

Sprint 02 provides the minimal persistence layer needed for echo-back chat.
The full message model (tool_calls, branching, provenance, feedback, costs)
is added in Sprint 05 alongside the agent turn loop.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

import aiosqlite

from app.db.connection import write_transaction
from app.db.schema import row_to_dict
from app.exceptions import NotFoundError
from app.sessions.models import Message

logger = logging.getLogger(__name__)


class MessageStore:
    """Database operations for the ``messages`` table.

    All writes go through ``write_transaction``; reads are direct SELECT
    queries that benefit from WAL concurrent read access.
    """

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # ── Create ────────────────────────────────────────────────────────────────

    async def insert(
        self,
        *,
        session_id: str,
        role: str,
        content: str = "",
    ) -> Message:
        """Persist a new message and return the model.

        Also stamps ``messages.updated_at`` and updates the session's
        ``message_count + last_message_at`` via the SessionStore helper
        (:meth:`~app.sessions.store.SessionStore.update_last_message`).
        """
        from app.sessions.store import get_session_store

        message_id = str(uuid.uuid4())
        now_iso = datetime.utcnow().isoformat()

        row: dict[str, Any] = {
            "id": message_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "created_at": now_iso,
            "updated_at": now_iso,
        }

        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT INTO messages (id, session_id, role, content, created_at, updated_at)
                VALUES (:id, :session_id, :role, :content, :created_at, :updated_at)
                """,
                row,
            )
        logger.debug(
            "Message inserted",
            extra={"message_id": message_id, "session_id": session_id, "role": role},
        )

        # Update session stats (atomic SQL increment — §20.3a)
        try:
            store = get_session_store()
            await store.update_last_message(session_id)
        except Exception:
            logger.warning(
                "Could not update session stats after message insert",
                extra={"session_id": session_id},
            )

        return await self.get(message_id)

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get(self, message_id: str) -> Message:
        """Fetch a single message by ID.

        Raises :class:`~app.exceptions.NotFoundError` when absent.
        """
        async with self._db.execute(
            "SELECT id, session_id, role, content, created_at, updated_at "
            "FROM messages WHERE id = ?",
            (message_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise NotFoundError(resource="Message", id=message_id)
        return Message.from_row(row_to_dict(row))

    async def list_by_session(
        self,
        session_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        active_only: bool = True,
    ) -> list[Message]:
        """Return messages for *session_id* ordered oldest-first.

        *active_only* filters to ``active = 1`` rows (defaults to ``True`` in
        Sprint 02; full branching support added in Sprint 05).
        """
        active_clause = "AND active = 1" if active_only else ""
        async with self._db.execute(
            f"""
            SELECT id, session_id, role, content, created_at, updated_at
            FROM messages
            WHERE session_id = ?
            {active_clause}
            ORDER BY created_at ASC
            LIMIT ? OFFSET ?
            """,
            (session_id, limit, offset),
        ) as cur:
            rows = await cur.fetchall()
            return [Message.from_row(row_to_dict(r)) for r in rows]


# ── Singleton ─────────────────────────────────────────────────────────────────

_message_store: MessageStore | None = None


def init_message_store(db: aiosqlite.Connection) -> MessageStore:
    """Initialise and return the process-wide message store singleton."""
    global _message_store  # noqa: PLW0603
    _message_store = MessageStore(db)
    return _message_store


def get_message_store() -> MessageStore:
    """Return the initialised message store singleton.

    Raises :class:`RuntimeError` if :func:`init_message_store` has not been called.
    """
    if _message_store is None:
        raise RuntimeError(
            "MessageStore has not been initialised. "
            "Call init_message_store() during application startup."
        )
    return _message_store
