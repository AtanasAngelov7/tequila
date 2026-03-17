"""Sprint 14b — Unit tests for AppLockManager (D4)."""
from __future__ import annotations

import asyncio
import pytest

from app.auth.app_lock import AppLockManager, init_app_lock


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _get_manager(db) -> AppLockManager:
    return init_app_lock(db)


# ── Initial state ─────────────────────────────────────────────────────────────


async def test_initial_state(migrated_db):
    lock = await _get_manager(migrated_db)
    state = await lock.get_state()
    assert not state.enabled
    assert not state.locked
    assert not state.has_pin


# ── set_pin returns recovery key ──────────────────────────────────────────────


async def test_set_pin_returns_recovery_key(migrated_db):
    lock = await _get_manager(migrated_db)
    recovery = await lock.set_pin("123456")
    assert recovery is not None
    assert len(recovery) == 24


async def test_set_pin_too_short(migrated_db):
    lock = await _get_manager(migrated_db)
    with pytest.raises(ValueError, match="at least"):
        await lock.set_pin("12345")


async def test_set_pin_enables_lock(migrated_db):
    lock = await _get_manager(migrated_db)
    await lock.set_pin("secure-pin-99")
    state = await lock.get_state()
    assert state.has_pin
    assert state.enabled


# ── verify_pin ────────────────────────────────────────────────────────────────


async def test_verify_pin_correct(migrated_db):
    lock = await _get_manager(migrated_db)
    await lock.set_pin("my-secret-pin")
    await lock.lock()  # Ensure locked first
    success = await lock.verify_pin("my-secret-pin")
    assert success
    assert not await lock.is_locked()


async def test_verify_pin_wrong(migrated_db):
    lock = await _get_manager(migrated_db)
    await lock.set_pin("my-secret-pin")
    await lock.lock()
    success = await lock.verify_pin("wrong-pin")
    assert not success
    assert await lock.is_locked()


# ── verify_recovery_key ───────────────────────────────────────────────────────


async def test_verify_recovery_key(migrated_db):
    lock = await _get_manager(migrated_db)
    recovery = await lock.set_pin("pin1234")
    await lock.lock()
    success = await lock.verify_recovery_key(recovery)
    assert success
    assert not await lock.is_locked()


async def test_verify_recovery_key_wrong(migrated_db):
    lock = await _get_manager(migrated_db)
    await lock.set_pin("pin1234")
    await lock.lock()
    success = await lock.verify_recovery_key("WRONG-RECOVERY-KEY-000000")
    assert not success


# ── lock / unlock ─────────────────────────────────────────────────────────────


async def test_lock_and_unlock(migrated_db):
    lock = await _get_manager(migrated_db)
    await lock.set_pin("test1234")
    assert not await lock.is_locked()
    await lock.lock()
    assert await lock.is_locked()
    await lock.unlock()
    assert not await lock.is_locked()


# ── disable ───────────────────────────────────────────────────────────────────


async def test_disable(migrated_db):
    lock = await _get_manager(migrated_db)
    await lock.set_pin("pin5678")
    await lock.disable()
    state = await lock.get_state()
    assert not state.enabled
    assert not state.has_pin
    assert not state.locked


# ── idle timeout ──────────────────────────────────────────────────────────────


async def test_set_idle_timeout(migrated_db):
    lock = await _get_manager(migrated_db)
    await lock.set_idle_timeout(300)
    state = await lock.get_state()
    assert state.idle_timeout_seconds == 300


async def test_record_activity_resets_timer(migrated_db):
    lock = await _get_manager(migrated_db)
    await lock.set_pin("pin0000")
    lock.record_activity()
    # Calling record_activity should not raise
    lock.record_activity()


# ── recovery key format ───────────────────────────────────────────────────────


def test_recovery_key_alphanumeric():
    import re
    from app.auth.app_lock import AppLockManager
    # _generate_recovery_key is an instance method but only needs self for secrets.choice
    lock = AppLockManager.__new__(AppLockManager)
    key = lock._generate_recovery_key()
    assert len(key) == 24
    assert re.match(r"^[A-Z0-9]{24}$", key), f"Key not alphanumeric: {key}"
