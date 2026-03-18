"""Unit tests for app/sessions/branching.py."""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import NotFoundError, ValidationError


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _insert_messages(store, session_id: str, pairs: list[tuple[str, str]]) -> list[object]:
    """Insert (role, content) pairs; return Message objects in order."""
    msgs = []
    for role, content in pairs:
        msg = await store.insert(
            session_id=session_id,
            role=role,
            content=content,
            active=True,
        )
        msgs.append(msg)
    return msgs


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_regenerate_deactivates_and_triggers_turn(migrated_db) -> None:
    """regenerate() deactivates the assistant message onward + triggers turn loop."""
    from app.sessions.store import SessionStore
    from app.sessions.messages import MessageStore
    from app.sessions.branching import regenerate

    session_store = SessionStore(migrated_db)
    msg_store = MessageStore(migrated_db)

    # Create session
    session = await session_store.create(session_key="user:regen_test")
    sid = session.session_id
    key = session.session_key

    # Insert user + assistant messages
    msgs = await _insert_messages(msg_store, sid, [
        ("user", "Hello!"),
        ("assistant", "Hi there!"),
    ])
    user_msg, asst_msg = msgs

    mock_loop = MagicMock()
    mock_loop._run_full_turn_inner = AsyncMock()
    mock_loop._get_session_lock = MagicMock(return_value=asyncio.Lock())

    with patch("app.agent.turn_loop.get_turn_loop", return_value=mock_loop):
        with patch("app.sessions.messages.get_message_store", return_value=msg_store):
            with patch("app.sessions.store.mark_turn_active"):
                with patch("app.sessions.store.mark_turn_inactive"):
                    await regenerate(
                        session_id=sid,
                        session_key=key,
                        message_id=asst_msg.id,
                        user_name="tester",
                    )

    # Turn loop was called with the user's original content
    mock_loop._run_full_turn_inner.assert_called_once()
    call_kwargs = mock_loop._run_full_turn_inner.call_args.kwargs
    assert call_kwargs["user_content"] == "Hello!"
    assert call_kwargs["session_id"] == sid

    # Assistant message is now deactivated
    chain = await msg_store.get_active_chain(sid)
    active_ids = {m.id for m in chain}
    assert asst_msg.id not in active_ids


@pytest.mark.asyncio
async def test_regenerate_rejects_non_assistant_message(migrated_db) -> None:
    """regenerate() raises ValidationError if message is not from assistant."""
    from app.sessions.store import SessionStore
    from app.sessions.messages import MessageStore
    from app.sessions.branching import regenerate

    session_store = SessionStore(migrated_db)
    msg_store = MessageStore(migrated_db)

    session = await session_store.create(session_key="user:regen_badtype")
    msg = await msg_store.insert(
        session_id=session.session_id,
        role="user",
        content="A user message",
        active=True,
    )

    with patch("app.sessions.messages.get_message_store", return_value=msg_store):
        with pytest.raises(ValidationError):
            await regenerate(
                session_id=session.session_id,
                session_key=session.session_key,
                message_id=msg.id,
            )


@pytest.mark.asyncio
async def test_regenerate_raises_on_missing_message(migrated_db) -> None:
    """regenerate() raises NotFoundError for a non-existent message id."""
    from app.sessions.messages import MessageStore
    from app.sessions.branching import regenerate

    msg_store = MessageStore(migrated_db)

    with patch("app.sessions.messages.get_message_store", return_value=msg_store):
        with pytest.raises(NotFoundError):
            await regenerate(
                session_id="any-session",
                session_key="user:x",
                message_id="msg-does-not-exist",
            )


@pytest.mark.asyncio
async def test_edit_and_resubmit_deactivates_and_triggers_turn(migrated_db) -> None:
    """edit_and_resubmit() deactivates from the user message + triggers new turn."""
    from app.sessions.store import SessionStore
    from app.sessions.messages import MessageStore
    from app.sessions.branching import edit_and_resubmit

    session_store = SessionStore(migrated_db)
    msg_store = MessageStore(migrated_db)

    session = await session_store.create(session_key="user:edit_test")
    sid = session.session_id
    key = session.session_key

    msgs = await _insert_messages(msg_store, sid, [
        ("user", "Original question"),
        ("assistant", "Original answer"),
    ])
    user_msg, asst_msg = msgs

    mock_loop = MagicMock()
    mock_loop._run_full_turn_inner = AsyncMock()
    mock_loop._get_session_lock = MagicMock(return_value=asyncio.Lock())

    with patch("app.agent.turn_loop.get_turn_loop", return_value=mock_loop):
        with patch("app.sessions.messages.get_message_store", return_value=msg_store):
            with patch("app.sessions.store.mark_turn_active"):
                with patch("app.sessions.store.mark_turn_inactive"):
                    await edit_and_resubmit(
                        session_id=sid,
                        session_key=key,
                        message_id=user_msg.id,
                        new_content="Edited question",
                        user_name="tester",
                    )

    # Turn loop called with new content
    call_kwargs = mock_loop._run_full_turn_inner.call_args.kwargs
    assert call_kwargs["user_content"] == "Edited question"

    # Both original messages deactivated
    chain = await msg_store.get_active_chain(sid)
    active_ids = {m.id for m in chain}
    assert user_msg.id not in active_ids
    assert asst_msg.id not in active_ids


@pytest.mark.asyncio
async def test_edit_and_resubmit_rejects_non_user_message(migrated_db) -> None:
    """edit_and_resubmit() raises ValidationError if message is not from user."""
    from app.sessions.store import SessionStore
    from app.sessions.messages import MessageStore
    from app.sessions.branching import edit_and_resubmit

    session_store = SessionStore(migrated_db)
    msg_store = MessageStore(migrated_db)

    session = await session_store.create(session_key="user:edit_badtype")
    msg = await msg_store.insert(
        session_id=session.session_id,
        role="assistant",
        content="An assistant message",
        active=True,
    )

    with patch("app.sessions.messages.get_message_store", return_value=msg_store):
        with pytest.raises(ValidationError):
            await edit_and_resubmit(
                session_id=session.session_id,
                session_key=session.session_key,
                message_id=msg.id,
                new_content="Won't matter",
            )
