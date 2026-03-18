"""Sprint 15 — files table, session_files table, and file retention columns (§21.6, §21.7).

Adds:
- ``files`` table: tracks all uploaded/agent-generated files with storage path,
  MIME type, size, soft-delete, pin flag, and retention timestamps.
- ``session_files`` table: links files to sessions with origin metadata.
- ``pinned`` and ``deleted_at`` columns on ``files`` per §21.7.

Revision ID: 0019
Revises: 0018
Create Date: 2026-03-18
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── files ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS files (
            file_id         TEXT PRIMARY KEY,
            filename        TEXT NOT NULL,
            mime_type       TEXT NOT NULL DEFAULT 'application/octet-stream',
            size_bytes      INTEGER NOT NULL DEFAULT 0,
            storage_path    TEXT NOT NULL,
            session_id      TEXT REFERENCES sessions(session_id),
            origin          TEXT NOT NULL DEFAULT 'upload',
            pinned          INTEGER NOT NULL DEFAULT 0,
            deleted_at      TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_files_session ON files(session_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_files_deleted ON files(deleted_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_files_pinned ON files(pinned)"
    )

    # ── session_files ─────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS session_files (
            id              TEXT PRIMARY KEY,
            session_id      TEXT NOT NULL REFERENCES sessions(session_id),
            file_id         TEXT NOT NULL REFERENCES files(file_id),
            message_id      TEXT REFERENCES messages(id),
            origin          TEXT NOT NULL DEFAULT 'upload',
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_files_session ON session_files(session_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_files_file ON session_files(file_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS session_files")
    op.execute("DROP TABLE IF EXISTS files")
