"""Sprint 14a — Skills system: skills + skill_resources tables (§4.5.7).

Revision ID: 0016
Revises: 0015
"""
from __future__ import annotations

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── skills: core skill definitions ────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS skills (
            skill_id            TEXT PRIMARY KEY,
            name                TEXT NOT NULL,
            description         TEXT NOT NULL,
            version             TEXT NOT NULL DEFAULT '1.0.0',
            summary             TEXT NOT NULL DEFAULT '',
            instructions        TEXT NOT NULL DEFAULT '',
            required_tools      TEXT NOT NULL DEFAULT '[]',
            recommended_tools   TEXT NOT NULL DEFAULT '[]',
            activation_mode     TEXT NOT NULL DEFAULT 'trigger',
            trigger_patterns    TEXT NOT NULL DEFAULT '[]',
            trigger_tool_presence TEXT NOT NULL DEFAULT '[]',
            priority            INTEGER NOT NULL DEFAULT 100,
            tags                TEXT NOT NULL DEFAULT '[]',
            author              TEXT NOT NULL DEFAULT 'user',
            is_builtin          BOOLEAN NOT NULL DEFAULT 0,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_skills_tags ON skills(tags)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_skills_builtin ON skills(is_builtin)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_skills_activation ON skills(activation_mode)")

    # ── skill_resources: Level 3 reference material ───────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS skill_resources (
            resource_id     TEXT PRIMARY KEY,
            skill_id        TEXT NOT NULL REFERENCES skills(skill_id) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            content         TEXT NOT NULL,
            content_tokens  INTEGER,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_skill_resources_skill ON skill_resources(skill_id)")

    # ── soul_versions: version history for SoulConfig (§4.1a) ─────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS soul_versions (
            version_id  TEXT PRIMARY KEY,
            agent_id    TEXT NOT NULL,
            version_num INTEGER NOT NULL,
            soul_json   TEXT NOT NULL,
            change_note TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            UNIQUE(agent_id, version_num)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_soul_versions_agent ON soul_versions(agent_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_soul_versions_agent")
    op.execute("DROP TABLE IF EXISTS soul_versions")
    op.execute("DROP INDEX IF EXISTS idx_skill_resources_skill")
    op.execute("DROP TABLE IF EXISTS skill_resources")
    op.execute("DROP INDEX IF EXISTS idx_skills_activation")
    op.execute("DROP INDEX IF EXISTS idx_skills_builtin")
    op.execute("DROP INDEX IF EXISTS idx_skills_tags")
    op.execute("DROP TABLE IF EXISTS skills")
