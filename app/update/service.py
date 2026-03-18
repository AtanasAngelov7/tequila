"""Auto-update service — check, download, apply (Sprint 16 §29.5)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from app.update.checker import check_github_releases, is_newer_than_current
from app.update.models import UpdateConfig, UpdateState

if TYPE_CHECKING:
    from app.update.models import VersionInfo

logger = logging.getLogger(__name__)

# Module-level singleton
_instance: UpdateService | None = None

# Version of the running app — read from pyproject or fallback constant.
_CURRENT_VERSION = "0.1.0"


def _current_version() -> str:
    """Return the running app version."""
    try:
        from importlib.metadata import version
        return version("tequila")
    except Exception:  # noqa: BLE001
        return _CURRENT_VERSION


class UpdateService:
    """Check for, download, and apply application updates (§29.5).

    Usage::

        svc = init_update_service(config, state_path)
        await svc.start()          # begins periodic background checks
        state = await svc.check()  # manual check
        state = await svc.download()
        await svc.apply()          # launch installer, exits process
        await svc.stop()
    """

    def __init__(
        self,
        config: UpdateConfig,
        state_path: Path,
    ) -> None:
        self._config = config
        self._state_path = state_path
        self._state = self._load_state()
        self._state.current_version = _current_version()
        self._task: asyncio.Task[None] | None = None

    # ── State persistence ─────────────────────────────────────────────────────

    def _load_state(self) -> UpdateState:
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text())
                return UpdateState(**data)
            except Exception:  # noqa: BLE001
                pass
        return UpdateState(current_version=_current_version())

    def _save_state(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(self._state.model_dump_json(indent=2))
        except OSError as exc:
            logger.warning("UpdateService: could not save state: %s", exc)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the periodic background update check."""
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="update-check-loop")

    async def stop(self) -> None:
        """Cancel the background loop."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        interval = self._config.check_interval_hours * 3600
        while True:
            await asyncio.sleep(interval)
            if self._config.enabled:
                try:
                    await self.check()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("UpdateService: background check failed: %s", exc)

    # ── Operations ────────────────────────────────────────────────────────────

    async def check(self) -> UpdateState:
        """Query GitHub for the latest release and update state."""
        if not self._config.enabled:
            return self._state

        self._state.last_checked_at = datetime.now(timezone.utc)
        try:
            info = await check_github_releases(
                self._config.github_repo,
                include_prerelease=(self._config.update_channel == "beta"),
            )
        except Exception as exc:  # noqa: BLE001
            self._state.status = "error"
            self._state.error = str(exc)
            self._save_state()
            return self._state

        current = _current_version()
        if info and is_newer_than_current(info.version, current):
            self._state.latest_version = info.version
            self._state.changelog = info.changelog
            if self._state.status not in ("downloading", "ready"):
                self._state.status = "available"
            self._state.error = None
            logger.info(
                "UpdateService: new version %r available (current %r).",
                info.version,
                current,
            )
            if self._config.auto_download and self._state.status == "available":
                await self.download()
        else:
            if self._state.status not in ("downloading", "ready"):
                self._state.status = "idle"
            self._state.latest_version = info.version if info else None

        self._save_state()
        return self._state

    async def download(self) -> UpdateState:
        """Download the latest installer in the background."""
        if self._state.status == "downloading":
            return self._state
        if self._state.status == "ready" and self._state.download_path:
            if Path(self._state.download_path).exists():
                return self._state

        info = await check_github_releases(
            self._config.github_repo,
            include_prerelease=(self._config.update_channel == "beta"),
        )
        if not info:
            self._state.status = "error"
            self._state.error = "No release found for download."
            self._save_state()
            return self._state

        from app.paths import data_dir
        dest = data_dir() / "updates" / f"TequilaSetup-{info.version}.exe"
        dest.parent.mkdir(parents=True, exist_ok=True)

        self._state.status = "downloading"
        self._state.download_progress = 0.0
        self._save_state()

        try:
            await asyncio.to_thread(self._download_sync, info.download_url, dest, info)
        except Exception as exc:  # noqa: BLE001
            logger.error("UpdateService: download failed: %s", exc)
            self._state.status = "error"
            self._state.error = f"Download failed: {exc}"
            self._save_state()
            return self._state

        self._state.download_path = str(dest)
        self._state.download_progress = 1.0
        self._state.status = "ready"
        self._state.error = None
        logger.info("UpdateService: installer downloaded to %s", dest)
        self._save_state()
        return self._state

    def _download_sync(self, url: str, dest: Path, info: "VersionInfo") -> None:
        """Synchronous streaming download (run in thread)."""
        hasher = hashlib.sha256() if info.checksum_sha256 else None
        with httpx.stream("GET", url, follow_redirects=True, timeout=300.0) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            received = 0
            with dest.open("wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=65536):
                    fh.write(chunk)
                    if hasher:
                        hasher.update(chunk)
                    received += len(chunk)
                    if total:
                        self._state.download_progress = received / total

        if hasher and info.checksum_sha256:
            digest = hasher.hexdigest()
            if digest.lower() != info.checksum_sha256.lower():
                dest.unlink(missing_ok=True)
                raise ValueError(
                    f"Checksum mismatch: expected {info.checksum_sha256}, got {digest}"
                )

    async def apply(self) -> None:
        """Launch the downloaded installer and exit the current process.

        On Windows this runs the ``.exe`` installer with ``/SILENT`` and lets
        the user complete the upgrade.  On other platforms a warning is logged.
        """
        if self._state.status != "ready" or not self._state.download_path:
            raise RuntimeError(
                "No installer ready to apply. Call download() first."
            )

        path = Path(self._state.download_path)
        if not path.exists():
            self._state.status = "error"
            self._state.error = f"Installer file missing: {path}"
            self._save_state()
            raise FileNotFoundError(f"Installer not found: {path}")

        if platform.system() == "Windows":
            logger.info("UpdateService: launching installer %s", path)
            subprocess.Popen(  # noqa: S603
                [str(path), "/SILENT"],
                close_fds=True,
            )
        else:
            logger.warning(
                "UpdateService: non-Windows apply not implemented. "
                "Installer at %s",
                path,
            )
            return

        # Reset state for next run
        self._state.status = "idle"
        self._state.download_path = None
        self._save_state()

        # Give the installer a moment to start before we exit.
        await asyncio.sleep(1)
        sys.exit(0)

    def get_state(self) -> UpdateState:
        """Return the current in-memory state (no I/O)."""
        return self._state


# ── Singleton helpers ─────────────────────────────────────────────────────────


def init_update_service(
    config: UpdateConfig | None = None,
    state_path: Path | None = None,
) -> UpdateService:
    """Create and register the module-level singleton."""
    global _instance
    from app.paths import data_dir

    cfg = config or UpdateConfig()
    path = state_path or (data_dir() / "update_state.json")
    _instance = UpdateService(cfg, path)
    return _instance


def get_update_service() -> UpdateService:
    """Return the singleton; raise ``RuntimeError`` if not initialised."""
    if _instance is None:
        raise RuntimeError(
            "UpdateService not initialised. Call init_update_service() in the lifespan."
        )
    return _instance
