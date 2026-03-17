"""App lock — PIN/password protection for local app access (Sprint 14b D4).

Provides:
  - ``AppLock`` model: enable, set PIN, verify PIN, idle timeout.
  - PIN stored as bcrypt hash (never in plaintext).
  - Recovery key for emergency unlock (bcrypt hash stored, key shown once).
  - ``AppLockManager.is_locked()`` — checked by API middleware.

The ``app_lock`` table has exactly one row (id = 1).
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import string
from datetime import datetime, timezone
from typing import Any

import aiosqlite
import bcrypt
from pydantic import BaseModel

from app.db.connection import write_transaction

logger = logging.getLogger(__name__)

# ── Models ────────────────────────────────────────────────────────────────────


class AppLockState(BaseModel):
    """Current app lock configuration."""

    enabled: bool = False
    idle_timeout_seconds: int = 0
    """0 = no auto-lock."""
    locked: bool = False
    has_pin: bool = False
    has_recovery_key: bool = False


# ── Manager ───────────────────────────────────────────────────────────────────


class AppLockManager:
    """Manages PIN-based application locking.

    The lock state is stored in the ``app_lock`` SQLite table (single row).
    Hashing uses bcrypt with a cost factor of 12.
    """

    _BCRYPT_ROUNDS = 12
    _MAX_ATTEMPTS = 5
    _LOCKOUT_SECONDS = 300  # 5 minute lockout after max attempts

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db
        self._last_activity: datetime = datetime.now(timezone.utc)
        self._idle_task: asyncio.Task[None] | None = None
        # TD-147: Brute-force protection
        self._failed_attempts: int = 0
        self._lockout_until: datetime | None = None

    # ── State ─────────────────────────────────────────────────────────────

    async def get_state(self) -> AppLockState:
        cursor = await self._db.execute(
            "SELECT enabled, idle_timeout_seconds, locked, "
            "pin_hash IS NOT NULL as has_pin, "
            "recovery_key_hash IS NOT NULL as has_key "
            "FROM app_lock WHERE id = 1"
        )
        row = await cursor.fetchone()
        if not row:
            return AppLockState()
        d = dict(row)
        return AppLockState(
            enabled=bool(d.get("enabled", 0)),
            idle_timeout_seconds=int(d.get("idle_timeout_seconds", 0)),
            locked=bool(d.get("locked", 0)),
            has_pin=bool(d.get("has_pin", 0)),
            has_recovery_key=bool(d.get("has_key", 0)),
        )

    async def is_locked(self) -> bool:
        state = await self.get_state()
        return state.enabled and state.locked

    async def lock(self) -> None:
        """Engage the lock screen."""
        async with write_transaction(self._db):
            await self._db.execute(
                "UPDATE app_lock SET locked = 1, updated_at = ? WHERE id = 1",
                (datetime.now(timezone.utc).isoformat(),),
            )
        logger.info("App locked.")

    async def unlock(self) -> bool:
        """Clear the lock without PIN — used internally after successful verify."""
        async with write_transaction(self._db):
            await self._db.execute(
                "UPDATE app_lock SET locked = 0, updated_at = ? WHERE id = 1",
                (datetime.now(timezone.utc).isoformat(),),
            )
        self._last_activity = datetime.now(timezone.utc)
        logger.info("App unlocked.")
        return True

    # ── PIN ───────────────────────────────────────────────────────────────

    async def set_pin(self, pin: str) -> str:
        """Set a new PIN. Returns the one-time recovery key (show it once!)."""
        if len(pin) < 6:
            raise ValueError("PIN must be at least 6 characters")
        if len(pin) > 72:
            raise ValueError("PIN must be at most 72 characters (bcrypt limit)")
        pin_hash = await asyncio.to_thread(
            bcrypt.hashpw, pin.encode(), bcrypt.gensalt(self._BCRYPT_ROUNDS)
        )
        recovery_key = self._generate_recovery_key()
        recovery_hash = await asyncio.to_thread(
            bcrypt.hashpw, recovery_key.encode(), bcrypt.gensalt(self._BCRYPT_ROUNDS)
        )
        async with write_transaction(self._db):
            await self._db.execute(
                "UPDATE app_lock SET pin_hash = ?, recovery_key_hash = ?, "
                "enabled = 1, updated_at = ? WHERE id = 1",
                (pin_hash.decode(), recovery_hash.decode(),
                 datetime.now(timezone.utc).isoformat()),
            )
        logger.info("App lock PIN set.")
        return recovery_key  # shown once to the user

    def _check_lockout(self) -> None:
        """Raise ValueError if currently locked out from brute-force protection."""
        if self._lockout_until and datetime.now(timezone.utc) < self._lockout_until:
            remaining = int((self._lockout_until - datetime.now(timezone.utc)).total_seconds())
            raise ValueError(f"Too many failed attempts. Try again in {remaining}s.")
        if self._lockout_until and datetime.now(timezone.utc) >= self._lockout_until:
            # Lockout expired — reset
            self._failed_attempts = 0
            self._lockout_until = None

    def _record_failed_attempt(self) -> None:
        """Track a failed verification attempt; engage lockout if threshold reached."""
        self._failed_attempts += 1
        if self._failed_attempts >= self._MAX_ATTEMPTS:
            from datetime import timedelta
            self._lockout_until = datetime.now(timezone.utc) + timedelta(seconds=self._LOCKOUT_SECONDS)
            logger.warning("Brute-force lockout engaged for %ds after %d failed attempts.",
                           self._LOCKOUT_SECONDS, self._failed_attempts)

    async def verify_pin(self, pin: str) -> bool:
        """Verify PIN and unlock on success."""
        self._check_lockout()
        cursor = await self._db.execute(
            "SELECT pin_hash FROM app_lock WHERE id = 1"
        )
        row = await cursor.fetchone()
        if not row or not row[0]:
            return False
        stored_hash: str = row[0]
        try:
            match = await asyncio.to_thread(
                bcrypt.checkpw, pin.encode(), stored_hash.encode()
            )
        except Exception:
            self._record_failed_attempt()
            return False
        if match:
            self._failed_attempts = 0
            self._lockout_until = None
            await self.unlock()
        else:
            self._record_failed_attempt()
        return match

    async def verify_recovery_key(self, key: str) -> bool:
        """Verify emergency recovery key and unlock on success."""
        self._check_lockout()
        cursor = await self._db.execute(
            "SELECT recovery_key_hash FROM app_lock WHERE id = 1"
        )
        row = await cursor.fetchone()
        if not row or not row[0]:
            return False
        stored_hash: str = row[0]
        try:
            match = await asyncio.to_thread(
                bcrypt.checkpw, key.encode(), stored_hash.encode()
            )
        except Exception:
            self._record_failed_attempt()
            return False
        if match:
            self._failed_attempts = 0
            self._lockout_until = None
            await self.unlock()
        else:
            self._record_failed_attempt()
        return match

    async def disable(self) -> None:
        """Disable app lock entirely (removes PIN and recovery key)."""
        async with write_transaction(self._db):
            await self._db.execute(
                "UPDATE app_lock SET enabled = 0, locked = 0, "
                "pin_hash = NULL, recovery_key_hash = NULL, updated_at = ? WHERE id = 1",
                (datetime.now(timezone.utc).isoformat(),),
            )

    async def set_idle_timeout(self, seconds: int) -> None:
        async with write_transaction(self._db):
            await self._db.execute(
                "UPDATE app_lock SET idle_timeout_seconds = ?, updated_at = ? WHERE id = 1",
                (max(0, seconds), datetime.now(timezone.utc).isoformat()),
            )

    # ── Idle timeout ──────────────────────────────────────────────────────

    def record_activity(self) -> None:
        """Call on every API request to reset the idle timer."""
        self._last_activity = datetime.now(timezone.utc)

    async def start_idle_watcher(self) -> None:
        """Start background task that auto-locks after idle_timeout_seconds."""
        self._idle_task = asyncio.create_task(self._idle_loop())

    async def stop_idle_watcher(self) -> None:
        if self._idle_task:
            self._idle_task.cancel()
            try:
                await self._idle_task
            except asyncio.CancelledError:
                pass

    async def _idle_loop(self) -> None:
        while True:
            await asyncio.sleep(30)  # Check every 30 seconds
            try:
                state = await self.get_state()
                if not state.enabled or state.locked or state.idle_timeout_seconds <= 0:
                    continue
                idle_secs = (
                    datetime.now(timezone.utc) - self._last_activity
                ).total_seconds()
                if idle_secs >= state.idle_timeout_seconds:
                    await self.lock()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("Idle watcher error: %s", exc)

    @staticmethod
    def _generate_recovery_key() -> str:
        """Generate a random 24-char alphanumeric recovery key."""
        alphabet = string.ascii_uppercase + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(24))


# ── Singleton ─────────────────────────────────────────────────────────────────

_lock_manager: AppLockManager | None = None


def init_app_lock(db: aiosqlite.Connection) -> AppLockManager:
    global _lock_manager
    _lock_manager = AppLockManager(db)
    return _lock_manager


def get_app_lock() -> AppLockManager:
    if _lock_manager is None:
        raise RuntimeError("AppLockManager not initialised")
    return _lock_manager
