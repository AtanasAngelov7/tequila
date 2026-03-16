"""TD-S3: Add index on knowledge_sources.auto_recall (TD-135).

Revision ID: 0012
Revises: 0011
"""
from __future__ import annotations

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_knowledge_sources_auto_recall",
        "knowledge_sources",
        ["auto_recall"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_sources_auto_recall", table_name="knowledge_sources")
