"""Unit tests for Sprint 13 D7 — Scheduler (cronparser, models, store, engine)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.scheduler.cronparser import next_run, validate_cron
from app.scheduler.models import ScheduledTask


# ── CronParser ────────────────────────────────────────────────────────────────


def test_validate_cron_accepts_valid():
    assert validate_cron("* * * * *") is True
    assert validate_cron("0 9 * * 1") is True
    assert validate_cron("*/15 * * * *") is True
    assert validate_cron("0 0 1 * *") is True
    assert validate_cron("30 14 15 3 0") is True  # 14:30 on March 15th if it's Sunday


def test_validate_cron_rejects_invalid():
    assert validate_cron("") is False
    assert validate_cron("a b c d e") is False
    assert validate_cron("* * * *") is False       # only 4 fields
    assert validate_cron("0 9 * * 1 extra") is False  # 6 fields


def test_next_run_returns_future():
    now = datetime.now(UTC)
    nxt = next_run("* * * * *", after=now)
    assert nxt is not None
    assert nxt > now


def test_next_run_hourly():
    base = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    nxt = next_run("0 * * * *", after=base)
    assert nxt is not None
    assert nxt.minute == 0
    assert nxt.hour == 13


def test_next_run_specific_time():
    """Test that next_run finds the next occurrence of a specific time."""
    base = datetime(2025, 1, 1, 8, 0, 0, tzinfo=UTC)
    # Should fire at 9:00 the same day
    nxt = next_run("0 9 * * *", after=base)
    assert nxt.hour == 9
    assert nxt.minute == 0
    assert nxt > base


def test_next_run_invalid_raises():
    with pytest.raises((ValueError, Exception)):
        next_run("not-valid", after=datetime.now(UTC))


def test_next_run_advances_past_now():
    """next_run always returns a time strictly after 'after'."""
    now = datetime.now(UTC)
    nxt = next_run("*/5 * * * *", after=now)
    assert nxt > now


# ── ScheduledTask model ───────────────────────────────────────────────────────


def test_scheduled_task_defaults():
    now = datetime.now(UTC)
    task = ScheduledTask(
        id="test-id",
        name="Test Task",
        cron_expression="* * * * *",
        agent_id="default-agent",
        prompt_template="hello",
        created_at=now,
        updated_at=now,
    )
    assert task.enabled is True
    assert task.run_count == 0
    assert task.last_run_at is None
    assert task.last_run_status is None
    assert task.agent_id == "default-agent"


def test_scheduled_task_with_all_fields():
    now = datetime.now(UTC)
    task = ScheduledTask(
        id="full-task",
        name="Full",
        cron_expression="0 9 * * 1",
        prompt_template="Do the thing",
        description="Fires weekly",
        agent_id="agent-abc",
        enabled=False,
        announce=True,
        run_count=5,
        created_at=now,
        updated_at=now,
    )
    assert task.description == "Fires weekly"
    assert task.agent_id == "agent-abc"
    assert task.enabled is False
    assert task.announce is True
    assert task.run_count == 5


# ── Store ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_save_and_get(migrated_db):
    from app.scheduler.store import load_task, save_task

    now = datetime.now(UTC)
    task = ScheduledTask(
        id="t1",
        name="Daily",
        cron_expression="0 9 * * *",
        agent_id="test-agent",
        prompt_template="go",
        created_at=now,
        updated_at=now,
    )
    await save_task(task, migrated_db)
    loaded = await load_task("t1", migrated_db)
    assert loaded is not None
    assert loaded.name == "Daily"
    assert loaded.cron_expression == "0 9 * * *"


@pytest.mark.asyncio
async def test_store_list_all(migrated_db):
    from app.scheduler.store import load_all_tasks, save_task

    now = datetime.now(UTC)
    for i in range(3):
        await save_task(ScheduledTask(
            id=f"task-{i}",
            name=f"Task {i}",
            cron_expression="* * * * *",
            agent_id="test-agent",
            prompt_template="ping",
            created_at=now,
            updated_at=now,
        ), migrated_db)
    all_tasks = await load_all_tasks(migrated_db)
    assert len(all_tasks) >= 3


@pytest.mark.asyncio
async def test_store_delete(migrated_db):
    from app.scheduler.store import delete_task, load_task, save_task

    now = datetime.now(UTC)
    await save_task(ScheduledTask(
        id="del-me",
        name="Delete Me",
        cron_expression="* * * * *",
        agent_id="test-agent",
        prompt_template="ping",
        created_at=now,
        updated_at=now,
    ), migrated_db)
    await delete_task("del-me", migrated_db)
    gone = await load_task("del-me", migrated_db)
    assert gone is None


@pytest.mark.asyncio
async def test_store_get_nonexistent_returns_none(migrated_db):
    from app.scheduler.store import load_task

    result = await load_task("no-such-id", migrated_db)
    assert result is None


# ── Engine tick logic ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_skips_disabled_task(migrated_db):
    """Tasks with enabled=False must not be in the enabled tasks list."""
    from app.scheduler.store import load_enabled_tasks, save_task

    now = datetime.now(UTC)
    task = ScheduledTask(
        id="disabled-task",
        name="Disabled",
        cron_expression="* * * * *",
        agent_id="test-agent",
        prompt_template="hello",
        enabled=False,
        created_at=now,
        updated_at=now,
    )
    await save_task(task, migrated_db)

    enabled = await load_enabled_tasks(migrated_db)
    ids = {t.id for t in enabled}
    assert "disabled-task" not in ids


@pytest.mark.asyncio
async def test_engine_includes_enabled_task(migrated_db):
    """Tasks with enabled=True must appear in load_enabled_tasks."""
    from app.scheduler.store import load_enabled_tasks, save_task

    now = datetime.now(UTC)
    task = ScheduledTask(
        id="enabled-task",
        name="Enabled",
        cron_expression="* * * * *",
        agent_id="test-agent",
        prompt_template="hello",
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    await save_task(task, migrated_db)

    enabled = await load_enabled_tasks(migrated_db)
    ids = {t.id for t in enabled}
    assert "enabled-task" in ids
