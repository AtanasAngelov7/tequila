"""Sprint 15 — Unit tests for FileExportService (app/files/export.py)."""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.files.export import FileExportService
from app.files.models import FileRecord, FileStorageConfig
from app.files.store import FileStore, init_file_store
from app.exceptions import NotFoundError, ValidationError


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_record(
    *,
    file_id: str | None = None,
    filename: str = "doc.txt",
    mime_type: str = "text/plain",
    size_bytes: int = 42,
    storage_path: str = "/tmp/doc.txt",
    pinned: bool = False,
    deleted_at: str | None = None,
) -> FileRecord:
    return FileRecord(
        file_id=file_id or str(uuid.uuid4()),
        filename=filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
        storage_path=storage_path,
        pinned=pinned,
        deleted_at=deleted_at,
        created_at="2025-01-01T00:00:00",
        updated_at="2025-01-01T00:00:00",
    )


def _make_service(db) -> FileExportService:
    store = init_file_store(db)
    return FileExportService(store)


# ── to_file_card ──────────────────────────────────────────────────────────────


async def test_to_file_card_fields(migrated_db):
    svc = _make_service(migrated_db)
    rec = _make_record(filename="photo.jpg", mime_type="image/jpeg", size_bytes=12345)
    card = await svc.to_file_card(rec)
    assert card.file_id == rec.file_id
    assert card.filename == "photo.jpg"
    assert card.mime_type == "image/jpeg"
    assert card.size_bytes == 12345
    assert card.download_url == f"/api/files/{rec.file_id}/download"
    assert card.preview_url == f"/api/files/{rec.file_id}/preview"
    assert card.preview_available is True  # images have previews


async def test_to_file_card_no_preview_for_binary(migrated_db):
    svc = _make_service(migrated_db)
    rec = _make_record(filename="data.exe", mime_type="application/octet-stream")
    card = await svc.to_file_card(rec)
    assert card.preview_available is False


async def test_to_file_card_pinned_propagated(migrated_db):
    svc = _make_service(migrated_db)
    rec = _make_record(pinned=True)
    card = await svc.to_file_card(rec)
    assert card.pinned is True


# ── get_download_info ─────────────────────────────────────────────────────────


async def test_get_download_info_ok(migrated_db, tmp_path):
    # Write a real file so the existence check passes.
    f = tmp_path / "hello.txt"
    f.write_text("hello")

    store = init_file_store(migrated_db)
    rec = await store.create(
        filename="hello.txt",
        mime_type="text/plain",
        size_bytes=5,
        storage_path=str(f),
    )

    svc = FileExportService(store)
    path, mime, fname = await svc.get_download_info(rec.file_id)
    assert path == f
    assert mime == "text/plain"
    assert fname == "hello.txt"


async def test_get_download_info_missing_on_disk(migrated_db, tmp_path):
    store = init_file_store(migrated_db)
    rec = await store.create(
        filename="gone.txt",
        mime_type="text/plain",
        size_bytes=0,
        storage_path=str(tmp_path / "gone.txt"),  # Does NOT exist on disk.
    )

    svc = FileExportService(store)
    with pytest.raises(ValidationError):
        await svc.get_download_info(rec.file_id)


async def test_get_download_info_deleted_record(migrated_db, tmp_path):
    f = tmp_path / "del.txt"
    f.write_text("data")
    store = init_file_store(migrated_db)
    rec = await store.create(filename="del.txt", mime_type="text/plain", size_bytes=4, storage_path=str(f))
    await store.soft_delete(rec.file_id)

    svc = FileExportService(store)
    with pytest.raises(NotFoundError):
        await svc.get_download_info(rec.file_id)


# ── get_preview — text ────────────────────────────────────────────────────────


async def test_get_preview_text_file(migrated_db, tmp_path):
    f = tmp_path / "readme.md"
    f.write_text("# Hello World")
    store = init_file_store(migrated_db)
    rec = await store.create(filename="readme.md", mime_type="text/markdown", size_bytes=13, storage_path=str(f))

    svc = FileExportService(store)
    result = await svc.get_preview(rec.file_id)
    assert result is not None
    raw_bytes, content_type = result
    assert b"Hello World" in raw_bytes
    assert "text/" in content_type


# ── get_preview — image (Pillow mock) ────────────────────────────────────────


async def test_get_preview_image_returns_jpeg(migrated_db, tmp_path):
    """Test image preview with Pillow mocked out (no real image needed)."""
    f = tmp_path / "photo.jpg"
    f.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)  # Minimal JPEG header bytes.

    store = init_file_store(migrated_db)
    rec = await store.create(filename="photo.jpg", mime_type="image/jpeg", size_bytes=104, storage_path=str(f))
    svc = FileExportService(store)

    fake_jpeg = b"\xff\xd8\xff" + b"\x00" * 50  # Fake resized JPEG.

    with patch("app.files.export._resize_image", return_value=fake_jpeg):
        result = await svc.get_preview(rec.file_id)

    assert result is not None
    raw_bytes, content_type = result
    assert raw_bytes == fake_jpeg
    assert content_type == "image/jpeg"


# ── get_preview — PDF (pdf2image mock) ───────────────────────────────────────


async def test_get_preview_pdf_returns_jpeg(migrated_db, tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4" + b"\x00" * 50)

    store = init_file_store(migrated_db)
    rec = await store.create(filename="doc.pdf", mime_type="application/pdf", size_bytes=58, storage_path=str(f))
    svc = FileExportService(store)

    fake_page = b"\xff\xd8\xff" + b"\x00" * 30

    with patch("app.files.export._pdf_first_page", return_value=fake_page):
        result = await svc.get_preview(rec.file_id)

    assert result is not None
    raw_bytes, content_type = result
    assert raw_bytes == fake_page
    assert content_type == "image/jpeg"


async def test_get_preview_pdf_returns_none_when_tool_unavailable(migrated_db, tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4" + b"\x00" * 20)

    store = init_file_store(migrated_db)
    rec = await store.create(filename="doc.pdf", mime_type="application/pdf", size_bytes=28, storage_path=str(f))
    svc = FileExportService(store)

    with patch("app.files.export._pdf_first_page", return_value=None):
        result = await svc.get_preview(rec.file_id)

    assert result is None


# ── get_preview — unsupported type ───────────────────────────────────────────


async def test_get_preview_binary_returns_none(migrated_db, tmp_path):
    f = tmp_path / "archive.zip"
    f.write_bytes(b"PK" + b"\x00" * 20)

    store = init_file_store(migrated_db)
    rec = await store.create(filename="archive.zip", mime_type="application/zip", size_bytes=22, storage_path=str(f))
    svc = FileExportService(store)

    result = await svc.get_preview(rec.file_id)
    assert result is None


# ── open_file / reveal_file ───────────────────────────────────────────────────


async def test_open_file_calls_os_open(migrated_db, tmp_path):
    f = tmp_path / "open_me.txt"
    f.write_text("open")

    store = init_file_store(migrated_db)
    rec = await store.create(filename="open_me.txt", mime_type="text/plain", size_bytes=4, storage_path=str(f))
    svc = FileExportService(store)

    with patch("app.files.export._os_open") as mock_open:
        await svc.open_file(rec.file_id)

    mock_open.assert_called_once_with(f)


async def test_reveal_file_calls_os_reveal(migrated_db, tmp_path):
    f = tmp_path / "reveal_me.txt"
    f.write_text("reveal")

    store = init_file_store(migrated_db)
    rec = await store.create(filename="reveal_me.txt", mime_type="text/plain", size_bytes=6, storage_path=str(f))
    svc = FileExportService(store)

    with patch("app.files.export._os_reveal") as mock_reveal:
        await svc.reveal_file(rec.file_id)

    mock_reveal.assert_called_once_with(f)


async def test_open_file_raises_for_missing_record(migrated_db):
    store = init_file_store(migrated_db)
    svc = FileExportService(store)

    with pytest.raises(NotFoundError):
        await svc.open_file("ghost-id")
