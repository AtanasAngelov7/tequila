"""Sprint 15 — Unit tests for FileStore (app/files/store.py)."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.files.store import FileStore, init_file_store
from app.exceptions import NotFoundError


# ── Helpers ───────────────────────────────────────────────────────────────────


def _store(db) -> FileStore:
    return init_file_store(db)


async def _insert_file(
    store: FileStore,
    *,
    filename: str = "test.txt",
    mime_type: str = "text/plain",
    size_bytes: int = 1024,
    storage_path: str = "/tmp/test.txt",
    session_id: str | None = None,
    origin: str = "upload",
):
    return await store.create(
        filename=filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
        storage_path=storage_path,
        session_id=session_id,
        origin=origin,
    )


async def _session_id(db) -> str:
    """Insert a minimal session row and return its id."""
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


# ── create ────────────────────────────────────────────────────────────────────


async def test_create_returns_file_record(migrated_db):
    store = _store(migrated_db)
    rec = await _insert_file(store)
    assert rec.file_id
    assert rec.filename == "test.txt"
    assert rec.mime_type == "text/plain"
    assert rec.size_bytes == 1024
    assert rec.origin == "upload"
    assert rec.pinned is False
    assert rec.deleted_at is None


async def test_create_assigns_unique_ids(migrated_db):
    store = _store(migrated_db)
    a = await _insert_file(store, filename="a.txt")
    b = await _insert_file(store, filename="b.txt")
    assert a.file_id != b.file_id


# ── get ───────────────────────────────────────────────────────────────────────


async def test_get_returns_exact_record(migrated_db):
    store = _store(migrated_db)
    created = await _insert_file(store, filename="fetch_me.txt")
    fetched = await store.get(created.file_id)
    assert fetched.file_id == created.file_id
    assert fetched.filename == "fetch_me.txt"


async def test_get_raises_for_unknown_id(migrated_db):
    store = _store(migrated_db)
    with pytest.raises(NotFoundError):
        await store.get("no-such-file")


async def test_get_raises_for_soft_deleted(migrated_db):
    store = _store(migrated_db)
    rec = await _insert_file(store)
    await store.soft_delete(rec.file_id)
    with pytest.raises(NotFoundError):
        await store.get(rec.file_id)


async def test_get_including_deleted_returns_soft_deleted(migrated_db):
    store = _store(migrated_db)
    rec = await _insert_file(store)
    await store.soft_delete(rec.file_id)
    fetched = await store.get_including_deleted(rec.file_id)
    assert fetched.file_id == rec.file_id
    assert fetched.deleted_at is not None


# ── pin ───────────────────────────────────────────────────────────────────────


async def test_pin_sets_and_clears(migrated_db):
    store = _store(migrated_db)
    rec = await _insert_file(store)
    assert rec.pinned is False

    pinned = await store.pin(rec.file_id, True)
    assert pinned.pinned is True

    unpinned = await store.pin(rec.file_id, False)
    assert unpinned.pinned is False


async def test_pin_raises_for_unknown_id(migrated_db):
    store = _store(migrated_db)
    with pytest.raises(NotFoundError):
        await store.pin("ghost", True)


# ── soft_delete ───────────────────────────────────────────────────────────────


async def test_soft_delete_sets_deleted_at(migrated_db):
    store = _store(migrated_db)
    rec = await _insert_file(store)
    await store.soft_delete(rec.file_id)
    fetched = await store.get_including_deleted(rec.file_id)
    assert fetched.deleted_at is not None


# ── hard_delete ───────────────────────────────────────────────────────────────


async def test_hard_delete_returns_storage_path(migrated_db):
    store = _store(migrated_db)
    rec = await _insert_file(store, storage_path="/data/files/x.txt")
    path = await store.hard_delete(rec.file_id)
    assert path == "/data/files/x.txt"


async def test_hard_delete_removes_row(migrated_db):
    store = _store(migrated_db)
    rec = await _insert_file(store)
    await store.hard_delete(rec.file_id)
    with pytest.raises(NotFoundError):
        await store.get_including_deleted(rec.file_id)


async def test_hard_delete_unknown_returns_none(migrated_db):
    store = _store(migrated_db)
    result = await store.hard_delete("not-there")
    assert result is None


# ── link_to_session / list_session_files ─────────────────────────────────────


async def test_link_and_list(migrated_db):
    sid = await _session_id(migrated_db)
    store = _store(migrated_db)
    rec = await _insert_file(store, session_id=sid)
    entry = await store.link_to_session(sid, rec.file_id)
    assert entry.session_id == sid
    assert entry.file_id == rec.file_id

    files = await store.list_session_files(sid)
    assert len(files) == 1
    assert files[0].file_id == rec.file_id


async def test_list_session_files_empty(migrated_db):
    sid = await _session_id(migrated_db)
    store = _store(migrated_db)
    files = await store.list_session_files(sid)
    assert files == []


async def test_list_session_files_by_origin(migrated_db):
    sid = await _session_id(migrated_db)
    store = _store(migrated_db)

    up = await _insert_file(store, filename="up.txt", origin="upload")
    ag = await _insert_file(store, filename="ag.txt", origin="agent_generated")
    await store.link_to_session(sid, up.file_id, origin="upload")
    await store.link_to_session(sid, ag.file_id, origin="agent_generated")

    uploads = await store.list_session_files(sid, origin="upload")
    assert len(uploads) == 1
    assert uploads[0].origin == "upload"

    agents = await store.list_session_files(sid, origin="agent_generated")
    assert len(agents) == 1
    assert agents[0].origin == "agent_generated"


async def test_list_session_files_by_mime_category(migrated_db):
    sid = await _session_id(migrated_db)
    store = _store(migrated_db)

    img = await _insert_file(store, filename="photo.jpg", mime_type="image/jpeg")
    txt = await _insert_file(store, filename="doc.txt", mime_type="text/plain")
    await store.link_to_session(sid, img.file_id)
    await store.link_to_session(sid, txt.file_id)

    images = await store.list_session_files(sid, mime_category="image")
    assert len(images) == 1
    assert images[0].mime_type.startswith("image/")


async def test_list_session_files_sort_name(migrated_db):
    sid = await _session_id(migrated_db)
    store = _store(migrated_db)

    b = await _insert_file(store, filename="b.txt")
    a = await _insert_file(store, filename="a.txt")
    await store.link_to_session(sid, b.file_id)
    await store.link_to_session(sid, a.file_id)

    files = await store.list_session_files(sid, sort="name")
    names = [f.filename for f in files]
    assert names == sorted(names)


# ── find_orphans ──────────────────────────────────────────────────────────────


async def test_find_orphans_detects_unlinked(migrated_db):
    store = _store(migrated_db)
    # Create file with no session link and creation time far in the past.
    rec = await _insert_file(store)
    # Back-date created_at by 35 days so orphan threshold (30 days) is met.
    async with migrated_db.execute(
        "UPDATE files SET created_at = datetime('now','-35 days') WHERE file_id = ?",
        (rec.file_id,),
    ):
        pass
    await migrated_db.commit()

    orphans = await store.find_orphans(older_than_days=30)
    ids = [o.file_id for o in orphans]
    assert rec.file_id in ids


async def test_find_orphans_excludes_linked(migrated_db):
    sid = await _session_id(migrated_db)
    store = _store(migrated_db)
    rec = await _insert_file(store, session_id=sid)
    await store.link_to_session(sid, rec.file_id)
    async with migrated_db.execute(
        "UPDATE files SET created_at = datetime('now','-35 days') WHERE file_id = ?",
        (rec.file_id,),
    ):
        pass
    await migrated_db.commit()

    orphans = await store.find_orphans(older_than_days=30)
    ids = [o.file_id for o in orphans]
    assert rec.file_id not in ids


async def test_find_orphans_excludes_pinned(migrated_db):
    store = _store(migrated_db)
    rec = await _insert_file(store)
    await store.pin(rec.file_id, True)
    async with migrated_db.execute(
        "UPDATE files SET created_at = datetime('now','-35 days') WHERE file_id = ?",
        (rec.file_id,),
    ):
        pass
    await migrated_db.commit()

    orphans = await store.find_orphans(older_than_days=30)
    ids = [o.file_id for o in orphans]
    assert rec.file_id not in ids


# ── find_expired_soft_deletes ─────────────────────────────────────────────────


async def test_find_expired_soft_deletes(migrated_db):
    store = _store(migrated_db)
    rec = await _insert_file(store)
    await store.soft_delete(rec.file_id)
    # Re-stamp deleted_at to 10 days ago so grace period (7 days) is exceeded.
    async with migrated_db.execute(
        "UPDATE files SET deleted_at = datetime('now','-10 days') WHERE file_id = ?",
        (rec.file_id,),
    ):
        pass
    await migrated_db.commit()

    expired = await store.find_expired_soft_deletes(grace_days=7)
    ids = [e.file_id for e in expired]
    assert rec.file_id in ids


async def test_find_expired_soft_deletes_excludes_fresh(migrated_db):
    store = _store(migrated_db)
    rec = await _insert_file(store)
    await store.soft_delete(rec.file_id)
    # deleted_at just NOW — still within grace period.
    expired = await store.find_expired_soft_deletes(grace_days=7)
    ids = [e.file_id for e in expired]
    assert rec.file_id not in ids


# ── get_storage_stats ─────────────────────────────────────────────────────────


async def test_storage_stats_empty(migrated_db):
    store = _store(migrated_db)
    stats = await store.get_storage_stats(quota_mb=1000.0)
    assert stats.total_files == 0
    assert stats.total_size_mb == 0.0
    assert stats.quota_mb == 1000.0
    assert stats.usage_percent == 0.0


async def test_storage_stats_counts_active_files(migrated_db):
    store = _store(migrated_db)
    await _insert_file(store, size_bytes=500_000)
    await _insert_file(store, size_bytes=500_000)
    soft_del = await _insert_file(store, size_bytes=999_999)
    await store.soft_delete(soft_del.file_id)

    stats = await store.get_storage_stats(quota_mb=1000.0)
    assert stats.total_files == 2
    # Two files × 500 KB each = ~0.95 MB (floating point tolerance).
    assert abs(stats.total_size_mb - 1_000_000 / 1_048_576) < 0.01


async def test_storage_stats_usage_percent(migrated_db):
    store = _store(migrated_db)
    # Add exactly 100 MB worth of files (simulated).
    async with migrated_db.execute(
        "INSERT INTO files(file_id, filename, mime_type, size_bytes, storage_path, created_at, updated_at) "
        "VALUES (?, 'big.bin', 'application/octet-stream', ?, '/tmp/big.bin', datetime('now'), datetime('now'))",
        (str(uuid.uuid4()), 100 * 1024 * 1024),
    ):
        pass
    await migrated_db.commit()

    stats = await store.get_storage_stats(quota_mb=1000.0)
    assert abs(stats.usage_percent - 10.0) < 0.01
