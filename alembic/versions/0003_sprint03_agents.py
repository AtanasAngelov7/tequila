"""Sprint 03 — agents table + setup wizard config keys (§15.1, §4.1).

Revision ID: 0003
Revises: 0002

Creates the minimal ``agents`` table required by the first-run setup wizard.
The full agent model with skills, memory config, tool permissions, etc. is
expanded in Sprint 04.  This migration establishes the table so the wizard
can persist the user-created main agent before the full agent subsystem lands.

Also seeds the ``setup.*`` config keys used by the first-run setup wizard.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────────────

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


# ── Upgrade ───────────────────────────────────────────────────────────────────


def upgrade() -> None:
    # ── agents table ─────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agents (
            agent_id    TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            provider    TEXT NOT NULL DEFAULT '',
            default_model TEXT NOT NULL DEFAULT '',
            persona     TEXT,
            status      TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'paused', 'archived')),
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status)"
    )

    # ── setup.* config keys ───────────────────────────────────────────────────
    _setup_keys = [
        # key, value, value_type, category, description, default_val, requires_restart
        (
            "setup.complete",
            "false",
            "bool",
            "setup",
            "True once the first-run setup wizard has been completed",
            "false",
            0,
        ),
        (
            "setup.user_name",
            '""',
            "str",
            "setup",
            "Display name entered during setup wizard",
            '""',
            0,
        ),
        (
            "setup.provider",
            '""',
            "str",
            "setup",
            "LLM provider chosen during setup (anthropic|openai|ollama)",
            '""',
            0,
        ),
        (
            "setup.default_model",
            '""',
            "str",
            "setup",
            "Default model chosen during setup (provider:model format)",
            '""',
            0,
        ),
        (
            "setup.main_agent_id",
            '""',
            "str",
            "setup",
            "agent_id of the main agent created during setup",
            '""',
            0,
        ),
    ]

    for key, value, value_type, category, description, default_val, requires_restart in _setup_keys:
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
    op.execute("DROP INDEX IF EXISTS idx_agents_status")
    op.execute("DROP TABLE IF EXISTS agents")
    # Config keys are left in place on downgrade to avoid data loss.
    # Run: DELETE FROM config WHERE key LIKE 'setup.%' to remove manually.
