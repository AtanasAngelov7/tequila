"""Data models for the auto-update subsystem (Sprint 16 §29.5)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class VersionInfo(BaseModel):
    """A single release returned by the GitHub releases API."""

    version: str
    """Semantic version string, e.g. ``"0.2.0"``."""

    release_date: str
    """ISO-8601 date string."""

    changelog: str
    """Release notes / body text."""

    download_url: str
    """URL of the Windows installer ``.exe`` asset."""

    checksum_sha256: str | None = None
    """Optional SHA-256 hex digest of the installer file."""

    is_prerelease: bool = False


class UpdateState(BaseModel):
    """Persistent state for the update mechanism."""

    current_version: str = "0.1.0"
    """Version of the currently running application."""

    latest_version: str | None = None
    """Latest available version found on the last check."""

    last_checked_at: datetime | None = None

    download_path: str | None = None
    """Local path to a downloaded installer (when status == 'ready')."""

    download_progress: float = Field(default=0.0, ge=0.0, le=1.0)
    """Download progress 0.0–1.0."""

    status: Literal["idle", "available", "downloading", "ready", "error"] = "idle"

    error: str | None = None
    """Human-readable error description when status == 'error'."""

    changelog: str | None = None
    """Release notes for the latest available version."""


class UpdateConfig(BaseModel):
    """Runtime-adjustable update configuration."""

    enabled: bool = True
    """Whether to check for updates at all."""

    check_interval_hours: int = Field(default=24, ge=1)
    """How often to query the releases API."""

    github_repo: str = "tequila-ai/tequila"
    """``owner/repo`` used to build the GitHub releases API URL."""

    auto_download: bool = False
    """If ``True``, silently download updates without user interaction."""

    update_channel: Literal["stable", "beta"] = "stable"
    """``stable`` uses latest non-prerelease; ``beta`` includes prereleases."""
