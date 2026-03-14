"""Low-level database introspection and utility helpers (§14.1, §20).

Used by Alembic ``env.py`` and by runtime code that needs to inspect the current
schema.  No SQLAlchemy — raw ``aiosqlite`` and ``sqlite3`` only.
"""
from __future__ import annotations

import logging
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

# ── Introspection ─────────────────────────────────────────────────────────────


async def table_exists(db: aiosqlite.Connection, name: str) -> bool:
    """Return ``True`` if *name* is a table in the current database."""
    cursor = await db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    )
    row = await cursor.fetchone()
    return row is not None


async def column_exists(db: aiosqlite.Connection, table: str, column: str) -> bool:
    """Return ``True`` if *column* exists in *table* (uses ``PRAGMA table_info``)."""
    cursor = await db.execute(f"PRAGMA table_info({table})")
    rows = await cursor.fetchall()
    return any(row["name"] == column for row in rows)


# ── Execution helpers ─────────────────────────────────────────────────────────


async def execute_script(db: aiosqlite.Connection, sql: str) -> None:
    """Execute a multi-statement SQL string statement-by-statement.

    Unlike ``db.executescript()`` (which issues an implicit ``COMMIT``), this
    helper splits on ``;`` and runs each non-empty statement individually,
    which is WAL-safe and works correctly inside an explicit transaction.
    """
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    for stmt in statements:
        await db.execute(stmt)


# ── Row conversion ────────────────────────────────────────────────────────────


def row_to_dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    """Convert an ``aiosqlite.Row`` to a plain ``dict``, or ``None`` if *row* is ``None``."""
    if row is None:
        return None
    return dict(row)
