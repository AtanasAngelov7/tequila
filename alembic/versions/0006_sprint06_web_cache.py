"""Sprint 06 — Web cache table (§17.2).

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-15

Adds the ``web_cache`` table used by ``web_fetch`` for TTL-based caching
with ETag / Last-Modified conditional GET support.
"""
from __future__ import annotations

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS web_cache (
            url           TEXT PRIMARY KEY,
            content       TEXT,
            content_type  TEXT,
            fetched_at    TEXT NOT NULL,
            ttl_s         INTEGER NOT NULL DEFAULT 3600,
            etag          TEXT,
            last_modified TEXT
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_web_cache_fetched_at ON web_cache (fetched_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS web_cache")
