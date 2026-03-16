"""Sprint 11 — Integration tests for the memory lifecycle pipeline (§5.8)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient


# ── Lifecycle manager availability ───────────────────────────────────────────


async def test_lifecycle_manager_initialised(test_app: AsyncClient):
    """MemoryLifecycleManager is available after startup."""
    from app.memory.lifecycle import get_lifecycle_manager
    mgr = get_lifecycle_manager()
    assert mgr is not None


async def test_lifecycle_decay_config_defaults(test_app: AsyncClient):
    """Lifecycle manager uses spec-default decay parameters (§5.8)."""
    from app.memory.lifecycle import get_lifecycle_manager
    mgr = get_lifecycle_manager()
    assert mgr.decay_cfg.half_life_days == 90
    assert mgr.decay_cfg.floor == 0.1
    assert mgr.decay_cfg.always_recall_immune is True


# ── Decay pass ────────────────────────────────────────────────────────────────


async def test_run_decay_does_not_raise(test_app: AsyncClient):
    """run_decay() completes without exception on a fresh database."""
    from app.memory.lifecycle import get_lifecycle_manager
    mgr = get_lifecycle_manager()
    result = await mgr.run_decay()
    assert isinstance(result, dict)
    assert "processed" in result


async def test_run_decay_updates_old_memory(test_app: AsyncClient):
    """A memory last accessed 180 days ago gets a reduced decay_score after run_decay()."""
    from app.memory.store import get_memory_store
    from app.memory.lifecycle import get_lifecycle_manager

    store = get_memory_store()
    old_ts = datetime.now(timezone.utc) - timedelta(days=180)

    # Create a memory through the store so it ends up in DB
    mem = await store.create(
        content="Very old fact that should decay.",
        memory_type="fact",
        source_type="user_created",
    )
    # Manually backdate last_accessed by updating directly
    await store.update(mem.id, decay_score=1.0)  # Ensure starting at 1.0

    # Update access time manually via DB
    import aiosqlite
    from app.db.connection import get_app_db
    db = get_app_db()
    from app.db.connection import write_transaction
    async with write_transaction(db):
        await db.execute(
            "UPDATE memory_extracts SET last_accessed = ? WHERE id = ?",
            (old_ts.isoformat(), mem.id),
        )

    mgr = get_lifecycle_manager()
    result = await mgr.run_decay()
    assert result["updated"] >= 1

    updated = await store.get(mem.id)
    assert updated.decay_score < 0.9  # Should have decayed from 1.0


# ── Archive pass ──────────────────────────────────────────────────────────────


async def test_run_archive_archives_low_decay_memory(test_app: AsyncClient):
    """run_archive() sets status='archived' for a memory with very low decay_score."""
    from app.memory.store import get_memory_store
    from app.memory.lifecycle import get_lifecycle_manager

    store = get_memory_store()
    mem = await store.create(
        content="This memory should be archived soon.",
        memory_type="fact",
        source_type="user_created",
    )
    # Push decay_score below archive_threshold
    await store.update(mem.id, decay_score=0.05)

    mgr = get_lifecycle_manager()
    result = await mgr.run_archive()
    assert result["archived"] >= 1

    archived = await store.get(mem.id)
    assert archived.status == "archived"


# ── Orphan report ─────────────────────────────────────────────────────────────


async def test_run_orphan_report_finds_unlinked_memory(test_app: AsyncClient):
    """run_orphan_report() flags a memory with no entity links and old access."""
    from app.memory.store import get_memory_store
    from app.memory.lifecycle import get_lifecycle_manager
    from app.db.connection import get_app_db, write_transaction

    store = get_memory_store()
    mem = await store.create(
        content="Orphan memory with no entity links.",
        memory_type="fact",
        source_type="user_created",
    )
    # Backdate last_accessed to past the orphan threshold
    old_ts = datetime.now(timezone.utc) - timedelta(days=90)
    db = get_app_db()
    async with write_transaction(db):
        await db.execute(
            "UPDATE memory_extracts SET last_accessed = ?, entity_ids = '[]' WHERE id = ?",
            (old_ts.isoformat(), mem.id),
        )

    mgr = get_lifecycle_manager()
    mgr.consol_cfg.orphan_report_after_days = 60

    result = await mgr.run_orphan_report()

    assert mem.id in result["orphan_ids"]


# ── run_all ───────────────────────────────────────────────────────────────────


async def test_run_all_completes_all_passes(test_app: AsyncClient):
    """run_all() runs all sub-passes and returns a composite result dict."""
    from app.memory.lifecycle import get_lifecycle_manager

    mgr = get_lifecycle_manager()
    result = await mgr.run_all()

    assert "decay" in result
    assert "archive" in result
    assert "expire_tasks" in result
    assert "orphan_report" in result
