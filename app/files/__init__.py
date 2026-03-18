"""File management package for Tequila v2 (§21.6, §21.7).

Provides:
- ``FileRecord`` / ``SessionFileEntry`` data models
- ``FileStore`` repository for CRUD against the ``files`` and ``session_files`` tables
- ``FileExportService`` for download, preview, open, reveal, and pin actions
- ``FileCleanupService`` for orphan detection, soft-delete lifecycle, and quota enforcement
"""
from __future__ import annotations

from app.files.models import FileRecord, SessionFileEntry, FileStorageConfig
from app.files.store import FileStore, get_file_store, init_file_store

__all__ = [
    "FileRecord",
    "SessionFileEntry",
    "FileStorageConfig",
    "FileStore",
    "get_file_store",
    "init_file_store",
]
