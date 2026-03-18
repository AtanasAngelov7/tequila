"""Sprint 11 — Unit tests for MemoryLifecycleManager (§5.8)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now():
    return datetime.now(timezone.utc)


def _make_memory(
    mid: str,
    *,
    always_recall: bool = False,
    pinned: bool = False,
    decay_score: float = 1.0,
    confidence: float = 1.0,
    status: str = "active",
    memory_type: str = "fact",
    last_accessed: datetime | None = None,
    expires_at: datetime | None = None,
    entity_ids: list[str] | None = None,
):
    m = MagicMock()
    m.id = mid
    m.always_recall = always_recall
    m.pinned = pinned
    m.decay_score = decay_score
    m.confidence = confidence
    m.status = status
    m.memory_type = memory_type
    m.last_accessed = last_accessed or _now()
    m.expires_at = expires_at
    m.entity_ids = entity_ids or []
    m.content = f"Content of {mid}"
    return m


def _make_lifecycle(memories: list, *, entity_ids_map: dict | None = None):
    """Return a MemoryLifecycleManager with a mocked MemoryStore."""
    from app.memory.lifecycle import MemoryLifecycleManager, MemoryDecayConfig, ConsolidationConfig

    mem_store = AsyncMock()
    # Return the given memories on first call, then [] to stop iteration
    calls = [0]

    async def _list(**kwargs):
        if calls[0] == 0:
            calls[0] += 1
            # Filter by memory_type if provided
            mt = kwargs.get("memory_type")
            if mt:
                return [m for m in memories if m.memory_type == mt]
            return list(memories)
        return []

    mem_store.list = _list
    mem_store.update = AsyncMock()
    mem_store.update_decay_scores_bulk = AsyncMock(return_value=1)  # TD-365
    mem_store.soft_delete = AsyncMock()
    mem_store.link_entity = AsyncMock()
    mem_store.unlink_entity = AsyncMock()

    ent_store = AsyncMock()
    ent_store.get_memories = AsyncMock(return_value=[])

    audit = AsyncMock()
    audit.log = AsyncMock()

    mgr = MemoryLifecycleManager(
        memory_store=mem_store,
        entity_store=ent_store,
        audit_log=audit,
        decay_cfg=MemoryDecayConfig(enabled=True, half_life_days=90, floor=0.1),
        consol_cfg=ConsolidationConfig(enabled=True, batch_size=50, archive_threshold=0.15),
    )
    return mgr, mem_store, audit


# ── _compute_decay ────────────────────────────────────────────────────────────


def test_compute_decay_fresh_memory():
    """Memory accessed now has decay_score = 1.0."""
    from app.memory.lifecycle import MemoryLifecycleManager
    score = MemoryLifecycleManager._compute_decay(_now(), 90, 0.1)
    assert abs(score - 1.0) < 0.01


def test_compute_decay_half_life():
    """Memory accessed exactly one half_life ago has decay_score ≈ 0.5."""
    from app.memory.lifecycle import MemoryLifecycleManager
    last = _now() - timedelta(days=90)
    score = MemoryLifecycleManager._compute_decay(last, 90, 0.1)
    assert abs(score - 0.5) < 0.01


def test_compute_decay_floor():
    """Very old memory never drops below floor."""
    from app.memory.lifecycle import MemoryLifecycleManager
    last = _now() - timedelta(days=10000)
    score = MemoryLifecycleManager._compute_decay(last, 90, 0.1)
    assert score == pytest.approx(0.1)


def test_compute_decay_quarter_life():
    """Memory at 0.25 * half_life has score ≈ 2**(−0.25) ≈ 0.84."""
    from app.memory.lifecycle import MemoryLifecycleManager
    import math
    last = _now() - timedelta(days=22.5)
    score = MemoryLifecycleManager._compute_decay(last, 90, 0.1)
    expected = 0.5 ** (22.5 / 90)
    assert abs(score - expected) < 0.005


def test_compute_decay_naive_datetime_handled():
    """Naive (tz-unaware) last_accessed is treated as UTC — no exception."""
    from app.memory.lifecycle import MemoryLifecycleManager
    naive = datetime.utcnow() - timedelta(days=45)
    assert not naive.tzinfo
    score = MemoryLifecycleManager._compute_decay(naive, 90, 0.1)
    assert 0.1 <= score <= 1.0


# ── run_decay ─────────────────────────────────────────────────────────────────


async def test_run_decay_updates_stale_memory():
    """run_decay() calls update() when the score changes significantly."""
    old_ts = _now() - timedelta(days=180)
    mem = _make_memory("m1", last_accessed=old_ts, decay_score=1.0)
    mgr, mem_store, audit = _make_lifecycle([mem])

    result = await mgr.run_decay()

    assert result["updated"] == 1
    assert result["processed"] == 1
    # TD-365: lifecycle now batches updates via update_decay_scores_bulk
    mem_store.update_decay_scores_bulk.assert_called_once()
    scores_list = mem_store.update_decay_scores_bulk.call_args[0][0]
    assert len(scores_list) == 1
    _mem_id, new_score = scores_list[0]
    assert new_score < 1.0


async def test_run_decay_skips_always_recall():
    """run_decay() skips memories with always_recall=True (immune)."""
    mem = _make_memory("m2", always_recall=True, last_accessed=_now() - timedelta(days=365))
    mgr, mem_store, _ = _make_lifecycle([mem])

    result = await mgr.run_decay()

    assert result["skipped"] == 1
    mem_store.update.assert_not_called()


async def test_run_decay_skips_unchanged():
    """run_decay() skips memories whose score changed by < 0.001."""
    # Freshly accessed memory — score stays at 1.0
    mem = _make_memory("m3", last_accessed=_now(), decay_score=1.0)
    mgr, mem_store, _ = _make_lifecycle([mem])

    result = await mgr.run_decay()

    assert result["skipped"] == 1  # score didn't change enough
    mem_store.update.assert_not_called()


async def test_run_decay_disabled(monkeypatch):
    """run_decay() returns zeros when enabled=False."""
    mem = _make_memory("m4", last_accessed=_now() - timedelta(days=200))
    mgr, mem_store, _ = _make_lifecycle([mem])
    mgr.decay_cfg.enabled = False

    result = await mgr.run_decay()

    assert result == {"processed": 0, "updated": 0, "skipped": 0}
    mem_store.update.assert_not_called()


# ── run_archive ───────────────────────────────────────────────────────────────


async def test_run_archive_archives_low_decay(migrated_db):
    """run_archive() archives memories below archive_threshold."""
    from app.memory.lifecycle import MemoryLifecycleManager, ConsolidationConfig

    mem = _make_memory("arch1", decay_score=0.05, always_recall=False, pinned=False)
    mgr, mem_store, audit = _make_lifecycle([mem])

    result = await mgr.run_archive()

    assert result["archived"] == 1
    mem_store.update.assert_called_once_with("arch1", status="archived")


async def test_run_archive_spares_always_recall():
    """run_archive() does not archive always_recall memories."""
    mem = _make_memory("arch2", decay_score=0.05, always_recall=True)
    mgr, mem_store, _ = _make_lifecycle([mem])

    result = await mgr.run_archive()

    assert result["archived"] == 0


async def test_run_archive_spares_pinned():
    """run_archive() does not archive pinned memories."""
    mem = _make_memory("arch3", decay_score=0.05, pinned=True)
    mgr, mem_store, _ = _make_lifecycle([mem])

    result = await mgr.run_archive()

    assert result["archived"] == 0


# ── run_expire_tasks ──────────────────────────────────────────────────────────


async def test_run_expire_tasks_archives_overdue_task():
    """run_expire_tasks() archives tasks past expires_at + grace period."""
    expired = _now() - timedelta(days=10)  # expired 10 days ago
    mem = _make_memory("task1", memory_type="task", expires_at=expired)
    mgr, mem_store, _ = _make_lifecycle([mem])
    mgr.decay_cfg.task_post_expiry_decay_days = 7  # grace = 7 days

    result = await mgr.run_expire_tasks()

    assert result["expired"] == 1
    mem_store.update.assert_called_once_with("task1", status="archived")


async def test_run_expire_tasks_spares_within_grace():
    """run_expire_tasks() does not archive tasks within the grace period."""
    expired = _now() - timedelta(days=3)  # expired 3 days ago
    mem = _make_memory("task2", memory_type="task", expires_at=expired)
    mgr, mem_store, _ = _make_lifecycle([mem])
    mgr.decay_cfg.task_post_expiry_decay_days = 7  # grace = 7 days

    result = await mgr.run_expire_tasks()

    assert result["expired"] == 0


# ── run_orphan_report ─────────────────────────────────────────────────────────


async def test_run_orphan_report_identifies_orphans():
    """run_orphan_report() flags memories with no entity links and old access."""
    old_ts = _now() - timedelta(days=90)
    mem = _make_memory("orp1", entity_ids=[], last_accessed=old_ts)
    mgr, _, _ = _make_lifecycle([mem])
    mgr.consol_cfg.orphan_report_after_days = 60

    result = await mgr.run_orphan_report()

    assert "orp1" in result["orphan_ids"]


async def test_run_orphan_report_spares_recent():
    """run_orphan_report() skips memories accessed recently."""
    fresh_ts = _now() - timedelta(days=5)
    mem = _make_memory("orp2", entity_ids=[], last_accessed=fresh_ts)
    mgr, _, _ = _make_lifecycle([mem])
    mgr.consol_cfg.orphan_report_after_days = 60

    result = await mgr.run_orphan_report()

    assert "orp2" not in result["orphan_ids"]


async def test_run_orphan_report_spares_linked():
    """run_orphan_report() skips memories that have entity links."""
    old_ts = _now() - timedelta(days=90)
    mem = _make_memory("orp3", entity_ids=["e001"], last_accessed=old_ts)
    mgr, _, _ = _make_lifecycle([mem])

    result = await mgr.run_orphan_report()

    assert "orp3" not in result["orphan_ids"]


# ── Singletons ────────────────────────────────────────────────────────────────


def test_get_lifecycle_manager_raises_before_init(monkeypatch):
    """get_lifecycle_manager() raises RuntimeError if not initialised."""
    import app.memory.lifecycle as mod
    monkeypatch.setattr(mod, "_lifecycle_manager", None)
    with pytest.raises(RuntimeError, match="not initialised"):
        mod.get_lifecycle_manager()
