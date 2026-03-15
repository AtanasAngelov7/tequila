"""Message store — insert and query session messages (§3.4 full — Sprint 05).

Supports the complete Message model: tool calls, branching, provenance,
feedback, content blocks, and cost metadata.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.db.connection import write_transaction
from app.db.schema import row_to_dict
from app.exceptions import NotFoundError
from app.sessions.models import Message

logger = logging.getLogger(__name__)

# All columns to SELECT (avoids SELECT * surprises after schema changes)
_MSG_COLS = (
    "id, session_id, role, content, "
    "content_blocks, tool_calls, tool_call_id, file_ids, "
    "parent_id, active, provenance, compressed, compressed_source_ids, "
    "turn_cost_id, feedback_rating, feedback_note, feedback_at, "
    "model, input_tokens, output_tokens, "
    "created_at, updated_at"
)


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
        content_blocks: list[dict[str, Any]] | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        file_ids: list[str] | None = None,
        parent_id: str | None = None,
        active: bool = True,
        provenance: str = "user_input",
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        turn_cost_id: str | None = None,
    ) -> Message:
        """Persist a new message and return the hydrated model."""
        from app.sessions.store import get_session_store

        message_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()

        row: dict[str, Any] = {
            "id": message_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "content_blocks": json.dumps(content_blocks or []),
            "tool_calls": json.dumps(tool_calls) if tool_calls is not None else None,
            "tool_call_id": tool_call_id,
            "file_ids": json.dumps(file_ids or []),
            "parent_id": parent_id,
            "active": 1 if active else 0,
            "provenance": provenance,
            "compressed": 0,
            "compressed_source_ids": json.dumps([]),
            "turn_cost_id": turn_cost_id,
            "feedback_rating": None,
            "feedback_note": None,
            "feedback_at": None,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "created_at": now_iso,
            "updated_at": now_iso,
        }

        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT INTO messages (
                    id, session_id, role, content,
                    content_blocks, tool_calls, tool_call_id, file_ids,
                    parent_id, active, provenance, compressed, compressed_source_ids,
                    turn_cost_id, feedback_rating, feedback_note, feedback_at,
                    model, input_tokens, output_tokens,
                    created_at, updated_at
                ) VALUES (
                    :id, :session_id, :role, :content,
                    :content_blocks, :tool_calls, :tool_call_id, :file_ids,
                    :parent_id, :active, :provenance, :compressed, :compressed_source_ids,
                    :turn_cost_id, :feedback_rating, :feedback_note, :feedback_at,
                    :model, :input_tokens, :output_tokens,
                    :created_at, :updated_at
                )
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
        """Fetch a single message by ID."""
        async with self._db.execute(
            f"SELECT {_MSG_COLS} FROM messages WHERE id = ?",
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
        """Return messages for *session_id* ordered oldest-first."""
        active_clause = "AND active = 1" if active_only else ""
        async with self._db.execute(
            f"""
            SELECT {_MSG_COLS}
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

    async def get_active_chain(self, session_id: str) -> list[Message]:
        """Return all active messages for *session_id* in chronological order.

        Used by prompt assembly to load session history.
        """
        return await self.list_by_session(session_id, limit=1000, active_only=True)

    # ── Update ────────────────────────────────────────────────────────────────

    async def update_feedback(
        self,
        message_id: str,
        *,
        rating: str | None,
        note: str | None = None,
    ) -> Message:
        """Set or clear feedback on a message.

        Pass ``rating=None`` to remove feedback.
        """
        now_iso = datetime.now(timezone.utc).isoformat() if rating else None
        async with write_transaction(self._db):
            await self._db.execute(
                """
                UPDATE messages
                SET feedback_rating = ?, feedback_note = ?, feedback_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (rating, note, now_iso, datetime.now(timezone.utc).isoformat(), message_id),
            )
        return await self.get(message_id)

    async def deactivate_from(
        self,
        session_id: str,
        *,
        from_message_id: str,
    ) -> int:
        """Mark *from_message_id* and all later active messages in *session_id*
        as ``active=False``.

        Returns the number of rows updated.
        Used by branching (§3.5) for regenerate and edit-and-resubmit.
        """
        # Get the created_at of the pivot message
        async with self._db.execute(
            "SELECT created_at FROM messages WHERE id = ? AND session_id = ?",
            (from_message_id, session_id),
        ) as cur:
            pivot = await cur.fetchone()
        if pivot is None:
            raise NotFoundError(resource="Message", id=from_message_id)
        pivot_ts = pivot[0]

        now_iso = datetime.now(timezone.utc).isoformat()
        async with write_transaction(self._db):
            result = await self._db.execute(
                """
                UPDATE messages
                SET active = 0, updated_at = ?
                WHERE session_id = ?
                  AND active = 1
                  AND created_at >= ?
                """,
                (now_iso, session_id, pivot_ts),
            )
        return result.rowcount


# ── Singleton ─────────────────────────────────────────────────────────────────

_message_store: MessageStore | None = None


def init_message_store(db: aiosqlite.Connection) -> MessageStore:
    """Initialise and return the process-wide message store singleton."""
    global _message_store  # noqa: PLW0603
    _message_store = MessageStore(db)
    return _message_store


def get_message_store() -> MessageStore:
    """Return the initialised message store singleton."""
    if _message_store is None:
        raise RuntimeError(
            "MessageStore has not been initialised. "
            "Call init_message_store() during application startup."
        )
    return _message_store

