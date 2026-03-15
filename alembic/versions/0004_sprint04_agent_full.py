"""Sprint 04 — Full agent model, skills + skill_resources tables (§4.1, §4.5.7).

Revision ID: 0004
Revises: 0003

Adds the Sprint 04 columns to the ``agents`` table (from the minimal Sprint 03
version) and creates the new ``skills`` and ``skill_resources`` tables required
for the three-level skill system (§4.5).

Also seeds the tools-related config keys.
"""
from __future__ import annotations

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ── Extend agents table ──────────────────────────────────────────────────
    # New columns added to the minimal Sprint 03 agents table.
    op.execute("ALTER TABLE agents ADD COLUMN role TEXT NOT NULL DEFAULT 'main'")
    op.execute("ALTER TABLE agents ADD COLUMN soul TEXT NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE agents ADD COLUMN fallback_provider_id TEXT")
    op.execute("ALTER TABLE agents ADD COLUMN tools TEXT NOT NULL DEFAULT '[]'")
    op.execute("ALTER TABLE agents ADD COLUMN skills TEXT NOT NULL DEFAULT '[]'")
    op.execute("ALTER TABLE agents ADD COLUMN default_policy TEXT NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE agents ADD COLUMN memory_scope TEXT NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE agents ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE agents ADD COLUMN escalation TEXT NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE agents ADD COLUMN version INTEGER NOT NULL DEFAULT 1")

    op.execute("CREATE INDEX IF NOT EXISTS idx_agents_role ON agents(role)")

    # ── skills table (§4.5.7) ────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS skills (
            skill_id              TEXT PRIMARY KEY,
            name                  TEXT NOT NULL,
            description           TEXT NOT NULL,
            version               TEXT NOT NULL DEFAULT '1.0.0',
            summary               TEXT NOT NULL DEFAULT '',
            instructions          TEXT NOT NULL DEFAULT '',
            required_tools        TEXT NOT NULL DEFAULT '[]',
            recommended_tools     TEXT NOT NULL DEFAULT '[]',
            activation_mode       TEXT NOT NULL DEFAULT 'trigger',
            trigger_patterns      TEXT NOT NULL DEFAULT '[]',
            trigger_tool_presence TEXT NOT NULL DEFAULT '[]',
            priority              INTEGER NOT NULL DEFAULT 100,
            tags                  TEXT NOT NULL DEFAULT '[]',
            author                TEXT NOT NULL DEFAULT 'user',
            is_builtin            BOOLEAN NOT NULL DEFAULT 0,
            created_at            TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_skills_tags ON skills(tags)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_skills_builtin ON skills(is_builtin)")

    # ── skill_resources table (§4.5.7) ───────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_resources (
            resource_id    TEXT PRIMARY KEY,
            skill_id       TEXT NOT NULL REFERENCES skills(skill_id) ON DELETE CASCADE,
            name           TEXT NOT NULL,
            description    TEXT NOT NULL DEFAULT '',
            content        TEXT NOT NULL,
            content_tokens INTEGER,
            created_at     TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_skill_resources_skill "
        "ON skill_resources(skill_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS skill_resources")
    op.execute("DROP TABLE IF EXISTS skills")
    # SQLite doesn't support DROP COLUMN; we recreate to remove added columns.
    op.execute(
        """
        CREATE TABLE agents_backup AS
        SELECT agent_id, name, provider, default_model, persona, status,
               created_at, updated_at
        FROM agents
        """
    )
    op.execute("DROP TABLE agents")
    op.execute("ALTER TABLE agents_backup RENAME TO agents")
