"""TD-S5 — Add CHECK constraints for enum-like columns (TD-85).

These constraints enforce at the DB layer what the application already
validates via ``Literal`` types (T1, T3, T4, T10).  They are applied via
Alembic batch mode (SQLite requires table recreation to add constraints).

Note: SQLite only enforces CHECK constraints added at CREATE TABLE time.
Alembic's ``batch_alter_table`` recreates the table, so the constraints are
effective for all writes from this migration forward.

Revision ID: 0013
Revises: 0012
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── memory_extracts ───────────────────────────────────────────────────────
    with op.batch_alter_table("memory_extracts") as batch_op:
        batch_op.create_check_constraint(
            "ck_memory_extracts_memory_type",
            "memory_type IN ('identity','preference','fact','experience','task','relationship','skill')",
        )
        batch_op.create_check_constraint(
            "ck_memory_extracts_source_type",
            "source_type IN ('extraction','user_created','agent_created','promoted','merged')",
        )
        batch_op.create_check_constraint(
            "ck_memory_extracts_scope",
            "scope IN ('global','agent','session')",
        )
        batch_op.create_check_constraint(
            "ck_memory_extracts_status",
            "status IN ('active','archived','deleted')",
        )

    # ── entities ──────────────────────────────────────────────────────────────
    with op.batch_alter_table("entities") as batch_op:
        batch_op.create_check_constraint(
            "ck_entities_entity_type",
            "entity_type IN ('person','organization','project','location','tool','concept','event','date')",
        )
        batch_op.create_check_constraint(
            "ck_entities_status",
            "status IN ('active','merged','deleted')",
        )


def downgrade() -> None:
    with op.batch_alter_table("entities") as batch_op:
        batch_op.drop_constraint("ck_entities_status", type_="check")
        batch_op.drop_constraint("ck_entities_entity_type", type_="check")

    with op.batch_alter_table("memory_extracts") as batch_op:
        batch_op.drop_constraint("ck_memory_extracts_status", type_="check")
        batch_op.drop_constraint("ck_memory_extracts_scope", type_="check")
        batch_op.drop_constraint("ck_memory_extracts_source_type", type_="check")
        batch_op.drop_constraint("ck_memory_extracts_memory_type", type_="check")
