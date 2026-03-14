"""Alembic environment — configures the SQLite database URL from app paths.

Tequila v2 uses aiosqlite at runtime but Alembic introspects the schema via
the synchronous ``sqlite3`` driver.  We therefore use a plain
``sqlite:///...`` URL here (no ``+aiosqlite``) — migrations run synchronously
at startup, separate from the async request-handling path.
"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make sure the project root is importable when running ``alembic`` from the
# command line (i.e., when ``app/`` is not already on sys.path).
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from app.paths import db_path  # noqa: E402 — after sys.path adjustment

# ── Alembic Config object ─────────────────────────────────────────────────────

config = context.config

# Apply the ini-file logging config (unless the application already set it up).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override the SQLite URL with the runtime-resolved path so dev paths and
# frozen-mode paths both work correctly.  Use as_posix() to produce
# forward-slash paths accepted by SQLAlchemy on Windows.
config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path().as_posix()}")


# ── Migrations ────────────────────────────────────────────────────────────────


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generate SQL to stdout)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live SQLite database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=None,
            # SQLite does not support transactional DDL in the normal sense;
            # render_as_batch enables Alembic's batch-mode for ALTER TABLE ops.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
