"""Baseline schema — sessions, messages, config, audit_log.

Revision ID: 0001
Revises: (none — first migration)
Create Date: 2026-03-14

Creates the four core tables required by Sprint 01:

- ``sessions``   — conversation sessions (§3.2, §14.1)
- ``messages``   — session messages (§3.4, §14.1)
- ``config``     — key-value configuration store (§14.4)
- ``audit_log``  — security and event audit trail (§12.1)
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# ── Revision identifiers ──────────────────────────────────────────────────────

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


# ── Upgrade ───────────────────────────────────────────────────────────────────


def upgrade() -> None:
    # ── sessions ──────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id          TEXT PRIMARY KEY,
            session_key         TEXT NOT NULL UNIQUE,
            kind                TEXT NOT NULL DEFAULT 'user',
            agent_id            TEXT NOT NULL DEFAULT 'main',
            channel             TEXT NOT NULL DEFAULT 'webchat',
            policy              TEXT NOT NULL DEFAULT '{}',
            status              TEXT NOT NULL DEFAULT 'active',
            parent_session_key  TEXT,
            title               TEXT,
            summary             TEXT,
            message_count       INTEGER NOT NULL DEFAULT 0,
            last_message_at     TEXT,
            metadata            TEXT NOT NULL DEFAULT '{}',
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
            version             INTEGER NOT NULL DEFAULT 1
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_key ON sessions(session_key)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC)"
    )

    # ── messages ──────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id                      TEXT PRIMARY KEY,
            session_id              TEXT NOT NULL REFERENCES sessions(session_id),
            role                    TEXT NOT NULL,
            content                 TEXT NOT NULL DEFAULT '',
            content_blocks          TEXT,
            tool_calls              TEXT,
            tool_call_id            TEXT,
            file_ids                TEXT,
            parent_id               TEXT REFERENCES messages(id),
            active                  BOOLEAN NOT NULL DEFAULT 1,
            provenance              TEXT NOT NULL DEFAULT 'user_input',
            compressed              BOOLEAN NOT NULL DEFAULT 0,
            compressed_source_ids   TEXT,
            turn_cost_id            TEXT,
            feedback_rating         TEXT,
            feedback_note           TEXT,
            feedback_at             TEXT,
            model                   TEXT,
            input_tokens            INTEGER,
            output_tokens           INTEGER,
            created_at              TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at              TEXT
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_parent ON messages(parent_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_active ON messages(session_id, active)"
    )

    # ── config ────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key              TEXT PRIMARY KEY,
            value            TEXT NOT NULL,
            value_type       TEXT NOT NULL,
            category         TEXT NOT NULL,
            description      TEXT,
            default_val      TEXT,
            requires_restart BOOLEAN NOT NULL DEFAULT 0,
            updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
            version          INTEGER NOT NULL DEFAULT 1
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_category ON config(category)"
    )

    # ── audit_log ─────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id              TEXT PRIMARY KEY,
            actor           TEXT NOT NULL,
            action          TEXT NOT NULL,
            resource_type   TEXT,
            resource_id     TEXT,
            outcome         TEXT NOT NULL DEFAULT 'success',
            detail          TEXT,
            ip_address      TEXT,
            session_key     TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC)"
    )

    # ── Seed default config rows ──────────────────────────────────────────────
    # Minimal set of config keys populated at baseline.  Additional keys are
    # seeded by later migrations as features are implemented.
    _seed_config(op)


def _seed_config(op: object) -> None:  # type: ignore[valid-type]
    """Insert default configuration rows that must exist from day one."""
    defaults: list[tuple[str, str, str, str, str, str, int]] = [
        # key, value, value_type, category, description, default_val, requires_restart
        (
            "server.host",
            '"127.0.0.1"',
            "str",
            "server",
            "HTTP server bind address",
            '"127.0.0.1"',
            1,
        ),
        (
            "server.port",
            "8000",
            "int",
            "server",
            "HTTP server port",
            "8000",
            1,
        ),
        (
            "server.gateway_token",
            '""',
            "str",
            "server",
            "Gateway authentication token (empty = disabled in local mode)",
            '""',
            1,
        ),
        (
            "logging.level",
            '"INFO"',
            "str",
            "logging",
            "Root log level: DEBUG, INFO, WARNING, ERROR",
            '"INFO"',
            0,
        ),
        (
            "logging.format",
            '"json"',
            "str",
            "logging",
            "Log format: json or text",
            '"json"',
            0,
        ),
        (
            "session.idle_timeout_days",
            "7",
            "int",
            "session",
            "Days of inactivity before a session transitions to idle",
            "7",
            0,
        ),
        (
            "session.auto_summarize_on_idle",
            "true",
            "bool",
            "session",
            "Generate a summary when a session transitions to idle",
            "true",
            0,
        ),
    ]

    for key, value, value_type, category, description, default_val, requires_restart in defaults:
        op.execute(
            sa.text(
                """
                INSERT OR IGNORE INTO config
                    (key, value, value_type, category, description, default_val, requires_restart)
                VALUES
                    (:key, :value, :value_type, :category, :description, :default_val, :requires_restart)
                """
            ).bindparams(
                key=key,
                value=value,
                value_type=value_type,
                category=category,
                description=description,
                default_val=default_val,
                requires_restart=requires_restart,
            )
        )


# ── Downgrade ─────────────────────────────────────────────────────────────────


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log")
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS sessions")
    op.execute("DROP TABLE IF EXISTS config")
