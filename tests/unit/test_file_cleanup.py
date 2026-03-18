"""Sprint 15 — Unit tests for FileCleanupService (app/files/cleanup.py)."""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.files.cleanup import FileCleanupService, init_file_cleanup_service, get_file_cleanup_service
from app.files.models import FileStorageConfig
from app.files.store import FileStore, init_file_store


# ── Helpers ───────────────────────────────────────────────────────────────────


def _config(**kwargs) -> FileStorageConfig:
    defaults = dict(
        max_storage_mb=100.0,
        orphan_retention_days=30,
        audio_retention_days=7,
        cleanup_interval_hours=24,
        soft_delete_grace_days=7,
        warn_at_percent=80.0,
    )
    defaults.update(kwargs)
    return FileStorageConfig(**defaults)


async def _make_svc(db) -> tuple[FileCleanupService, FileStore]:
    store = init_file_store(db)
    cfg = _config()
    svc = init_file_cleanup_service(store, cfg)
    return svc, store


async def _session_id(db) -> str:
    sid = str(uuid.uuid4())
    skey = str(uuid.uuid4())
    async with db.execute(
        "INSERT INTO sessions(session_id, session_key, title, status, created_at, updated_at) "
        "VALUES (?, ?, 'Test', 'active', datetime('now'), datetime('now'))",
        (sid, skey),
    ):
        pass
    await db.commit()
    return sid


# ── run_once — no files ───────────────────────────────────────────────────────


async def test_run_once_on_empty_db(migrated_db):
    svc, _ = await _make_svc(migrated_db)
    stats = await svc.run_once()
    assert stats.total_files == 0
    assert stats.orphaned_files == 0


# ── orphan soft-delete ────────────────────────────────────────────────────────


async def test_run_once_soft_deletes_orphans(migrated_db):
    svc, store = await _make_svc(migrated_db)

    # Create orphan file (no session link, old enough to pass threshold).
    rec = await store.create(
        filename="orphan.txt",
        mime_type="text/plain",
        size_bytes=100,
        storage_path="/tmp/orphan.txt",
    )
    async with migrated_db.execute(
        "UPDATE files SET created_at = datetime('now','-35 days') WHERE file_id = ?",
        (rec.file_id,),
    ):
        pass
    await migrated_db.commit()

    await svc.run_once()

    # File should now be soft-deleted.
    updated = await store.get_including_deleted(rec.file_id)
    assert updated.deleted_at is not None


async def test_run_once_does_not_soft_delete_fresh_orphan(migrated_db):
    """Orphan within retention window should NOT be soft-deleted."""
    svc, store = await _make_svc(migrated_db)
    rec = await store.create(
        filename="fresh_orphan.txt",
        mime_type="text/plain",
        size_bytes=50,
        storage_path="/tmp/fresh.txt",
    )
    # created_at is default NOW — within the 30-day window.
    await svc.run_once()

    updated = await store.get_including_deleted(rec.file_id)
    assert updated.deleted_at is None


async def test_run_once_does_not_soft_delete_pinned(migrated_db):
    svc, store = await _make_svc(migrated_db)
    rec = await store.create(
        filename="pinned.txt",
        mime_type="text/plain",
        size_bytes=50,
        storage_path="/tmp/pinned.txt",
    )
    await store.pin(rec.file_id, True)
    async with migrated_db.execute(
        "UPDATE files SET created_at = datetime('now','-35 days') WHERE file_id = ?",
        (rec.file_id,),
    ):
        pass
    await migrated_db.commit()

    await svc.run_once()

    updated = await store.get_including_deleted(rec.file_id)
    assert updated.deleted_at is None  # pinned, must not be touched


# ── hard delete after grace period ───────────────────────────────────────────


async def test_run_once_hard_deletes_expired_soft_deletes(migrated_db, tmp_path):
    """Files soft-deleted beyond grace period should be hard-deleted."""
    svc, store = await _make_svc(migrated_db)

    # Create a real file on disk so _delete_from_disk works.
    fpath = tmp_path / "expire.txt"
    fpath.write_text("data")

    rec = await store.create(
        filename="expire.txt",
        mime_type="text/plain",
        size_bytes=4,
        storage_path=str(fpath),
    )
    # Soft-delete it and back-date deleted_at beyond grace period.
    await store.soft_delete(rec.file_id)
    async with migrated_db.execute(
        "UPDATE files SET deleted_at = datetime('now','-10 days') WHERE file_id = ?",
        (rec.file_id,),
    ):
        pass
    await migrated_db.commit()

    await svc.run_once()

    # Row should be gone from the DB entirely.
    from app.exceptions import NotFoundError
    with pytest.raises(NotFoundError):
        await store.get_including_deleted(rec.file_id)

    # Disk file should also be removed.
    assert not fpath.exists()


async def test_run_once_skips_missing_disk_file_gracefully(migrated_db):
    """Hard-delete of file whose disk path is already gone should not raise."""
    svc, store = await _make_svc(migrated_db)

    rec = await store.create(
        filename="ghost.txt",
        mime_type="text/plain",
        size_bytes=0,
        storage_path="/nonexistent/path/ghost.txt",
    )
    await store.soft_delete(rec.file_id)
    async with migrated_db.execute(
        "UPDATE files SET deleted_at = datetime('now','-10 days') WHERE file_id = ?",
        (rec.file_id,),
    ):
        pass
    await migrated_db.commit()

    # Should not raise even though the disk file does not exist.
    await svc.run_once()


# ── quota warning emission ────────────────────────────────────────────────────


async def test_run_once_emits_storage_warning_at_threshold(migrated_db):
    """When usage > warn_at_percent, a storage_warning notification is emitted."""
    # Use a tiny quota (1 MB) so the test file triggers the warning.
    tiny_config = _config(max_storage_mb=1.0, warn_at_percent=10.0)
    store = init_file_store(migrated_db)
    svc = init_file_cleanup_service(store, tiny_config)

    # Insert a 500 KB file (50% of 1 MB quota, well above 10% threshold).
    await store.create(
        filename="big.bin",
        mime_type="application/octet-stream",
        size_bytes=500 * 1024,
        storage_path="/tmp/big.bin",
    )

    dispatched: list[dict] = []

    class _FakeDispatcher:
        async def dispatch(self, *, event_type: str, title: str, body: str, priority: str = "normal") -> None:
            dispatched.append({"event_type": event_type})

    with patch("app.notifications.get_notification_dispatcher", return_value=_FakeDispatcher()):
        await svc.run_once()

    warning_events = [e for e in dispatched if e.get("event_type") == "storage_warning"]
    assert len(warning_events) >= 1


async def test_run_once_no_warning_below_threshold(migrated_db):
    """No warning when usage is below warn_at_percent."""
    # 80% threshold, files total 0 bytes → no warning.
    cfg = _config(max_storage_mb=1000.0, warn_at_percent=80.0)
    store = init_file_store(migrated_db)
    svc = init_file_cleanup_service(store, cfg)

    dispatched: list[dict] = []

    class _FakeDispatcher:
        async def dispatch(self, *, event_type: str, title: str, body: str, priority: str = "normal") -> None:
            dispatched.append({"event_type": event_type})

    with patch("app.notifications.get_notification_dispatcher", return_value=_FakeDispatcher()):
        await svc.run_once()

    warning_events = [e for e in dispatched if e.get("event_type") == "storage_warning"]
    assert len(warning_events) == 0


# ── start / stop lifecycle ────────────────────────────────────────────────────


async def test_start_and_stop(migrated_db):
    svc, _ = await _make_svc(migrated_db)
    await svc.start()
    assert svc._task is not None
    assert not svc._task.done()

    task = svc._task  # capture before stop() clears it
    await svc.stop()
    assert svc._task is None  # stop() clears the task reference
    assert task.done()        # underlying asyncio.Task is cancelled/done


async def test_start_idempotent(migrated_db):
    """Calling start() twice should not raise or create duplicate tasks."""
    svc, _ = await _make_svc(migrated_db)
    await svc.start()
    task_before = svc._task
    await svc.start()
    task_after = svc._task
    assert task_before is task_after  # same task, not a second one
    await svc.stop()


async def test_stop_without_start_does_not_raise(migrated_db):
    svc, _ = await _make_svc(migrated_db)
    # stop() before start() must be safe.
    await svc.stop()


# ── singleton ─────────────────────────────────────────────────────────────────


async def test_singleton_returns_same_instance(migrated_db):
    store = init_file_store(migrated_db)
    cfg = _config()
    svc_a = init_file_cleanup_service(store, cfg)
    svc_b = get_file_cleanup_service()
    assert svc_a is svc_b


# ── stats returned by run_once ────────────────────────────────────────────────


async def test_run_once_returns_storage_stats(migrated_db):
    svc, store = await _make_svc(migrated_db)
    await store.create(
        filename="sample.txt",
        mime_type="text/plain",
        size_bytes=1024,
        storage_path="/tmp/sample.txt",
    )
    stats = await svc.run_once()
    assert stats.total_files == 1
    assert stats.quota_mb > 0
