"""Sprint 07 — audit_log schema alignment — approval-decision indexes (§11.2).

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-15

Note: The audit_log table itself was created by migration 0001 with the full
general-purpose schema.  This migration only adds the two performance indexes
used by the Sprint 07 approval flow (session_key, created_at).  The Sprint 07
CREATE TABLE statement is kept as a no-op IF NOT EXISTS guard.
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:  # noqa: D103
    # ── audit_log — approval / policy decision log ───────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id            TEXT NOT NULL PRIMARY KEY,
            created_at    TEXT NOT NULL,
            event_type    TEXT NOT NULL,
            session_key   TEXT NOT NULL DEFAULT '',
            tool_name     TEXT NOT NULL DEFAULT '',
            decision      TEXT NOT NULL DEFAULT '',
            actor         TEXT NOT NULL DEFAULT 'system',
            details_json  TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_log_session_key "
        "ON audit_log (session_key)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_log_created_at "
        "ON audit_log (created_at)"
    )


def downgrade() -> None:  # noqa: D103
    op.execute("DROP INDEX IF EXISTS ix_audit_log_created_at")
    op.execute("DROP INDEX IF EXISTS ix_audit_log_session_key")
    op.execute("DROP TABLE IF EXISTS audit_log")
