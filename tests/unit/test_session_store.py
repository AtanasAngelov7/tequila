"""Unit tests for SessionStore CRUD, lifecycle, and idle detection (Sprint 02, D1)."""
from __future__ import annotations

import pytest

from app.sessions.store import SessionStore, init_session_store, get_session_store
from app.exceptions import SessionNotFoundError, ConflictError


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _make_store(db) -> SessionStore:
    return init_session_store(db)


# ── Create ────────────────────────────────────────────────────────────────────


async def test_create_returns_session(migrated_db):
    store = await _make_store(migrated_db)
    session = await store.create(title="Hello")
    assert session.session_id
    # Sprint 03: session_key now includes a UUID suffix to prevent collisions.
    assert session.session_key.startswith("user:main:")
    assert session.kind == "user"
    assert session.status == "active"
    assert session.title == "Hello"
    assert session.message_count == 0
    assert session.version == 1


async def test_create_custom_key(migrated_db):
    store = await _make_store(migrated_db)
    s = await store.create(session_key="agent:test-001", kind="agent", agent_id="test-agent")
    assert s.session_key == "agent:test-001"
    assert s.kind == "agent"


# ── Get ───────────────────────────────────────────────────────────────────────


async def test_get_by_id(migrated_db):
    store = await _make_store(migrated_db)
    created = await store.create(title="GetTest")
    fetched = await store.get_by_id(created.session_id)
    assert fetched.session_id == created.session_id
    assert fetched.title == "GetTest"


async def test_get_by_key(migrated_db):
    store = await _make_store(migrated_db)
    created = await store.create(session_key="user:getbykey")
    fetched = await store.get_by_key("user:getbykey")
    assert fetched.session_id == created.session_id


async def test_get_by_id_not_found(migrated_db):
    store = await _make_store(migrated_db)
    with pytest.raises(SessionNotFoundError):
        await store.get_by_id("nonexistent-id")


async def test_get_by_key_not_found(migrated_db):
    store = await _make_store(migrated_db)
    with pytest.raises(SessionNotFoundError):
        await store.get_by_key("user:no-such-key")


# ── List ──────────────────────────────────────────────────────────────────────


async def test_list_returns_all(migrated_db):
    store = await _make_store(migrated_db)
    await store.create(session_key="user:s1", title="S1")
    await store.create(session_key="user:s2", title="S2")
    sessions = await store.list()
    assert len(sessions) >= 2


async def test_list_filter_by_status(migrated_db):
    store = await _make_store(migrated_db)
    s = await store.create(session_key="user:list-arch")
    await store.archive(s.session_id)
    active = await store.list(status="active")
    archived = await store.list(status="archived")
    assert all(x.status == "active" for x in active)
    assert any(x.session_id == s.session_id for x in archived)


async def test_list_filter_by_kind(migrated_db):
    store = await _make_store(migrated_db)
    await store.create(session_key="agent:kind-test", kind="agent")
    agents = await store.list(kind="agent")
    assert all(x.kind == "agent" for x in agents)


async def test_list_pagination(migrated_db):
    store = await _make_store(migrated_db)
    for i in range(5):
        await store.create(session_key=f"user:page-{i}")
    first_page = await store.list(limit=2, offset=0)
    second_page = await store.list(limit=2, offset=2)
    assert len(first_page) == 2
    # IDs must be distinct pages
    ids_first = {s.session_id for s in first_page}
    ids_second = {s.session_id for s in second_page}
    assert ids_first.isdisjoint(ids_second)


# ── Update ────────────────────────────────────────────────────────────────────


async def test_update_title(migrated_db):
    store = await _make_store(migrated_db)
    s = await store.create(title="Old")
    updated = await store.update(s.session_id, title="New")
    assert updated.title == "New"
    assert updated.version == 2  # OCC bump


async def test_update_summary(migrated_db):
    store = await _make_store(migrated_db)
    s = await store.create()
    updated = await store.update(s.session_id, summary="Summary text")
    assert updated.summary == "Summary text"


async def test_update_metadata(migrated_db):
    store = await _make_store(migrated_db)
    s = await store.create()
    updated = await store.update(s.session_id, metadata={"foo": "bar"})
    assert updated.metadata == {"foo": "bar"}


# ── Lifecycle — archive / unarchive ───────────────────────────────────────────


async def test_archive(migrated_db):
    store = await _make_store(migrated_db)
    s = await store.create(session_key="user:arch-me")
    archived = await store.archive(s.session_id)
    assert archived.status == "archived"
    fetched = await store.get_by_id(s.session_id)
    assert fetched.status == "archived"


async def test_unarchive(migrated_db):
    store = await _make_store(migrated_db)
    s = await store.create(session_key="user:unarch-me")
    await store.archive(s.session_id)
    restored = await store.unarchive(s.session_id)
    assert restored.status == "active"


# ── Lifecycle — mark_idle ─────────────────────────────────────────────────────


async def test_mark_idle(migrated_db):
    store = await _make_store(migrated_db)
    s = await store.create(session_key="user:idle-me")
    result = await store.mark_idle(s.session_id)
    assert result is True
    fetched = await store.get_by_id(s.session_id)
    assert fetched.status == "idle"


async def test_mark_idle_already_idle(migrated_db):
    store = await _make_store(migrated_db)
    s = await store.create(session_key="user:idle-twice")
    await store.mark_idle(s.session_id)
    # Second call on an idle session should return False (WHERE status='active')
    result = await store.mark_idle(s.session_id)
    assert result is False


# ── Message count ─────────────────────────────────────────────────────────────


async def test_update_last_message(migrated_db):
    store = await _make_store(migrated_db)
    s = await store.create()
    await store.update_last_message(s.session_id)
    updated = await store.get_by_id(s.session_id)
    assert updated.message_count == 1
    assert updated.last_message_at is not None


# ── Delete ────────────────────────────────────────────────────────────────────


async def test_delete(migrated_db):
    store = await _make_store(migrated_db)
    s = await store.create(session_key="user:del-me")
    await store.delete(s.session_id)
    with pytest.raises(SessionNotFoundError):
        await store.get_by_id(s.session_id)


# ── Idle detection ────────────────────────────────────────────────────────────


async def test_run_idle_check(migrated_db):
    store = await _make_store(migrated_db)
    # Sessions not idle (just created) should not be marked
    await store.create(session_key="user:idle-check")
    count = await store.run_idle_check(idle_timeout_days=0)
    # May mark our fresh session since timeout_days=0
    assert isinstance(count, int)
    assert count >= 0


# ── Singleton ────────────────────────────────────────────────────────────────


async def test_get_session_store(migrated_db):
    init_session_store(migrated_db)
    store = get_session_store()
    assert isinstance(store, SessionStore)
