"""Sprint 11 — Unit tests for MemoryAuditLog (§5.9)."""
from __future__ import annotations

import pytest


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
async def audit(migrated_db):
    """Initialise the MemoryAuditLog with a fresh in-memory database."""
    from app.memory.audit import MemoryAuditLog
    return MemoryAuditLog(migrated_db)


# ── log() ─────────────────────────────────────────────────────────────────────


async def test_log_creates_event(audit):
    """log() returns a MemoryEvent with correct fields."""
    event = await audit.log(
        event_type="created",
        memory_id="m001",
        actor="agent",
        new_content="The user likes coffee.",
    )
    assert event.event_type == "created"
    assert event.memory_id == "m001"
    assert event.actor == "agent"
    assert event.new_content == "The user likes coffee."
    assert event.id is not None  # UUID assigned


async def test_log_entity_event(audit):
    """log() accepts entity_id and actor_id."""
    event = await audit.log(
        event_type="entity_created",
        entity_id="e001",
        actor="extraction_pipeline",
        actor_id="session-42",
    )
    assert event.entity_id == "e001"
    assert event.actor_id == "session-42"


async def test_log_stores_metadata(audit):
    """log() round-trips the metadata dict."""
    meta = {"similarity": 0.95, "merged_into": "m002"}
    event = await audit.log(
        event_type="merged",
        memory_id="m003",
        actor="consolidation",
        metadata=meta,
    )
    assert event.metadata == meta


# ── get_memory_history() ──────────────────────────────────────────────────────


async def test_get_memory_history_filters_by_id(audit):
    """get_memory_history() returns only events for the given memory_id."""
    await audit.log(event_type="created", memory_id="mA", actor="agent")
    await audit.log(event_type="updated", memory_id="mA", actor="agent")
    await audit.log(event_type="created", memory_id="mB", actor="agent")

    history = await audit.get_memory_history("mA")
    assert all(e.memory_id == "mA" for e in history)
    assert len(history) == 2


async def test_get_memory_history_newest_first(audit):
    """get_memory_history() returns events in descending timestamp order."""
    await audit.log(event_type="created", memory_id="mZ", actor="agent")
    await audit.log(event_type="updated", memory_id="mZ", actor="agent")

    history = await audit.get_memory_history("mZ")
    assert history[0].event_type == "updated"
    assert history[1].event_type == "created"


async def test_get_memory_history_empty(audit):
    """get_memory_history() returns [] for unknown memory_id."""
    result = await audit.get_memory_history("nonexistent")
    assert result == []


# ── get_entity_history() ──────────────────────────────────────────────────────


async def test_get_entity_history_filters(audit):
    """get_entity_history() returns only events for the given entity_id."""
    await audit.log(event_type="entity_created", entity_id="eX", actor="system")
    await audit.log(event_type="entity_updated", entity_id="eX", actor="agent")
    await audit.log(event_type="entity_created", entity_id="eY", actor="system")

    history = await audit.get_entity_history("eX")
    assert len(history) == 2
    assert all(e.entity_id == "eX" for e in history)


# ── get_global_feed() ─────────────────────────────────────────────────────────


async def test_get_global_feed_returns_all(audit):
    """get_global_feed() returns events in descending order."""
    await audit.log(event_type="created", memory_id="m1", actor="agent")
    await audit.log(event_type="updated", memory_id="m2", actor="system")

    feed = await audit.get_global_feed()
    assert len(feed) >= 2


async def test_get_global_feed_filter_by_event_type(audit):
    """get_global_feed(event_type=...) filters correctly."""
    await audit.log(event_type="pinned", memory_id="p1", actor="agent")
    await audit.log(event_type="unpinned", memory_id="p2", actor="agent")
    await audit.log(event_type="pinned", memory_id="p3", actor="agent")

    feed = await audit.get_global_feed(event_type="pinned")
    assert all(e.event_type == "pinned" for e in feed)
    assert len(feed) >= 2


async def test_get_global_feed_filter_by_actor(audit):
    """get_global_feed(actor=...) filters correctly."""
    await audit.log(event_type="created", memory_id="a1", actor="agent")
    await audit.log(event_type="created", memory_id="a2", actor="consolidation")

    feed = await audit.get_global_feed(actor="agent")
    assert all(e.actor == "agent" for e in feed)


async def test_get_global_feed_pagination(audit):
    """get_global_feed() respects limit and offset."""
    for i in range(5):
        await audit.log(event_type="created", memory_id=f"page{i}", actor="system")

    page1 = await audit.get_global_feed(limit=2, offset=0)
    page2 = await audit.get_global_feed(limit=2, offset=2)

    ids1 = {e.id for e in page1}
    ids2 = {e.id for e in page2}
    assert len(ids1) == 2
    assert len(ids2) == 2
    assert ids1.isdisjoint(ids2)


# ── Singletons ────────────────────────────────────────────────────────────────


def test_get_memory_audit_raises_before_init(monkeypatch):
    """get_memory_audit() raises RuntimeError if not initialised."""
    import app.memory.audit as mod
    monkeypatch.setattr(mod, "_audit", None)
    with pytest.raises(RuntimeError, match="not initialised"):
        mod.get_memory_audit()


async def test_init_and_get_memory_audit(migrated_db):
    """init_memory_audit() followed by get_memory_audit() returns the instance."""
    from app.memory.audit import init_memory_audit, get_memory_audit, MemoryAuditLog
    inst = init_memory_audit(migrated_db)
    assert isinstance(inst, MemoryAuditLog)
    assert get_memory_audit() is inst
