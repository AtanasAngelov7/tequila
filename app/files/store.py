"""File repository — CRUD against ``files`` and ``session_files`` tables (§21.6, §21.7).

All write paths use ``write_transaction``; all reads use a plain connection.
Never contains SQL in the route layer — follows the 4-layer architecture rule.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import aiosqlite

from app.db.connection import write_transaction
from app.exceptions import NotFoundError
from app.files.models import (
    FileRecord,
    FileStorageStats,
    SessionFileEntry,
)

logger = logging.getLogger(__name__)

# ── Module-level singleton ─────────────────────────────────────────────────────

_store: FileStore | None = None


def init_file_store(db: aiosqlite.Connection) -> "FileStore":
    """Initialise and cache the process-wide ``FileStore`` singleton."""
    global _store
    _store = FileStore(db)
    return _store


def get_file_store() -> "FileStore":
    """Return the singleton; raises ``RuntimeError`` if not yet initialised."""
    if _store is None:
        raise RuntimeError("FileStore not initialised — call init_file_store() first.")
    return _store


# ── Repository ────────────────────────────────────────────────────────────────


class FileStore:
    """CRUD and query operations for the ``files`` and ``session_files`` tables."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # ── File CRUD ─────────────────────────────────────────────────────────────

    async def create(
        self,
        filename: str,
        mime_type: str,
        size_bytes: int,
        storage_path: str,
        session_id: str | None = None,
        origin: Literal["upload", "agent_generated"] = "upload",
    ) -> FileRecord:
        """Insert a new file record and return it."""
        file_id = str(uuid.uuid4())
        now = _utcnow()
        async with write_transaction(self._db):
                await self._db.execute(
                    """
                    INSERT INTO files
                        (file_id, filename, mime_type, size_bytes, storage_path,
                         session_id, origin, pinned, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        file_id,
                        filename,
                        mime_type,
                        size_bytes,
                        storage_path,
                        session_id,
                        origin,
                        now,
                        now,
                    ),
                )
        return FileRecord(
            file_id=file_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            storage_path=storage_path,
            session_id=session_id,
            origin=origin,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
        )

    async def get(self, file_id: str) -> FileRecord:
        """Fetch a file record by ID; raises ``NotFoundError`` if absent."""
        async with self._db.execute(
            "SELECT * FROM files WHERE file_id = ? AND deleted_at IS NULL",
            (file_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise NotFoundError(f"File {file_id!r} not found.")
        return _row_to_file(row)

    async def get_including_deleted(self, file_id: str) -> FileRecord:
        """Fetch a file record including soft-deleted files."""
        async with self._db.execute(
            "SELECT * FROM files WHERE file_id = ?",
            (file_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise NotFoundError(f"File {file_id!r} not found.")
        return _row_to_file(row)

    async def pin(self, file_id: str, pinned: bool) -> FileRecord:
        """Set ``pinned`` flag on a file; raises ``NotFoundError`` if absent."""
        now = _utcnow()
        async with write_transaction(self._db):
                await self._db.execute(
                    "UPDATE files SET pinned = ?, updated_at = ? WHERE file_id = ? AND deleted_at IS NULL",
                    (1 if pinned else 0, now, file_id),
                )
                async with self._db.execute(
                    "SELECT changes()"
                ) as cur:
                    changed = (await cur.fetchone())[0]
        if not changed:
            raise NotFoundError(f"File {file_id!r} not found.")
        return await self.get(file_id)

    async def soft_delete(self, file_id: str) -> None:
        """Mark a file as soft-deleted (sets ``deleted_at``)."""
        now = _utcnow()
        async with write_transaction(self._db):
                await self._db.execute(
                    "UPDATE files SET deleted_at = ?, updated_at = ? WHERE file_id = ? AND deleted_at IS NULL",
                    (now, now, file_id),
                )

    async def hard_delete(self, file_id: str) -> str | None:
        """Permanently remove a file row; returns the ``storage_path`` if found."""
        async with self._db.execute(
            "SELECT storage_path FROM files WHERE file_id = ?",
            (file_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        path = row["storage_path"] if isinstance(row, dict) else row[0]
        async with write_transaction(self._db):
                await self._db.execute(
                    "DELETE FROM session_files WHERE file_id = ?",
                    (file_id,),
                )
                await self._db.execute(
                    "DELETE FROM files WHERE file_id = ?",
                    (file_id,),
                )
        return path

    # ── Session file links ────────────────────────────────────────────────────

    async def link_to_session(
        self,
        session_id: str,
        file_id: str,
        message_id: str | None = None,
        origin: Literal["upload", "agent_generated"] = "upload",
    ) -> SessionFileEntry:
        """Create a ``session_files`` link row."""
        link_id = str(uuid.uuid4())
        now = _utcnow()
        async with write_transaction(self._db):
                await self._db.execute(
                    """
                    INSERT OR IGNORE INTO session_files
                        (id, session_id, file_id, message_id, origin, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (link_id, session_id, file_id, message_id, origin, now),
                )
        return SessionFileEntry(
            id=link_id,
            session_id=session_id,
            file_id=file_id,
            message_id=message_id,
            origin=origin,
            created_at=datetime.fromisoformat(now),
        )

    async def list_session_files(
        self,
        session_id: str,
        origin: Literal["upload", "agent_generated"] | None = None,
        mime_category: Literal["image", "document", "audio", "other"] | None = None,
        sort: Literal["date", "name", "size"] = "date",
    ) -> list[SessionFileEntry]:
        """Return all non-deleted files for *session_id*, optionally filtered."""
        conditions = [
            "sf.session_id = ?",
            "f.deleted_at IS NULL",
        ]
        params: list[object] = [session_id]

        if origin is not None:
            conditions.append("f.origin = ?")
            params.append(origin)

        if mime_category is not None:
            mime_filter = _mime_category_sql(mime_category)
            conditions.append(f"({mime_filter})")

        order = {
            "date": "sf.created_at DESC",
            "name": "f.filename ASC",
            "size": "f.size_bytes DESC",
        }[sort]

        where = " AND ".join(conditions)
        sql = f"""
            SELECT sf.id, sf.session_id, sf.file_id, sf.message_id,
                   sf.origin, sf.created_at,
                   f.filename, f.mime_type, f.size_bytes, f.pinned
            FROM session_files sf
            JOIN files f ON f.file_id = sf.file_id
            WHERE {where}
            ORDER BY {order}
        """
        async with self._db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_session_file(r) for r in rows]

    # ── Orphan / cleanup queries ──────────────────────────────────────────────

    async def find_orphans(self, older_than_days: int) -> list[FileRecord]:
        """Return files that have no session link, are not pinned, and are older than the threshold."""
        cutoff = _utcnow_minus_days(older_than_days)
        sql = """
            SELECT f.*
            FROM files f
            LEFT JOIN session_files sf ON sf.file_id = f.file_id
            WHERE sf.file_id IS NULL
              AND f.pinned = 0
              AND f.deleted_at IS NULL
              AND f.created_at < ?
        """
        async with self._db.execute(sql, (cutoff,)) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_file(r) for r in rows]

    async def find_expired_soft_deletes(self, grace_days: int) -> list[FileRecord]:
        """Return soft-deleted files whose grace period has expired."""
        cutoff = _utcnow_minus_days(grace_days)
        async with self._db.execute(
            "SELECT * FROM files WHERE deleted_at IS NOT NULL AND deleted_at < ?",
            (cutoff,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_file(r) for r in rows]

    async def get_storage_stats(self, quota_mb: int = 5000) -> FileStorageStats:
        """Compute storage statistics for the status endpoint (§21.7)."""
        async with self._db.execute(
            """
            SELECT
                COUNT(*) AS total_files,
                COALESCE(SUM(size_bytes), 0) AS total_bytes
            FROM files
            WHERE deleted_at IS NULL
            """
        ) as cur:
            row = await cur.fetchone()
        total_files = row[0] if row else 0
        total_bytes = row[1] if row else 0
        total_size_mb = round(total_bytes / (1024 * 1024), 2)

        async with self._db.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(f.size_bytes), 0)
            FROM files f
            LEFT JOIN session_files sf ON sf.file_id = f.file_id
            WHERE sf.file_id IS NULL
              AND f.pinned = 0
              AND f.deleted_at IS NULL
            """
        ) as cur:
            orphan_row = await cur.fetchone()
        orphaned_files = orphan_row[0] if orphan_row else 0
        orphaned_bytes = orphan_row[1] if orphan_row else 0

        async with self._db.execute(
            "SELECT COUNT(*) FROM files WHERE pinned = 1 AND deleted_at IS NULL"
        ) as cur:
            pinned_row = await cur.fetchone()
        pinned_files = pinned_row[0] if pinned_row else 0

        usage_percent = (
            round(total_size_mb / quota_mb * 100, 2) if quota_mb > 0 else 0.0
        )

        return FileStorageStats(
            total_files=total_files,
            total_size_mb=total_size_mb,
            quota_mb=quota_mb,
            usage_percent=usage_percent,
            orphaned_files=orphaned_files,
            orphaned_size_mb=round(orphaned_bytes / (1024 * 1024), 2),
            pinned_files=pinned_files,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _utcnow_minus_days(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _row_to_file(row: aiosqlite.Row) -> FileRecord:
    d = dict(row)
    return FileRecord(
        file_id=d["file_id"],
        filename=d["filename"],
        mime_type=d["mime_type"],
        size_bytes=d["size_bytes"],
        storage_path=d["storage_path"],
        session_id=d.get("session_id"),
        origin=d.get("origin", "upload"),
        pinned=bool(d.get("pinned", 0)),
        deleted_at=datetime.fromisoformat(d["deleted_at"]) if d.get("deleted_at") else None,
        created_at=datetime.fromisoformat(d["created_at"]) if d.get("created_at") else datetime.utcnow(),
        updated_at=datetime.fromisoformat(d["updated_at"]) if d.get("updated_at") else datetime.utcnow(),
    )


def _row_to_session_file(row: aiosqlite.Row) -> SessionFileEntry:
    d = dict(row)
    return SessionFileEntry(
        id=d["id"],
        session_id=d["session_id"],
        file_id=d["file_id"],
        message_id=d.get("message_id"),
        origin=d.get("origin", "upload"),
        created_at=datetime.fromisoformat(d["created_at"]) if d.get("created_at") else datetime.utcnow(),
        filename=d.get("filename"),
        mime_type=d.get("mime_type"),
        size_bytes=d.get("size_bytes"),
        pinned=bool(d.get("pinned", 0)),
    )


def _mime_category_sql(category: str) -> str:
    """Return a SQL fragment for matching a MIME category against ``f.mime_type``."""
    mapping: dict[str, str] = {
        "image": "f.mime_type LIKE 'image/%'",
        "document": (
            "f.mime_type IN ('application/pdf','application/msword',"
            "'application/vnd.openxmlformats-officedocument.wordprocessingml.document',"
            "'application/vnd.ms-excel',"
            "'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',"
            "'application/vnd.ms-powerpoint',"
            "'application/vnd.openxmlformats-officedocument.presentationml.presentation',"
            "'text/plain','text/markdown','text/csv')"
        ),
        "audio": "f.mime_type LIKE 'audio/%'",
        "other": (
            "f.mime_type NOT LIKE 'image/%' AND f.mime_type NOT LIKE 'audio/%'"
        ),
    }
    return mapping.get(category, "1=1")
