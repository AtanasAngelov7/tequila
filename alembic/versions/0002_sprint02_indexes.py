"""Sprint 02 — additional indexes for sessions and messages (§3.7, §14.3).

Revision ID: 0002
Revises: 0001

Adds performance indexes for:
- Idle-detection queries (filter by status + last_message_at / created_at).
- Session list filtering by kind.
"""
from __future__ import annotations

from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────────────

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


# ── Upgrade ───────────────────────────────────────────────────────────────────


def upgrade() -> None:
    # Index for idle-detection query: WHERE status = 'active' AND last_message_at < :cutoff
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_status_last_msg "
        "ON sessions(status, last_message_at)"
    )
    # Index for list sessions filtered by kind
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_kind "
        "ON sessions(kind)"
    )


# ── Downgrade ─────────────────────────────────────────────────────────────────


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_sessions_status_last_msg")
    op.execute("DROP INDEX IF EXISTS idx_sessions_kind")
