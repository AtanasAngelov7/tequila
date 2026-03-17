"""Sprint 14b — Unit tests for BackupManager (§26.1–26.6)."""
from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from app.backup import BackupConfig, BackupManager, init_backup_manager


async def _manager(db, tmp_path: Path) -> BackupManager:
    mgr = init_backup_manager(db)
    # Override backup dir to a temp directory for test isolation
    await mgr.set_config(BackupConfig(backup_dir=str(tmp_path / "backups"), retention_count=3))
    return mgr


# ── Config ────────────────────────────────────────────────────────────────────


async def test_default_config(migrated_db):
    mgr = init_backup_manager(migrated_db)
    cfg = await mgr.get_config()
    assert cfg.retention_count > 0
    assert cfg.schedule_cron


async def test_set_config(migrated_db):
    mgr = init_backup_manager(migrated_db)
    await mgr.set_config(BackupConfig(enabled=True, retention_count=5, backup_dir="data/backups"))
    cfg = await mgr.get_config()
    assert cfg.retention_count == 5


# ── list_backups empty ────────────────────────────────────────────────────────


async def test_list_backups_empty(migrated_db, tmp_path):
    mgr = await _manager(migrated_db, tmp_path)
    items = await mgr.list_backups()
    assert items == []


# ── create_backup ─────────────────────────────────────────────────────────────


async def test_create_backup_creates_archive(migrated_db, tmp_path):
    mgr = await _manager(migrated_db, tmp_path)
    archive = await mgr.create_backup()
    assert archive.exists()
    assert archive.suffix == ".gz"
    assert "tequila_backup_" in archive.name


async def test_create_backup_is_valid_tar(migrated_db, tmp_path):
    mgr = await _manager(migrated_db, tmp_path)
    archive = await mgr.create_backup()
    assert tarfile.is_tarfile(str(archive))


async def test_create_backup_contains_config_json(migrated_db, tmp_path):
    mgr = await _manager(migrated_db, tmp_path)
    archive = await mgr.create_backup()
    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
    assert "config.json" in names


async def test_list_backups_after_create(migrated_db, tmp_path):
    mgr = await _manager(migrated_db, tmp_path)
    await mgr.create_backup()
    items = await mgr.list_backups()
    assert len(items) == 1
    assert items[0].filename.startswith("tequila_backup_")


# ── retention ─────────────────────────────────────────────────────────────────


async def test_retention_deletes_oldest(migrated_db, tmp_path):
    """Create 5 backups with retention=3 — only 3 should remain."""
    mgr = await _manager(migrated_db, tmp_path)
    cfg = await mgr.get_config()
    # retention_count already set to 3 above
    for _ in range(5):
        await mgr.create_backup()
    items = await mgr.list_backups()
    assert len(items) <= 3


# ── archive name format ───────────────────────────────────────────────────────


async def test_archive_name_format(migrated_db, tmp_path):
    import re
    mgr = await _manager(migrated_db, tmp_path)
    archive = await mgr.create_backup()
    # Expected: tequila_backup_YYYY-MM-DD_HHmmss.tar.gz
    pattern = r"tequila_backup_\d{4}-\d{2}-\d{2}_\d{6}\.tar\.gz"
    assert re.match(pattern, archive.name), f"Name does not match pattern: {archive.name}"


# ── restore validation ────────────────────────────────────────────────────────


async def test_restore_missing_file_raises(migrated_db, tmp_path):
    mgr = await _manager(migrated_db, tmp_path)
    with pytest.raises(FileNotFoundError):
        await mgr.restore_backup(tmp_path / "nonexistent.tar.gz")


async def test_restore_not_tar_raises(migrated_db, tmp_path):
    bad_file = tmp_path / "junk.tar.gz"
    bad_file.write_bytes(b"This is not a real tarball")
    mgr = await _manager(migrated_db, tmp_path)
    with pytest.raises(ValueError, match="valid tar"):
        await mgr.restore_backup(bad_file)
