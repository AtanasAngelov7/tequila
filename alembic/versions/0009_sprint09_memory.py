"""Sprint 09 — memory system tables (§5.3, §5.4, §5.10, §5.13).

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-16
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:  # noqa: D103
    # ── vault_notes ───────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_notes (
            id           TEXT NOT NULL PRIMARY KEY,
            title        TEXT NOT NULL,
            slug         TEXT NOT NULL,
            filename     TEXT NOT NULL,
            content_hash TEXT NOT NULL DEFAULT '',
            wikilinks    TEXT NOT NULL DEFAULT '[]',
            tags         TEXT NOT NULL DEFAULT '[]',
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(slug),
            UNIQUE(filename)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_vault_notes_slug "
        "ON vault_notes (slug)"
    )

    # ── embeddings ────────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS embeddings (
            id          TEXT NOT NULL PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_id   TEXT NOT NULL,
            model_id    TEXT NOT NULL,
            vector      BLOB NOT NULL,
            dimensions  INTEGER NOT NULL,
            text_hash   TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(source_type, source_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_embeddings_source "
        "ON embeddings (source_type, source_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_embeddings_model "
        "ON embeddings (model_id)"
    )

    # ── memory_extracts ───────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_extracts (
            id                TEXT NOT NULL PRIMARY KEY,
            content           TEXT NOT NULL,
            memory_type       TEXT NOT NULL,
            always_recall     INTEGER NOT NULL DEFAULT 0,
            recall_weight     REAL NOT NULL DEFAULT 1.0,
            pinned            INTEGER NOT NULL DEFAULT 0,
            created_at        TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
            last_accessed     TEXT NOT NULL DEFAULT (datetime('now')),
            access_count      INTEGER NOT NULL DEFAULT 0,
            expires_at        TEXT,
            decay_score       REAL NOT NULL DEFAULT 1.0,
            source_type       TEXT NOT NULL DEFAULT 'user_created',
            source_session_id TEXT,
            source_message_id TEXT,
            confidence        REAL NOT NULL DEFAULT 1.0,
            entity_ids        TEXT NOT NULL DEFAULT '[]',
            tags              TEXT NOT NULL DEFAULT '[]',
            scope             TEXT NOT NULL DEFAULT 'global',
            agent_id          TEXT,
            status            TEXT NOT NULL DEFAULT 'active',
            version           INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_extracts_type "
        "ON memory_extracts (memory_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_extracts_scope "
        "ON memory_extracts (scope, agent_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_extracts_status "
        "ON memory_extracts (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_extracts_recall "
        "ON memory_extracts (always_recall)"
    )

    # ── entities ──────────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS entities (
            id              TEXT NOT NULL PRIMARY KEY,
            name            TEXT NOT NULL,
            entity_type     TEXT NOT NULL,
            aliases         TEXT NOT NULL DEFAULT '[]',
            summary         TEXT NOT NULL DEFAULT '',
            properties      TEXT NOT NULL DEFAULT '{}',
            first_seen      TEXT NOT NULL DEFAULT (datetime('now')),
            last_referenced TEXT NOT NULL DEFAULT (datetime('now')),
            reference_count INTEGER NOT NULL DEFAULT 0,
            status          TEXT NOT NULL DEFAULT 'active',
            merged_into     TEXT,
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_entities_name ON entities (name)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_entities_type ON entities (entity_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_entities_status ON entities (status)"
    )

    # ── memory_entity_links ───────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_entity_links (
            memory_id  TEXT NOT NULL REFERENCES memory_extracts(id) ON DELETE CASCADE,
            entity_id  TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (memory_id, entity_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_entity_links_entity "
        "ON memory_entity_links (entity_id)"
    )


def downgrade() -> None:  # noqa: D103
    op.execute("DROP INDEX IF EXISTS idx_memory_entity_links_entity")
    op.execute("DROP TABLE IF EXISTS memory_entity_links")
    op.execute("DROP INDEX IF EXISTS idx_entities_status")
    op.execute("DROP INDEX IF EXISTS idx_entities_type")
    op.execute("DROP INDEX IF EXISTS idx_entities_name")
    op.execute("DROP TABLE IF EXISTS entities")
    op.execute("DROP INDEX IF EXISTS idx_memory_extracts_recall")
    op.execute("DROP INDEX IF EXISTS idx_memory_extracts_status")
    op.execute("DROP INDEX IF EXISTS idx_memory_extracts_scope")
    op.execute("DROP INDEX IF EXISTS idx_memory_extracts_type")
    op.execute("DROP TABLE IF EXISTS memory_extracts")
    op.execute("DROP INDEX IF EXISTS idx_embeddings_model")
    op.execute("DROP INDEX IF EXISTS idx_embeddings_source")
    op.execute("DROP TABLE IF EXISTS embeddings")
    op.execute("DROP INDEX IF EXISTS idx_vault_notes_slug")
    op.execute("DROP TABLE IF EXISTS vault_notes")
