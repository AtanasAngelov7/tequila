"""Unit tests for session title defaults and manual rename (Sprint 03, D3).

Covers:
- Default title "New Session" for user kind
- Default titles for channel, cron, webhook, agent kinds
- Manual title override via create() argument
- Manual rename via store.update()
- Session key includes UUID suffix to prevent collisions
"""
from __future__ import annotations

import pytest

from app.sessions.store import SessionStore, init_session_store


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _make_store(db) -> SessionStore:
    return init_session_store(db)


# ── Default titles ────────────────────────────────────────────────────────────


async def test_user_session_default_title(migrated_db):
    """User sessions default to 'New Session'."""
    store = await _make_store(migrated_db)
    session = await store.create(kind="user")
    assert session.title == "New Session"


async def test_explicit_title_preserved(migrated_db):
    """An explicitly supplied title is not overridden."""
    store = await _make_store(migrated_db)
    session = await store.create(title="Custom Title", kind="user")
    assert session.title == "Custom Title"


async def test_channel_session_default_title(migrated_db):
    """Channel sessions include the channel name + sender."""
    store = await _make_store(migrated_db)
    session = await store.create(
        session_key="channel:telegram:alice",
        kind="channel",
        channel="telegram",
        metadata={"sender": "Alice"},
    )
    assert session.title == "Telegram: Alice"


async def test_channel_session_default_title_unknown_sender(migrated_db):
    """Channel session with no sender metadata defaults to 'unknown'."""
    store = await _make_store(migrated_db)
    session = await store.create(
        session_key="channel:telegram:noone",
        kind="channel",
        channel="telegram",
    )
    assert session.title == "Telegram: unknown"


async def test_cron_session_default_title(migrated_db):
    """Cron sessions use job_name from metadata."""
    store = await _make_store(migrated_db)
    session = await store.create(
        session_key="cron:daily-digest",
        kind="cron",
        metadata={"job_name": "Daily Digest"},
    )
    assert session.title == "Daily Digest"


async def test_cron_session_fallback_title(migrated_db):
    """Cron session with no job_name falls back to 'Scheduled Task'."""
    store = await _make_store(migrated_db)
    session = await store.create(
        session_key="cron:unnamed",
        kind="cron",
    )
    assert session.title == "Scheduled Task"


async def test_webhook_session_default_title(migrated_db):
    """Webhook sessions use webhook_label from metadata."""
    store = await _make_store(migrated_db)
    session = await store.create(
        session_key="webhook:github-push",
        kind="webhook",
        metadata={"webhook_label": "GitHub Push"},
    )
    assert session.title == "GitHub Push"


async def test_webhook_session_fallback_title(migrated_db):
    """Webhook session with no label falls back to 'Webhook Task'."""
    store = await _make_store(migrated_db)
    session = await store.create(
        session_key="webhook:unlabelled",
        kind="webhook",
    )
    assert session.title == "Webhook Task"


async def test_agent_session_default_title(migrated_db):
    """Agent sessions include the agent_id in the title."""
    store = await _make_store(migrated_db)
    session = await store.create(
        session_key="agent:worker:001",
        kind="agent",
        agent_id="worker-agent",
    )
    assert session.title == "Agent: worker-agent"


# ── Session key uniqueness ────────────────────────────────────────────────────


async def test_two_user_sessions_get_unique_keys(migrated_db):
    """Two default user sessions should not collide on session_key."""
    store = await _make_store(migrated_db)
    s1 = await store.create(kind="user")
    s2 = await store.create(kind="user")
    assert s1.session_key != s2.session_key
    assert s1.session_key.startswith("user:main:")
    assert s2.session_key.startswith("user:main:")


# ── Manual rename ──────────────────────────────────────────────────────────────


async def test_manual_rename(migrated_db):
    """store.update() with a title changes the session title."""
    store = await _make_store(migrated_db)
    session = await store.create(session_key="user:rename-test", kind="user")
    assert session.title == "New Session"
    renamed = await store.update(session.session_id, title="My Renamed Session")
    assert renamed.title == "My Renamed Session"


async def test_rename_does_not_change_other_fields(migrated_db):
    """Rename via update() must not touch kind, status, or message_count."""
    store = await _make_store(migrated_db)
    session = await store.create(session_key="user:rename-fields")
    original_status = session.status
    original_kind = session.kind
    updated = await store.update(session.session_id, title="New Name")
    assert updated.status == original_status
    assert updated.kind == original_kind
    assert updated.message_count == session.message_count
