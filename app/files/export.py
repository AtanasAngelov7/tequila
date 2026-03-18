"""File export service — download, preview, open, reveal actions (§21.6).

Handles:
- Streaming file downloads with proper ``Content-Disposition`` headers
- Thumbnail/preview generation for images and PDFs
- OS-level open-file and reveal-in-explorer commands (local-only)
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import platform
import subprocess
import sys
from pathlib import Path

import aiosqlite

from app.exceptions import NotFoundError, ValidationError
from app.files.models import FileCard, FileRecord
from app.files.store import FileStore

logger = logging.getLogger(__name__)


# ── Export service ────────────────────────────────────────────────────────────


class FileExportService:
    """Service layer for file download, preview, and OS-action endpoints."""

    def __init__(self, store: FileStore) -> None:
        self._store = store

    async def get_download_info(self, file_id: str) -> tuple[Path, str, str]:
        """Return ``(path, mime_type, filename)`` for a download response.

        Raises ``NotFoundError`` if the record is missing or deleted.
        Raises ``ValidationError`` if the file does not exist on disk.
        """
        record = await self._store.get(file_id)
        path = Path(record.storage_path)
        if not path.exists():
            raise ValidationError(f"File on disk not found: {record.storage_path!r}")
        return path, record.mime_type, record.filename

    async def get_preview(self, file_id: str) -> tuple[bytes, str] | None:
        """Generate a preview (thumbnail or first page) for images and PDFs.

        Returns ``(image_bytes, mime_type)`` or ``None`` if preview is not
        supported for this MIME type.

        Image types: resized to max 400 px using Pillow (CPU-bound, run in thread).
        PDF types: first-page rasterization via pdf2image / Pillow-PDF if available,
        or a placeholder if those are not installed.
        """
        record = await self._store.get(file_id)
        if not record.preview_available:
            return None
        path = Path(record.storage_path)
        if not path.exists():
            raise ValidationError(f"File on disk not found: {record.storage_path!r}")

        mime = record.mime_type

        if mime.startswith("image/"):
            data = await asyncio.to_thread(_resize_image, path, 400)
            return data, "image/jpeg"

        if mime == "application/pdf":
            data = await asyncio.to_thread(_pdf_first_page, path, 400)
            if data is not None:
                return data, "image/jpeg"
            # Fall back to a generic PDF icon bytes (empty — caller handles None)
            return None

        if mime.startswith("text/"):
            # For text files return the first 4 KB as plain text
            content = await asyncio.to_thread(lambda: path.read_bytes()[:4096])
            return content, mime

        return None

    async def open_file(self, file_id: str) -> None:
        """Open the file with the OS default application (§21.6).

        Uses ``os.startfile`` on Windows, ``xdg-open`` on Linux, ``open`` on macOS.
        Raises ``ValidationError`` if the file is missing on disk.
        """
        record = await self._store.get(file_id)
        path = Path(record.storage_path)
        if not path.exists():
            raise ValidationError(f"File on disk not found: {record.storage_path!r}")
        await asyncio.to_thread(_os_open, path)

    async def reveal_file(self, file_id: str) -> None:
        """Reveal the file in the OS file manager (§21.6).

        On Windows: ``explorer /select,<path>``.
        On macOS: ``open -R <path>``.
        On Linux: ``xdg-open <parent_dir>``.
        Raises ``ValidationError`` if the file is missing on disk.
        """
        record = await self._store.get(file_id)
        path = Path(record.storage_path)
        if not path.exists():
            raise ValidationError(f"File on disk not found: {record.storage_path!r}")
        await asyncio.to_thread(_os_reveal, path)

    async def to_file_card(self, record: FileRecord) -> FileCard:
        """Convert a ``FileRecord`` to the frontend ``FileCard`` schema."""
        return FileCard(
            file_id=record.file_id,
            filename=record.filename,
            mime_type=record.mime_type,
            size_bytes=record.size_bytes,
            download_url=record.download_url,
            preview_available=record.preview_available,
            preview_url=record.preview_url,
            pinned=record.pinned,
            origin=record.origin,
        )


# ── OS helpers (run in thread pool) ──────────────────────────────────────────


def _os_open(path: Path) -> None:
    """Open *path* with the OS default app (blocking — run via asyncio.to_thread)."""
    system = platform.system()
    if system == "Windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif system == "Darwin":
        subprocess.Popen(["open", str(path)], close_fds=True)  # noqa: S603, S607
    else:
        subprocess.Popen(["xdg-open", str(path)], close_fds=True)  # noqa: S603, S607


def _os_reveal(path: Path) -> None:
    """Reveal *path* in the OS file manager (blocking — run via asyncio.to_thread)."""
    system = platform.system()
    if system == "Windows":
        subprocess.Popen(  # noqa: S603, S607
            ["explorer", f"/select,{path}"], close_fds=True
        )
    elif system == "Darwin":
        subprocess.Popen(["open", "-R", str(path)], close_fds=True)  # noqa: S603, S607
    else:
        subprocess.Popen(["xdg-open", str(path.parent)], close_fds=True)  # noqa: S603, S607


def _resize_image(path: Path, max_px: int) -> bytes:
    """Resize an image to *max_px* on the longest side and return JPEG bytes.

    Falls back to raw file bytes if Pillow is not installed.
    """
    try:
        from PIL import Image  # type: ignore[import]
        import io

        with Image.open(path) as img:
            img.thumbnail((max_px, max_px))
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=85)
            return buf.getvalue()
    except ImportError:
        return path.read_bytes()


def _pdf_first_page(path: Path, max_px: int) -> bytes | None:
    """Rasterise the first page of a PDF and return JPEG bytes.

    Returns ``None`` if pdf2image / poppler is not available.
    """
    try:
        from pdf2image import convert_from_path  # type: ignore[import]
        import io

        images = convert_from_path(str(path), first_page=1, last_page=1, dpi=72)
        if not images:
            return None
        img = images[0]
        img.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return buf.getvalue()
    except (ImportError, Exception):  # noqa: BLE001
        logger.debug("PDF preview unavailable for %s", path)
        return None
