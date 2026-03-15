"""Conversation branching — regenerate and edit-and-resubmit (§3.5, Sprint 05).

Branching allows the user to:
- **Regenerate**: re-run the last assistant turn from the same user message.
  The existing assistant response (and all messages after it) are deactivated,
  and a new assistant response is generated via the turn loop.
- **Edit and resubmit**: replace a user message with new content.
  All messages from that message onward are deactivated, and the turn loop
  runs with the edited user message as the new input.

In both cases ``MessageStore.deactivate_from()`` is called to mark the pivot
message and all subsequent active messages as ``active=False``.
The deactivated messages remain in the database and can be retrieved by
setting ``active_only=False`` when listing messages.

Entry points
------------
``regenerate(session_id, message_id)``
    Deactivate from *message_id* (assistant message), re-run turn loop with
    the preceding user message content.

``edit_and_resubmit(session_id, message_id, new_content)``
    Deactivate from *message_id* (user message), insert a new user message
    with *new_content*, then run the turn loop.
"""
from __future__ import annotations

import logging

from app.exceptions import NotFoundError, ValidationError

logger = logging.getLogger(__name__)


async def regenerate(
    *,
    session_id: str,
    session_key: str,
    message_id: str,
    user_name: str = "",
) -> None:
    """Regenerate an assistant response.

    1. Verify *message_id* is an assistant message in *session_id*.
    2. Find the immediately preceding user message in the active chain.
    3. Deactivate from *message_id* (the assistant message) onward.
    4. Trigger a new turn loop run with the preceding user message content.

    Raises
    ------
    NotFoundError
        If *message_id* doesn't exist.
    ValidationError
        If *message_id* is not an assistant message.
    """
    from app.agent.turn_loop import get_turn_loop
    from app.sessions.messages import get_message_store

    store = get_message_store()

    # Load the target message
    msg = await store.get(message_id)
    if msg.session_id != session_id:
        raise NotFoundError(resource="Message", id=message_id)
    if msg.role != "assistant":
        raise ValidationError(f"Message {message_id!r} is not an assistant message (role={msg.role!r}).")

    # Find preceding user message from the active chain
    chain = await store.get_active_chain(session_id)
    preceding_user_content: str | None = None
    for m in reversed(chain):
        if m.id == message_id:
            # Found the pivot — stop looking forward
            continue
        if m.role == "user":
            preceding_user_content = m.content
            break

    if preceding_user_content is None:
        raise ValidationError(
            f"No preceding user message found before message {message_id!r}."
        )

    # Deactivate from assistant message onward
    count = await store.deactivate_from(session_id, from_message_id=message_id)
    logger.info(
        "regenerate: deactivated %d messages from %s onward (session=%s)",
        count, message_id, session_id,
    )

    # Trigger new turn — insert new user message + run
    turn_loop = get_turn_loop()
    await turn_loop.run_turn_from_api(
        session_id=session_id,
        session_key=session_key,
        user_content=preceding_user_content,
        user_name=user_name,
    )


async def edit_and_resubmit(
    *,
    session_id: str,
    session_key: str,
    message_id: str,
    new_content: str,
    user_name: str = "",
) -> None:
    """Edit a user message and resubmit the conversation from that point.

    1. Verify *message_id* is a user message in *session_id*.
    2. Deactivate from *message_id* onward (marks the old user message inactive).
    3. Run turn loop with *new_content* as the new user message.

    Raises
    ------
    NotFoundError
        If *message_id* doesn't exist.
    ValidationError
        If *message_id* is not a user message.
    """
    from app.agent.turn_loop import get_turn_loop
    from app.sessions.messages import get_message_store

    store = get_message_store()

    # Load and validate the target message
    msg = await store.get(message_id)
    if msg.session_id != session_id:
        raise NotFoundError(resource="Message", id=message_id)
    if msg.role != "user":
        raise ValidationError(
            f"Message {message_id!r} is not a user message (role={msg.role!r})."
        )

    if not new_content or not new_content.strip():
        raise ValidationError("new_content must not be empty.")

    # Deactivate from user message onward
    count = await store.deactivate_from(session_id, from_message_id=message_id)
    logger.info(
        "edit_and_resubmit: deactivated %d messages from %s onward (session=%s)",
        count, message_id, session_id,
    )

    # Run new turn with edited content
    turn_loop = get_turn_loop()
    await turn_loop.run_turn_from_api(
        session_id=session_id,
        session_key=session_key,
        user_content=new_content.strip(),
        user_name=user_name,
    )
