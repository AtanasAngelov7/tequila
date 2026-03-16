"""Sprint 08 — workflow tables (§10.1–10.3).

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-15
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:  # noqa: D103
    # ── workflows ────────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflows (
            id          TEXT NOT NULL PRIMARY KEY,
            name        TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            mode        TEXT NOT NULL DEFAULT 'pipeline',
            steps_json  TEXT NOT NULL DEFAULT '[]',
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    # ── workflow_runs ─────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id               TEXT NOT NULL PRIMARY KEY,
            workflow_id      TEXT NOT NULL REFERENCES workflows(id),
            status           TEXT NOT NULL DEFAULT 'pending',
            step_results_json TEXT NOT NULL DEFAULT '{}',
            current_step     TEXT,
            error            TEXT,
            started_at       TEXT,
            completed_at     TEXT,
            created_at       TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workflow_runs_workflow_id "
        "ON workflow_runs (workflow_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workflow_runs_status "
        "ON workflow_runs (status)"
    )


def downgrade() -> None:  # noqa: D103
    op.execute("DROP INDEX IF EXISTS ix_workflow_runs_status")
    op.execute("DROP INDEX IF EXISTS ix_workflow_runs_workflow_id")
    op.execute("DROP TABLE IF EXISTS workflow_runs")
    op.execute("DROP TABLE IF EXISTS workflows")
