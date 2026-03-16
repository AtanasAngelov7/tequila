"""Sprint 10 — Knowledge sources table (§5.14).

Revision ID: 0010
Revises: 0009
"""
from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_sources (
            id                  TEXT PRIMARY KEY,
            name                TEXT NOT NULL,
            description         TEXT NOT NULL DEFAULT '',
            backend             TEXT NOT NULL CHECK(backend IN ('chroma','pgvector','faiss','http')),
            query_mode          TEXT NOT NULL DEFAULT 'text' CHECK(query_mode IN ('text','vector')),
            embedding_provider  TEXT,
            auto_recall         INTEGER NOT NULL DEFAULT 0,
            priority            INTEGER NOT NULL DEFAULT 100,
            max_results         INTEGER NOT NULL DEFAULT 5,
            similarity_threshold REAL NOT NULL DEFAULT 0.6,
            connection_json     TEXT NOT NULL DEFAULT '{}',
            allowed_agents_json TEXT,
            status              TEXT NOT NULL DEFAULT 'disabled' CHECK(status IN ('active','error','disabled')),
            error_message       TEXT,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            last_health_check   TEXT,
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_knowledge_sources_status
        ON knowledge_sources (status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_knowledge_sources_backend
        ON knowledge_sources (backend)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_sources")
