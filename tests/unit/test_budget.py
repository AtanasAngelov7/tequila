"""Sprint 14b — Unit tests for budget tracker (§23.1–23.5)."""
from __future__ import annotations

from datetime import date

import pytest

from app.budget import (
    BudgetCap,
    BudgetTracker,
    ProviderPricing,
    TurnCost,
    init_budget_tracker,
)


def _make_turn_cost(**kwargs) -> TurnCost:
    from datetime import datetime, timezone
    import uuid
    defaults = {
        "turn_id": str(uuid.uuid4()),
        "session_id": "sess-test-001",
        "agent_id": "main",
        "provider_id": "anthropic",
        "model": "claude-sonnet-4-6",
        "input_tokens": 100,
        "output_tokens": 50,
        "cost_usd": 0.001,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    defaults.update(kwargs)
    return TurnCost(**defaults)


# ── Default pricing seeding ───────────────────────────────────────────────────


async def test_seed_default_pricing(migrated_db):
    tracker = init_budget_tracker(migrated_db)
    await tracker.seed_default_pricing()
    pricing = await tracker.list_pricing()
    assert len(pricing) >= 5


async def test_seed_default_pricing_idempotent(migrated_db):
    tracker = init_budget_tracker(migrated_db)
    await tracker.seed_default_pricing()
    await tracker.seed_default_pricing()
    pricing = await tracker.list_pricing()
    # No duplicates
    keys = [(p.provider_id, p.model) for p in pricing]
    assert len(keys) == len(set(keys))


# ── Cost calculation ──────────────────────────────────────────────────────────


async def test_calculate_cost_known_model(migrated_db):
    tracker = init_budget_tracker(migrated_db)
    await tracker.seed_default_pricing()
    cost = await tracker._calculate_cost("anthropic", "claude-sonnet-4-6", 1000, 500)
    assert cost > 0


async def test_calculate_cost_unknown_model_returns_zero(migrated_db):
    tracker = init_budget_tracker(migrated_db)
    await tracker.seed_default_pricing()
    # Unknown model with no wildcard entry
    cost = await tracker._calculate_cost("unknown_provider", "some-model", 100, 50)
    assert cost == 0.0


async def test_calculate_cost_ollama_wildcard(migrated_db):
    tracker = init_budget_tracker(migrated_db)
    await tracker.seed_default_pricing()
    cost = await tracker._calculate_cost("ollama", "mistral", 1000, 500)
    assert cost == 0.0


# ── Upsert + list pricing ─────────────────────────────────────────────────────


async def test_upsert_pricing(migrated_db):
    tracker = init_budget_tracker(migrated_db)
    p = ProviderPricing(
        provider_id="test-provider",
        model="test-model",
        input_cost_per_1k=0.01,
        output_cost_per_1k=0.02,
    )
    await tracker.upsert_pricing(p)
    all_pricing = await tracker.list_pricing()
    match = next((x for x in all_pricing if x.provider_id == "test-provider"), None)
    assert match is not None
    assert match.input_cost_per_1k == 0.01


# ── Budget caps ───────────────────────────────────────────────────────────────


async def test_set_and_get_cap(migrated_db):
    tracker = init_budget_tracker(migrated_db)
    cap = BudgetCap(period="daily", limit_usd=10.0, action="warn")
    await tracker.set_cap(cap)
    caps = await tracker.list_caps()
    daily_cap = next((c for c in caps if c.period == "daily"), None)
    assert daily_cap is not None
    assert daily_cap.limit_usd == 10.0


async def test_delete_cap(migrated_db):
    tracker = init_budget_tracker(migrated_db)
    cap = BudgetCap(period="monthly", limit_usd=100.0, action="warn")
    await tracker.set_cap(cap)
    await tracker.delete_cap("monthly")
    caps = await tracker.list_caps()
    assert not any(c.period == "monthly" for c in caps)


async def test_is_blocked_no_caps(migrated_db):
    tracker = init_budget_tracker(migrated_db)
    # No caps set — should never be blocked
    assert not await tracker.is_blocked()


async def test_is_blocked_warn_cap_not_blocked(migrated_db):
    tracker = init_budget_tracker(migrated_db)
    cap = BudgetCap(period="daily", limit_usd=0.001, action="warn")
    await tracker.set_cap(cap)
    # warn caps do not block
    assert not await tracker.is_blocked()


async def test_is_blocked_block_cap_exceeded(migrated_db):
    """If a block-mode daily cap is at $0.001 and we've spent $1, is_blocked returns True."""
    import uuid
    from datetime import datetime, timezone
    tracker = init_budget_tracker(migrated_db)
    cap = BudgetCap(period="daily", limit_usd=0.001, action="block")
    await tracker.set_cap(cap)
    # Insert a turn cost that exceeds the cap
    tc = TurnCost(
        turn_id=str(uuid.uuid4()),
        session_id="sess-block-test",
        agent_id="main",
        provider_id="test",
        model="m",
        input_tokens=100,
        output_tokens=50,
        cost_usd=1.0,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    await tracker._persist_turn_cost(tc)
    assert await tracker.is_blocked()


# ── Summary queries ───────────────────────────────────────────────────────────


async def test_get_summary_empty(migrated_db):
    tracker = init_budget_tracker(migrated_db)
    from datetime import date
    summary = await tracker.get_summary(period="daily", date_or_month=date.today().isoformat())
    assert summary.total_cost_usd == 0.0
    assert summary.turn_count == 0


async def test_get_summary_with_data(migrated_db):
    import uuid
    from datetime import datetime, timezone
    tracker = init_budget_tracker(migrated_db)
    today = date.today().isoformat()
    tc = TurnCost(
        turn_id=str(uuid.uuid4()),
        session_id="sess-sum",
        agent_id="main",
        provider_id="anthropic",
        model="claude-sonnet-4-6",
        input_tokens=200,
        output_tokens=100,
        cost_usd=0.005,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    await tracker._persist_turn_cost(tc)
    summary = await tracker.get_summary(period="daily", date_or_month=today)
    assert summary.total_cost_usd >= 0.005
    assert summary.turn_count >= 1
