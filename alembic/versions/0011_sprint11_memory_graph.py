"""Sprint 11 — Memory events audit trail and knowledge graph edges (§5.9, §5.11).

Revision ID: 0011
Revises: 0010
"""
from __future__ import annotations

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── memory_events: audit trail for all memory + entity mutations (§5.9) ───
    op.execute("""
        CREATE TABLE IF NOT EXISTS memory_events (
            id              TEXT PRIMARY KEY,
            memory_id       TEXT,
            entity_id       TEXT,
            event_type      TEXT NOT NULL,
            actor           TEXT NOT NULL DEFAULT 'system',
            actor_id        TEXT,
            old_content     TEXT,
            new_content     TEXT,
            reason          TEXT,
            metadata        TEXT NOT NULL DEFAULT '{}',
            timestamp       TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_memory_events_memory_id ON memory_events(memory_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_memory_events_entity_id ON memory_events(entity_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_memory_events_timestamp ON memory_events(timestamp)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_memory_events_event_type ON memory_events(event_type)")

    # ── graph_edges: knowledge graph edges (§5.11) ────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS graph_edges (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id   TEXT NOT NULL,
            source_type TEXT NOT NULL,
            target_id   TEXT NOT NULL,
            target_type TEXT NOT NULL,
            edge_type   TEXT NOT NULL,
            weight      REAL NOT NULL DEFAULT 1.0,
            label       TEXT,
            metadata    TEXT NOT NULL DEFAULT '{}',
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(source_id, target_id, edge_type)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_graph_edges_type ON graph_edges(edge_type)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS graph_edges")
    op.execute("DROP TABLE IF EXISTS memory_events")
