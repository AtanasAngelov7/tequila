"""Shared pytest fixtures for Tequila v2 tests (§27).

All fixtures are async-aware (``asyncio_mode = "auto"`` in pyproject.toml).
"""
from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

# Ensure the project root is on sys.path when running tests directly.
_project_root = Path(__file__).resolve().parent.parent  # repo root, not tests/
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ── Database fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
async def test_db_path(tmp_path: Path) -> Path:
    """Return a temporary path for a test SQLite database.

    The filename matches ``DB_FILENAME`` so that ``db_path()`` (called by
    ``alembic/env.py``) resolves to the same file that ``startup()`` opens.
    """
    from app.constants import DB_FILENAME
    return tmp_path / DB_FILENAME


@pytest.fixture
async def migrated_db(test_db_path: Path) -> AsyncGenerator[object, None]:
    """Create a temporary database with baseline migrations applied.

    Yields the open ``aiosqlite.Connection`` object.
    """
    from app.db.connection import startup, shutdown, _write_locks

    # Override the data directory to use the temp path.
    os.environ["TEQUILA_DATA_DIR"] = str(test_db_path.parent)

    # Reset the write lock registry for isolation between tests.
    _write_locks.clear()

    # Run Alembic migrations BEFORE opening the async connection so that
    # the aiosqlite connection sees the fully-migrated schema from the start.
    from alembic.config import Config
    from alembic import command

    alembic_cfg = Config(str(_project_root / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{test_db_path.as_posix()}")
    alembic_cfg.set_main_option("script_location", str(_project_root / "alembic"))
    command.upgrade(alembic_cfg, "head")

    # Now open the async connection (tables already exist).
    await startup(test_db_path)

    from app.db.connection import get_app_db
    yield get_app_db()

    await shutdown()
    _write_locks.pop(test_db_path, None)
    os.environ.pop("TEQUILA_DATA_DIR", None)


@pytest.fixture
async def config_store(migrated_db: object) -> object:
    """Return a hydrated ``ConfigStore`` backed by the test database."""
    import aiosqlite
    from app.config import ConfigStore

    store = ConfigStore(migrated_db)  # type: ignore[arg-type]
    await store.hydrate()
    return store


# ── Gateway fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def test_gateway() -> object:
    """Return a fresh ``GatewayRouter`` (not the process singleton)."""
    from app.gateway.router import GatewayRouter

    r = GatewayRouter()
    r.start()
    return r


# ── FastAPI test client ───────────────────────────────────────────────────────


@pytest.fixture
async def test_app(test_db_path: Path) -> AsyncGenerator[object, None]:
    """Create and start the FastAPI application for integration testing.

    Uses ``asgi-lifespan`` to run the full startup/shutdown lifecycle so that
    the database, config store, and gateway are properly initialised.
    """
    os.environ["TEQUILA_DATA_DIR"] = str(test_db_path.parent)

    from asgi_lifespan import LifespanManager
    from httpx import AsyncClient, ASGITransport

    from app.api.app import create_app
    from app.db.connection import _write_locks

    _write_locks.clear()

    application = create_app()
    async with LifespanManager(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),  # type: ignore[arg-type]
            base_url="http://test",
        ) as client:
            yield client

    os.environ.pop("TEQUILA_DATA_DIR", None)
    _write_locks.clear()
