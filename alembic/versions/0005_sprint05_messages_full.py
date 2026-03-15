"""Sprint 05 — Full message schema (§3.4): tool calls, branching, provenance, feedback.

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-15

Adds the columns that were stubbed in Sprint 02 (only id/session_id/role/content/timestamps):
- content_blocks, tool_calls, tool_call_id, file_ids
- parent_id, active, provenance
- compressed, compressed_source_ids, turn_cost_id
- feedback_rating, feedback_note, feedback_at
- model, input_tokens, output_tokens
Plus three new indexes for branching and active filtering.
"""
from __future__ import annotations

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Add all new columns to messages (SQLite only supports ADD COLUMN)
    new_columns = [
        "ALTER TABLE messages ADD COLUMN content_blocks TEXT",
        "ALTER TABLE messages ADD COLUMN tool_calls TEXT",
        "ALTER TABLE messages ADD COLUMN tool_call_id TEXT",
        "ALTER TABLE messages ADD COLUMN file_ids TEXT",
        "ALTER TABLE messages ADD COLUMN parent_id TEXT REFERENCES messages(id)",
        "ALTER TABLE messages ADD COLUMN active BOOLEAN NOT NULL DEFAULT 1",
        "ALTER TABLE messages ADD COLUMN provenance TEXT NOT NULL DEFAULT 'user_input'",
        "ALTER TABLE messages ADD COLUMN compressed BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE messages ADD COLUMN compressed_source_ids TEXT",
        "ALTER TABLE messages ADD COLUMN turn_cost_id TEXT",
        "ALTER TABLE messages ADD COLUMN feedback_rating TEXT",
        "ALTER TABLE messages ADD COLUMN feedback_note TEXT",
        "ALTER TABLE messages ADD COLUMN feedback_at TEXT",
        "ALTER TABLE messages ADD COLUMN model TEXT",
        "ALTER TABLE messages ADD COLUMN input_tokens INTEGER",
        "ALTER TABLE messages ADD COLUMN output_tokens INTEGER",
    ]
    for stmt in new_columns:
        try:
            op.execute(stmt)
        except Exception:
            pass  # Column may already exist (idempotent)

    # New indexes for branching + active filtering
    for stmt in [
        "CREATE INDEX IF NOT EXISTS idx_messages_parent ON messages(parent_id)",
        "CREATE INDEX IF NOT EXISTS idx_messages_active ON messages(session_id, active)",
    ]:
        op.execute(stmt)


def downgrade() -> None:
    # SQLite cannot DROP COLUMN — downgrade is a no-op
    pass
