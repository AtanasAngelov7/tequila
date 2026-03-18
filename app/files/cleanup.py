"""File cleanup service — orphan detection, soft-delete lifecycle, quota enforcement (§21.7).

Runs as a periodic background task.  Each cleanup pass is chunked in batches of
50 (§20.5) to keep write-lock hold-times short.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.files.models import FileStorageConfig, FileStorageStats
from app.files.store import FileStore

logger = logging.getLogger(__name__)

_BATCH = 50


class FileCleanupService:
    """Periodic background task that enforces retention and quota rules.

    Usage::

        svc = FileCleanupService(store, config)
        await svc.start()          # schedules recurring cleanup
        await svc.run_once()       # trigger one pass immediately (API endpoint)
        await svc.stop()           # cancel the background task on shutdown
    """

    def __init__(self, store: FileStore, config: FileStorageConfig) -> None:
        self._store = store
        self._config = config
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the periodic cleanup loop."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="file-cleanup")
        logger.info("FileCleanupService started (interval=%dh).", self._config.cleanup_interval_hours)

    async def stop(self) -> None:
        """Cancel the background loop cleanly."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run_once(self) -> FileStorageStats:
        """Run one full cleanup pass and return the resulting storage stats."""
        logger.info("FileCleanupService: running cleanup pass.")

        # Step 1 — soft-delete orphans past retention window.
        orphans = await self._store.find_orphans(self._config.orphan_retention_days)
        for batch_start in range(0, len(orphans), _BATCH):
            batch = orphans[batch_start : batch_start + _BATCH]
            for record in batch:
                await self._store.soft_delete(record.file_id)
            logger.debug("Soft-deleted %d orphaned files.", len(batch))

        # Step 2 — permanently remove files past the grace period.
        expired = await self._store.find_expired_soft_deletes(self._config.soft_delete_grace_days)
        removed = 0
        for batch_start in range(0, len(expired), _BATCH):
            batch = expired[batch_start : batch_start + _BATCH]
            for record in batch:
                storage_path = await self._store.hard_delete(record.file_id)
                if storage_path:
                    _delete_from_disk(storage_path)
            removed += len(batch)
        if removed:
            logger.info("FileCleanupService: permanently removed %d files.", removed)

        # Step 3 — compute stats and emit warning if over quota.
        stats = await self._store.get_storage_stats(self._config.max_storage_mb)
        if (
            self._config.max_storage_mb > 0
            and stats.usage_percent >= self._config.warn_at_percent
        ):
            await self._emit_storage_warning(stats)

        logger.info(
            "FileCleanupService: pass complete — %d files, %.1f MB, %.1f%% of quota.",
            stats.total_files,
            stats.total_size_mb,
            stats.usage_percent,
        )
        return stats

    async def check_quota(self) -> None:
        """Raise HTTP 507 equivalent if storage is at 100% capacity.

        Called by the upload endpoint before accepting new files.
        """
        if self._config.max_storage_mb == 0:
            return  # unlimited
        stats = await self._store.get_storage_stats(self._config.max_storage_mb)
        if stats.usage_percent >= 100.0:
            from app.exceptions import ValidationError
            raise ValidationError(
                f"Storage quota exceeded ({stats.total_size_mb:.0f} / {self._config.max_storage_mb} MB)."
            )

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        interval_s = self._config.cleanup_interval_hours * 3600
        while True:
            try:
                await asyncio.sleep(interval_s)
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                logger.warning("FileCleanupService: error in cleanup loop.", exc_info=True)

    async def _emit_storage_warning(self, stats: FileStorageStats) -> None:
        """Push a ``storage_warning`` notification if the notification subsystem is up."""
        try:
            from app.notifications import get_notification_dispatcher
            dispatcher = get_notification_dispatcher()
            await dispatcher.dispatch(
                event_type="storage_warning",
                title="Storage Warning",
                body=(
                    f"Disk usage at {stats.usage_percent:.0f}% of quota "
                    f"({stats.total_size_mb:.0f} MB / {stats.quota_mb} MB)."
                ),
                priority="high",
            )
        except Exception:  # noqa: BLE001
            logger.warning("FileCleanupService: could not emit storage_warning notification.", exc_info=True)


# ── Singleton management ──────────────────────────────────────────────────────

_cleanup_service: FileCleanupService | None = None


def init_file_cleanup_service(store: FileStore, config: FileStorageConfig) -> FileCleanupService:
    """Initialise the process-wide ``FileCleanupService`` singleton."""
    global _cleanup_service
    _cleanup_service = FileCleanupService(store, config)
    return _cleanup_service


def get_file_cleanup_service() -> FileCleanupService:
    """Return the singleton; raises if not initialised."""
    if _cleanup_service is None:
        raise RuntimeError("FileCleanupService not initialised — call init_file_cleanup_service() first.")
    return _cleanup_service


# ── Disk helpers (run in thread pool) ─────────────────────────────────────────


def _delete_from_disk(storage_path: str) -> None:
    """Delete *storage_path* from disk, logging but not raising on errors."""
    try:
        p = Path(storage_path)
        if p.exists():
            p.unlink()
    except OSError as exc:
        logger.warning("Could not delete file from disk: %s — %s", storage_path, exc)
