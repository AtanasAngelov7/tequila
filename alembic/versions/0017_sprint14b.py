"""Sprint 14b — Notifications, Budget, Audit sinks, App Lock, Backup.

Creates:
  - notifications table
  - notification_preferences table
  - turn_costs table (§23.1)
  - budget_caps table (§23.3)
  - provider_pricing table (§23.1)
  - audit_sinks table
  - audit_retention table
  - app_lock table
  - backup_configs table

Revision ID: 0017
Revises: 0016
"""
from __future__ import annotations

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── notifications ─────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id                  TEXT PRIMARY KEY,
            notification_type   TEXT NOT NULL,
            title               TEXT NOT NULL,
            body                TEXT NOT NULL,
            severity            TEXT NOT NULL DEFAULT 'info',
            action_url          TEXT,
            source_session_key  TEXT,
            read                INTEGER NOT NULL DEFAULT 0,
            created_at          TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(notification_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at)")

    # ── notification_preferences ──────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS notification_preferences (
            id                  TEXT PRIMARY KEY,
            notification_type   TEXT NOT NULL UNIQUE,
            channels            TEXT NOT NULL DEFAULT '["in_app"]',
            enabled             INTEGER NOT NULL DEFAULT 1,
            updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # ── provider_pricing ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS provider_pricing (
            id                  TEXT PRIMARY KEY,
            provider_id         TEXT NOT NULL,
            model               TEXT NOT NULL,
            input_cost_per_1k   REAL NOT NULL DEFAULT 0.0,
            output_cost_per_1k  REAL NOT NULL DEFAULT 0.0,
            effective_date      TEXT NOT NULL DEFAULT (date('now')),
            UNIQUE(provider_id, model)
        )
    """)

    # ── turn_costs ────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS turn_costs (
            turn_id             TEXT PRIMARY KEY,
            session_id          TEXT NOT NULL,
            agent_id            TEXT NOT NULL,
            provider_id         TEXT NOT NULL,
            model               TEXT NOT NULL,
            input_tokens        INTEGER NOT NULL DEFAULT 0,
            output_tokens       INTEGER NOT NULL DEFAULT 0,
            cost_usd            REAL NOT NULL DEFAULT 0.0,
            timestamp           TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_turn_costs_session ON turn_costs(session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_turn_costs_agent ON turn_costs(agent_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_turn_costs_ts ON turn_costs(timestamp)")

    # ── budget_caps ───────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS budget_caps (
            id                  TEXT PRIMARY KEY,
            period              TEXT NOT NULL CHECK(period IN ('daily','monthly')),
            limit_usd           REAL NOT NULL,
            action              TEXT NOT NULL DEFAULT 'warn' CHECK(action IN ('warn','block')),
            updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(period)
        )
    """)

    # ── audit_sinks ───────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_sinks (
            id                  TEXT PRIMARY KEY,
            kind                TEXT NOT NULL CHECK(kind IN ('sqlite','file','webhook')),
            name                TEXT NOT NULL UNIQUE,
            config              TEXT NOT NULL DEFAULT '{}',
            enabled             INTEGER NOT NULL DEFAULT 1,
            created_at          TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # ── audit_retention ───────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_retention (
            id                  TEXT PRIMARY KEY,
            sink_id             TEXT NOT NULL REFERENCES audit_sinks(id) ON DELETE CASCADE,
            retain_days         INTEGER NOT NULL DEFAULT 90,
            max_events          INTEGER,
            updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(sink_id)
        )
    """)

    # ── app_lock ──────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS app_lock (
            id                  INTEGER PRIMARY KEY CHECK(id = 1),
            pin_hash            TEXT,
            recovery_key_hash   TEXT,
            enabled             INTEGER NOT NULL DEFAULT 0,
            idle_timeout_seconds INTEGER NOT NULL DEFAULT 0,
            locked              INTEGER NOT NULL DEFAULT 0,
            updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Ensure exactly one row exists
    op.execute("INSERT OR IGNORE INTO app_lock(id) VALUES(1)")

    # ── backup_configs ────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS backup_configs (
            id                  INTEGER PRIMARY KEY CHECK(id = 1),
            enabled             INTEGER NOT NULL DEFAULT 1,
            schedule_cron       TEXT NOT NULL DEFAULT '0 3 * * *',
            retention_count     INTEGER NOT NULL DEFAULT 7,
            backup_dir          TEXT NOT NULL DEFAULT 'data/backups',
            updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    op.execute("INSERT OR IGNORE INTO backup_configs(id) VALUES(1)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS backup_configs")
    op.execute("DROP TABLE IF EXISTS app_lock")
    op.execute("DROP TABLE IF EXISTS audit_retention")
    op.execute("DROP TABLE IF EXISTS audit_sinks")
    op.execute("DROP TABLE IF EXISTS budget_caps")
    op.execute("DROP TABLE IF EXISTS turn_costs")
    op.execute("DROP TABLE IF EXISTS provider_pricing")
    op.execute("DROP TABLE IF EXISTS notification_preferences")
    op.execute("DROP TABLE IF EXISTS notifications")
