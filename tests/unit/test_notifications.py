"""Sprint 14b — Unit tests for notification system (§24.1–24.5)."""
from __future__ import annotations

import pytest

from app.notifications import (
    Notification,
    NotificationPreference,
    NotificationStore,
    init_notification_store,
)


def _make_notification(**kwargs) -> Notification:
    defaults = {
        "notification_type": "agent.run.error",
        "title": "Test",
        "body": "Test body",
        "severity": "info",
    }
    defaults.update(kwargs)
    return Notification(**defaults)


# ── NotificationStore ─────────────────────────────────────────────────────────


async def test_create_and_list(migrated_db):
    store = init_notification_store(migrated_db)
    n = await store.create(_make_notification(title="Hello"))
    assert n.id
    items = await store.list(unread_only=False)
    assert any(x.id == n.id for x in items)


async def test_list_unread_only(migrated_db):
    store = init_notification_store(migrated_db)
    n = await store.create(_make_notification(title="Unread"))
    items = await store.list(unread_only=True)
    assert any(x.id == n.id for x in items)
    # After mark read it should disappear from unread filter
    await store.mark_read(n.id)
    items2 = await store.list(unread_only=True)
    assert all(x.id != n.id for x in items2)


async def test_mark_read(migrated_db):
    store = init_notification_store(migrated_db)
    n = await store.create(_make_notification())
    assert not n.read
    await store.mark_read(n.id)
    all_items = await store.list(unread_only=False)
    matched = next(x for x in all_items if x.id == n.id)
    assert matched.read


async def test_mark_all_read(migrated_db):
    store = init_notification_store(migrated_db)
    await store.create(_make_notification(title="A"))
    await store.create(_make_notification(title="B"))
    count = await store.mark_all_read()
    assert count >= 2
    assert await store.count_unread() == 0


async def test_count_unread(migrated_db):
    store = init_notification_store(migrated_db)
    before = await store.count_unread()
    await store.create(_make_notification())
    await store.create(_make_notification())
    after = await store.count_unread()
    assert after == before + 2


# ── NotificationPreference ────────────────────────────────────────────────────


async def test_seed_default_preferences(migrated_db):
    store = init_notification_store(migrated_db)
    await store.seed_default_preferences()
    prefs = await store.list_preferences()
    assert len(prefs) >= 2


async def test_upsert_and_get_preference(migrated_db):
    store = init_notification_store(migrated_db)
    pref = NotificationPreference(
        notification_type="test.custom",
        channels=["in_app"],
        enabled=True,
    )
    await store.upsert_preference(pref)
    fetched = await store.get_preference("test.custom")
    assert fetched is not None
    assert fetched.notification_type == "test.custom"
    assert fetched.enabled


async def test_get_preference_wildcard_fallback(migrated_db):
    store = init_notification_store(migrated_db)
    # Seed a wildcard preference
    wildcard = NotificationPreference(
        notification_type="*",
        channels=["in_app"],
        enabled=True,
    )
    await store.upsert_preference(wildcard)
    # Look up a type that has no explicit entry — should fall back to wildcard
    result = await store.get_preference("some.unknown.type")
    assert result is not None
    assert result.notification_type == "*"


async def test_preference_disabled(migrated_db):
    store = init_notification_store(migrated_db)
    pref = NotificationPreference(
        notification_type="budget.warning",
        channels=["in_app"],
        enabled=False,
    )
    await store.upsert_preference(pref)
    fetched = await store.get_preference("budget.warning")
    assert fetched is not None
    assert not fetched.enabled


# ── Notification model ────────────────────────────────────────────────────────


def test_notification_to_row_round_trip():
    n = Notification(
        notification_type="plugin.error",
        title="Plugin crashed",
        body="Full stack trace here",
        severity="error",
        action_url="/plugins",
    )
    row = n.to_row()
    restored = Notification.from_row(row)
    assert restored.notification_type == n.notification_type
    assert restored.title == n.title
    assert restored.severity == n.severity
    assert not restored.read
