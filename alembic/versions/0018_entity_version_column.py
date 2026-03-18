"""Add version column to entities table for integer-based OCC (TD-300).

Replaces timestamp-based optimistic concurrency control with an integer
version counter to eliminate same-millisecond race conditions.

Revision ID: 0018
Revises: 0017
Create Date: 2026-03-18
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE entities ADD COLUMN version INTEGER NOT NULL DEFAULT 1")


def downgrade() -> None:
    # SQLite doesn't support DROP COLUMN < 3.35, so use batch
    with op.batch_alter_table("entities") as batch_op:
        batch_op.drop_column("version")
