"""Sprint 13 — Scheduler & cron-based agent sessions (§7.1–§7.3, §20.8).

Tables added:
  scheduled_tasks — cron-based scheduled agent run definitions

Revision ID: 0015
Revises: 0014
"""
from __future__ import annotations

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id              TEXT NOT NULL PRIMARY KEY,
            name            TEXT NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            cron_expression TEXT NOT NULL,
            agent_id        TEXT NOT NULL,
            prompt_template TEXT NOT NULL DEFAULT '',
            enabled         INTEGER NOT NULL DEFAULT 1
                CHECK (enabled IN (0, 1)),
            announce        INTEGER NOT NULL DEFAULT 0
                CHECK (announce IN (0, 1)),
            last_run_at     TEXT,
            last_run_status TEXT
                CHECK (last_run_status IS NULL OR last_run_status IN ('success', 'error', 'skipped')),
            last_run_error  TEXT,
            next_run_at     TEXT,
            run_count       INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_scheduled_tasks_enabled ON scheduled_tasks (enabled)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_scheduled_tasks_next_run ON scheduled_tasks (next_run_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_scheduled_tasks_agent ON scheduled_tasks (agent_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS scheduled_tasks")
