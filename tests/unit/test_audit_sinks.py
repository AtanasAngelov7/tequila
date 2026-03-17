"""Sprint 14b — Unit tests for audit sinks & retention (§12.1–12.3)."""
from __future__ import annotations

import json
import pytest

from app.audit.sinks import (
    AuditRetention,
    AuditSink,
    AuditSinkManager,
    init_audit_sink_manager,
)


def _make_sink(**kwargs) -> AuditSink:
    defaults = {
        "kind": "file",
        "name": "test-sink",
        "config": {"path": "/tmp/test_audit.jsonl"},
        "enabled": True,
    }
    defaults.update(kwargs)
    return AuditSink(**defaults)


# ── Seed defaults ─────────────────────────────────────────────────────────────


async def test_seed_default_sinks(migrated_db):
    mgr = init_audit_sink_manager(migrated_db)
    await mgr.seed_default_sinks()
    sinks = await mgr.list_sinks()
    assert any(s.name == "sqlite_default" for s in sinks)


async def test_seed_default_sinks_idempotent(migrated_db):
    mgr = init_audit_sink_manager(migrated_db)
    await mgr.seed_default_sinks()
    await mgr.seed_default_sinks()
    sinks = await mgr.list_sinks()
    names = [s.name for s in sinks]
    assert names.count("sqlite_default") == 1


async def test_seed_creates_retention_policy(migrated_db):
    mgr = init_audit_sink_manager(migrated_db)
    await mgr.seed_default_sinks()
    sinks = await mgr.list_sinks()
    default_sink = next(s for s in sinks if s.name == "sqlite_default")
    retention = await mgr.get_retention(default_sink.id)
    assert retention is not None
    assert retention.retain_days == 90


# ── CRUD ──────────────────────────────────────────────────────────────────────


async def test_create_and_get_sink(migrated_db):
    mgr = init_audit_sink_manager(migrated_db)
    sink = await mgr.create_sink(_make_sink(name="my-file-sink"))
    assert sink.id
    fetched = await mgr.get_sink(sink.id)
    assert fetched is not None
    assert fetched.name == "my-file-sink"


async def test_list_sinks(migrated_db):
    mgr = init_audit_sink_manager(migrated_db)
    await mgr.create_sink(_make_sink(name="list-test-1"))
    await mgr.create_sink(_make_sink(name="list-test-2"))
    sinks = await mgr.list_sinks()
    names = [s.name for s in sinks]
    assert "list-test-1" in names
    assert "list-test-2" in names


async def test_update_sink(migrated_db):
    mgr = init_audit_sink_manager(migrated_db)
    sink = await mgr.create_sink(_make_sink(name="update-test"))
    updated = await mgr.update_sink(sink.id, enabled=False)
    assert not updated.enabled


async def test_delete_sink(migrated_db):
    mgr = init_audit_sink_manager(migrated_db)
    sink = await mgr.create_sink(_make_sink(name="delete-me"))
    await mgr.delete_sink(sink.id)
    with pytest.raises(KeyError):
        await mgr.get_sink(sink.id)


# ── Retention policies ────────────────────────────────────────────────────────


async def test_set_and_get_retention(migrated_db):
    mgr = init_audit_sink_manager(migrated_db)
    sink = await mgr.create_sink(_make_sink(name="retention-test"))
    policy = AuditRetention(sink_id=sink.id, retain_days=30, max_events=1000)
    await mgr.set_retention(policy)
    fetched = await mgr.get_retention(sink.id)
    assert fetched is not None
    assert fetched.retain_days == 30
    assert fetched.max_events == 1000


async def test_retention_upsert(migrated_db):
    """set_retention should update, not insert duplicate."""
    mgr = init_audit_sink_manager(migrated_db)
    sink = await mgr.create_sink(_make_sink(name="retention-upsert"))
    policy1 = AuditRetention(sink_id=sink.id, retain_days=60)
    await mgr.set_retention(policy1)
    policy2 = AuditRetention(sink_id=sink.id, retain_days=30)
    await mgr.set_retention(policy2)
    fetched = await mgr.get_retention(sink.id)
    assert fetched is not None
    assert fetched.retain_days == 30


# ── Stats ─────────────────────────────────────────────────────────────────────


async def test_stats_empty_db(migrated_db):
    mgr = init_audit_sink_manager(migrated_db)
    stats = await mgr.stats()
    assert "total" in stats
    assert stats["total"] >= 0


# ── apply_retention (pruning) ─────────────────────────────────────────────────


async def test_apply_retention_runs_without_error(migrated_db):
    mgr = init_audit_sink_manager(migrated_db)
    await mgr.seed_default_sinks()
    # Should not raise even with no events to prune
    await mgr.apply_retention()


async def test_prune_sqlite_max_events(migrated_db):
    """Insert events, set max_events=2, apply_retention, verify only 2 remain."""
    from datetime import datetime, timezone
    from app.audit.log import write_audit_event, AuditEvent

    mgr = init_audit_sink_manager(migrated_db)
    await mgr.seed_default_sinks()
    sinks = await mgr.list_sinks()
    sqlite_sink = next(s for s in sinks if s.name == "sqlite_default")

    # Write 5 audit events
    for i in range(5):
        await write_audit_event(
            migrated_db,
            AuditEvent(
                actor="test",
                action=f"test.event.{i}",
                outcome="success",
            ),
        )

    # Set max_events = 2
    policy = AuditRetention(sink_id=sqlite_sink.id, retain_days=365, max_events=2)
    await mgr.set_retention(policy)
    await mgr.apply_retention()

    stats = await mgr.stats()
    assert stats["total"] <= 2
