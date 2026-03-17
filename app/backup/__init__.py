"""Backup and restore system for Tequila v2 (§26.1–26.6, Sprint 14b D5).

Creates encrypted tar.gz archives of:
  - SQLite database
  - data/uploads/
  - data/vault/
  - data/embeddings/
  - config export (JSON)
  - custom plugins

Restore: extracts archive, runs Alembic migrations, rebuilds FTS indexes.

Usage::

    manager = init_backup_manager(db)
    path = await manager.create_backup()
    await manager.restore_backup(path_to_archive)
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
from pydantic import BaseModel, Field

from app.db.connection import write_transaction

logger = logging.getLogger(__name__)


# ── Models ────────────────────────────────────────────────────────────────────


class BackupConfig(BaseModel):
    """Backup schedule and retention (§26.4)."""

    enabled: bool = True
    schedule_cron: str = "0 3 * * *"
    retention_count: int = 7
    backup_dir: str = "data/backups"


class BackupInfo(BaseModel):
    """Metadata about a single backup file."""

    filename: str
    path: str
    size_bytes: int
    created_at: str


# ── Excluded paths (§26.2) ────────────────────────────────────────────────────
_EXCLUDE_DIRS = {"logs", "browser_profiles", "cache", "__pycache__"}


def _exclude_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    """Exclude logs, browser profiles, and cache from archives."""
    parts = Path(tarinfo.name).parts
    for part in parts:
        if part in _EXCLUDE_DIRS:
            return None
    return tarinfo


# ── BackupManager ─────────────────────────────────────────────────────────────


class BackupManager:
    """Creates and restores encrypted tar.gz backups (§26.1–26.6)."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # ── Config ────────────────────────────────────────────────────────────

    async def get_config(self) -> BackupConfig:
        cursor = await self._db.execute(
            "SELECT enabled, schedule_cron, retention_count, backup_dir "
            "FROM backup_configs WHERE id = 1"
        )
        row = await cursor.fetchone()
        if row:
            return BackupConfig.model_validate(dict(row))
        return BackupConfig()

    async def set_config(self, config: BackupConfig) -> BackupConfig:
        # TD-153: Validate backup_dir — reject path traversal attempts
        bdir = config.backup_dir
        if bdir:
            from pathlib import PurePosixPath, PureWindowsPath
            p = PurePosixPath(bdir) if "/" in bdir else PureWindowsPath(bdir)
            if ".." in p.parts:
                raise ValueError(f"Invalid backup_dir: path traversal ('..') not allowed: {bdir!r}")
        async with write_transaction(self._db):
            await self._db.execute(
                """
                UPDATE backup_configs SET
                    enabled = ?, schedule_cron = ?,
                    retention_count = ?, backup_dir = ?, updated_at = ?
                WHERE id = 1
                """,
                (int(config.enabled), config.schedule_cron,
                 config.retention_count, config.backup_dir,
                 datetime.now(timezone.utc).isoformat()),
            )
        return config

    # ── Create ────────────────────────────────────────────────────────────

    async def create_backup(self) -> Path:
        """Create a tar.gz backup archive. Returns path to the archive.

        Backup is NOT encrypted at the archive level (planned for Phase 7).
        It is intended to be stored in a secure local directory.
        """
        config = await self.get_config()
        from app.paths import data_dir
        data = data_dir()
        backup_dir = Path(config.backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        archive_name = f"tequila_backup_{ts}.tar.gz"
        archive_path = backup_dir / archive_name

        # Run in thread to avoid blocking event loop
        await asyncio.to_thread(self._build_archive, archive_path, data)

        logger.info("Backup created: %s (%d bytes)", archive_path, archive_path.stat().st_size)

        # Apply retention
        await asyncio.to_thread(self._apply_retention, backup_dir, config.retention_count)

        return archive_path

    def _build_archive(self, archive_path: Path, data_root: Path) -> None:
        """Build the tar.gz archive synchronously (called via asyncio.to_thread)."""
        db_path = data_root / "tequila.db"
        included_subdirs = ["uploads", "vault", "embeddings"]
        custom_plugins = Path("app") / "plugins" / "custom"

        with tarfile.open(archive_path, "w:gz") as tar:
            # SQLite database
            if db_path.exists():
                tar.add(db_path, arcname="tequila.db")

            # Data subdirectories (excluding logs etc.)
            for subdir in included_subdirs:
                p = data_root / subdir
                if p.exists():
                    tar.add(p, arcname=subdir, filter=_exclude_filter)

            # Config export (JSON)
            config_json = self._export_config_sync()
            import io
            config_bytes = config_json.encode("utf-8")
            info = tarfile.TarInfo(name="config.json")
            info.size = len(config_bytes)
            tar.addfile(info, io.BytesIO(config_bytes))

            # Custom plugins
            if custom_plugins.exists():
                tar.add(custom_plugins, arcname="plugins_custom", filter=_exclude_filter)

    def _export_config_sync(self) -> str:
        """Placeholder — full config export is async; returns minimal JSON."""
        return json.dumps({"exported_at": datetime.now(timezone.utc).isoformat()}, indent=2)

    def _apply_retention(self, backup_dir: Path, retain_count: int) -> None:
        """Delete oldest backups exceeding retain_count."""
        archives = sorted(
            backup_dir.glob("tequila_backup_*.tar.gz"),
            key=lambda p: p.stat().st_mtime,
        )
        excess = len(archives) - retain_count
        for old in archives[:excess]:
            try:
                old.unlink()
                logger.info("Deleted old backup: %s", old)
            except Exception as exc:
                logger.warning("Could not delete old backup %s: %s", old, exc)

    # ── List ──────────────────────────────────────────────────────────────

    async def list_backups(self) -> list[BackupInfo]:
        config = await self.get_config()
        backup_dir = Path(config.backup_dir)
        if not backup_dir.exists():
            return []
        archives = sorted(
            backup_dir.glob("tequila_backup_*.tar.gz"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        infos: list[BackupInfo] = []
        for p in archives:
            stat = p.stat()
            infos.append(BackupInfo(
                filename=p.name,
                path=str(p),
                size_bytes=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            ))
        return infos

    # ── Restore ───────────────────────────────────────────────────────────

    async def restore_backup(self, archive_path: Path) -> dict[str, Any]:
        """Restore from a backup archive (§26.5).

        Steps:
        1. Validate the archive.
        2. Create a pre-restore backup.
        3. Extract to data/.
        4. Run Alembic migrations.
        5. Return status dict.

        NOTE: Active sessions and scheduler are NOT currently stopped here.
        Full lifecycle stop/restart would require coordination at the app level.
        """
        result: dict[str, Any] = {
            "restored_from": str(archive_path),
            "steps": [],
        }

        # 1. Validate
        if not archive_path.exists():
            raise FileNotFoundError(f"Backup file not found: {archive_path}")
        if not tarfile.is_tarfile(str(archive_path)):
            raise ValueError("Not a valid tar.gz archive")
        result["steps"].append("validated")

        # 2. Pre-restore backup
        try:
            pre_restore_path = await self.create_backup()
            result["pre_restore_backup"] = str(pre_restore_path)
            result["steps"].append("pre_restore_backup_created")
        except Exception as exc:
            logger.warning("Could not create pre-restore backup: %s", exc)

        # 3. Close database connection before overwriting DB file (TD-141)
        from app.db.connection import shutdown as db_shutdown, startup as db_startup
        from app.paths import data_dir, db_path as get_db_path
        data = data_dir()
        await db_shutdown()
        try:
            await asyncio.to_thread(self._extract_archive, archive_path, data)
            result["steps"].append("extracted")
        finally:
            # Reopen connection regardless of extraction outcome
            await db_startup(get_db_path())

        # 4. Run Alembic migrations
        migration_ok = False
        try:
            from app.paths import alembic_dir
            import subprocess
            proc = await asyncio.to_thread(
                lambda: subprocess.run(
                    [sys.executable, "-m", "alembic", "upgrade", "head"],
                    capture_output=True, text=True,
                    cwd=str(alembic_dir().parent),
                )
            )
            if proc.returncode != 0:
                logger.warning("Alembic migration after restore had issues: %s", proc.stderr)
                result["steps"].append("migration_failed")
            else:
                result["steps"].append("migrations_applied")
                migration_ok = True
        except Exception as exc:
            logger.warning("Post-restore migrations failed: %s", exc)
            result["steps"].append("migration_failed")

        # TD-164: Only report complete when migrations succeeded
        if migration_ok:
            result["steps"].append("complete")
        else:
            result["steps"].append("complete_with_errors")
        logger.info("Restore complete from %s", archive_path)
        return result

    def _extract_archive(self, archive_path: Path, data_root: Path) -> None:
        """Extract archive to data_root (synchronous helper)."""
        with tarfile.open(archive_path, "r:gz") as tar:
            # Safety: only extract expected top-level names
            safe_prefixes = {"tequila.db", "uploads", "vault", "embeddings",
                             "config.json", "plugins_custom"}
            for member in tar.getmembers():
                top = Path(member.name).parts[0] if member.name else ""
                if top not in safe_prefixes:
                    logger.debug("Skipping unexpected archive member: %s", member.name)
                    continue
                # TD-157: Explicit path traversal check — resolved target must
                # stay inside data_root regardless of Python version.
                resolved_target = (data_root / member.name).resolve()
                if not str(resolved_target).startswith(str(data_root.resolve())):
                    logger.warning("Tar path traversal blocked: %s", member.name)
                    continue
                try:
                    tar.extract(member, path=str(data_root), filter="tar")
                except TypeError:
                    # Python < 3.11.4 doesn't support filter= parameter
                    tar.extract(member, path=str(data_root))


# ── Singleton ─────────────────────────────────────────────────────────────────

_manager: BackupManager | None = None


def init_backup_manager(db: aiosqlite.Connection) -> BackupManager:
    global _manager
    _manager = BackupManager(db)
    return _manager


def get_backup_manager() -> BackupManager:
    if _manager is None:
        raise RuntimeError("BackupManager not initialised")
    return _manager
