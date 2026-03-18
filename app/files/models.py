"""Data models for the file management subsystem (§21.6, §21.7)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ── Core file record ──────────────────────────────────────────────────────────


class FileRecord(BaseModel):
    """A file stored on disk and tracked in the ``files`` table."""

    file_id: str
    """Unique file identifier (UUID)."""

    filename: str
    """Original filename as provided by the uploader or agent tool."""

    mime_type: str
    """MIME type, e.g. ``'image/png'``, ``'application/pdf'``."""

    size_bytes: int
    """File size in bytes."""

    storage_path: str
    """Absolute path on disk where the file is stored."""

    session_id: str | None = None
    """Session that owns this file, or ``None`` for orphaned files."""

    origin: Literal["upload", "agent_generated"] = "upload"
    """Whether the file was uploaded by the user or created by an agent tool."""

    pinned: bool = False
    """If ``True``, the file is exempt from all automated cleanup (§21.7)."""

    deleted_at: datetime | None = None
    """Set when the file is soft-deleted; permanently removed after the grace period."""

    created_at: datetime = Field(default_factory=datetime.utcnow)
    """When the file was first stored."""

    updated_at: datetime = Field(default_factory=datetime.utcnow)
    """When the file record was last modified."""

    # ── Derived / computed ────────────────────────────────────────────────────

    @property
    def download_url(self) -> str:
        """REST URL to download this file."""
        return f"/api/files/{self.file_id}/download"

    @property
    def preview_url(self) -> str | None:
        """REST URL for a thumbnail/preview, or ``None`` if preview is unsupported."""
        previewable = {"image/", "application/pdf", "text/"}
        if any(self.mime_type.startswith(p) for p in previewable):
            return f"/api/files/{self.file_id}/preview"
        return None

    @property
    def preview_available(self) -> bool:
        """``True`` when a preview endpoint is available for this media type."""
        return self.preview_url is not None


class FileCard(BaseModel):
    """Serialised file card sent to the frontend inside message content (§21.6)."""

    file_id: str
    """Unique file identifier."""

    filename: str
    """Display filename."""

    mime_type: str
    """MIME type for rendering decisions."""

    size_bytes: int
    """Size in bytes; frontend formats to human-readable."""

    download_url: str
    """URL returned by ``GET /api/files/{id}/download``."""

    preview_available: bool
    """Whether a preview thumbnail can be fetched."""

    preview_url: str | None = None
    """URL returned by ``GET /api/files/{id}/preview``, or ``None``."""

    pinned: bool = False
    """Whether the file has been pinned by the user."""

    origin: Literal["upload", "agent_generated"] = "upload"
    """File provenance."""


# ── Session file link ─────────────────────────────────────────────────────────


class SessionFileEntry(BaseModel):
    """A file associated with a particular session (``session_files`` table row)."""

    id: str
    """Row UUID."""

    session_id: str
    """Which session this file belongs to."""

    file_id: str
    """References ``files.file_id``."""

    message_id: str | None = None
    """The message (if any) that first referenced this file."""

    origin: Literal["upload", "agent_generated"] = "upload"
    """Upload or agent-generated."""

    created_at: datetime = Field(default_factory=datetime.utcnow)
    """When the association was created."""

    # ── Joined fields (populated by store queries) ────────────────────────────

    filename: str | None = None
    """Populated from the ``files`` join."""

    mime_type: str | None = None
    """Populated from the ``files`` join."""

    size_bytes: int | None = None
    """Populated from the ``files`` join."""

    pinned: bool = False
    """From the file record."""


# ── Configuration ─────────────────────────────────────────────────────────────


class FileStorageConfig(BaseModel):
    """Runtime-adjustable storage and retention configuration (§21.7)."""

    max_storage_mb: int = Field(default=5000, ge=0)
    """Total upload storage cap in megabytes.  ``0`` means no limit."""

    orphan_retention_days: int = Field(default=30, ge=1)
    """Days before orphaned files are soft-deleted."""

    audio_retention_days: int = Field(default=7, ge=1)
    """Days to retain transcription source audio after the transcript is complete."""

    cleanup_interval_hours: int = Field(default=24, ge=1)
    """How often the cleanup task runs."""

    soft_delete_grace_days: int = Field(default=7, ge=1)
    """Days between soft-delete and permanent disk removal."""

    warn_at_percent: int = Field(default=80, ge=1, le=100)
    """Storage usage percentage at which a ``storage_warning`` notification is emitted."""


# ── Storage stats ─────────────────────────────────────────────────────────────


class FileStorageStats(BaseModel):
    """Storage statistics returned by ``GET /api/files/stats`` and embedded in status (§21.7)."""

    total_files: int
    """Total number of non-deleted file records."""

    total_size_mb: float
    """Sum of all non-deleted file sizes, in megabytes."""

    quota_mb: int
    """Configured maximum in megabytes (0 = unlimited)."""

    usage_percent: float
    """``total_size_mb / quota_mb * 100``, or ``0.0`` if quota is unlimited."""

    orphaned_files: int
    """Files with no session/message reference and not pinned."""

    orphaned_size_mb: float
    """Total size of orphaned files in megabytes."""

    pinned_files: int
    """Number of pinned files exempt from cleanup."""
