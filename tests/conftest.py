"""Shared pytest fixtures for Tequila v2 tests (§27).

All fixtures are async-aware (``asyncio_mode = "auto"`` in pyproject.toml).

Performance note — Golden DB pattern
-------------------------------------
``_golden_db_bytes`` (session-scoped) runs ``alembic upgrade head`` **once**
per pytest session and captures the result as raw bytes.  Every
``migrated_db`` fixture call writes those bytes into a fresh per-test temp
file, giving full test isolation at sub-millisecond copy cost instead of
running all 12 migrations per test (~164 ms each, ~32 s total).

See ``tests/README.md`` for the full test-infrastructure guide, including what
to do when adding new migrations.
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


@pytest.fixture(scope="session")
def _golden_db_bytes(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    """Run Alembic **once per session** and return the migrated schema as bytes.

    Every ``migrated_db`` fixture call copies these bytes into a fresh temp
    file instead of re-running all 12 migrations — cutting ~30 s off the suite.
    """
    from app.constants import DB_FILENAME
    from alembic.config import Config
    from alembic import command

    golden_dir = tmp_path_factory.mktemp("golden")
    golden_path = golden_dir / DB_FILENAME

    # Point db_path() (called inside alembic/env.py) at the golden directory.
    os.environ["TEQUILA_DATA_DIR"] = str(golden_dir)
    try:
        alembic_cfg = Config(str(_project_root / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(_project_root / "alembic"))
        command.upgrade(alembic_cfg, "head")
        return golden_path.read_bytes()
    finally:
        os.environ.pop("TEQUILA_DATA_DIR", None)


@pytest.fixture
async def test_db_path(tmp_path: Path, _golden_db_bytes: bytes) -> Path:
    """Return a per-test temp path pre-populated with the migrated schema.

    The file is a byte-for-byte copy of the session-level golden DB, so each
    test gets full isolation without paying the Alembic migration cost again.
    """
    from app.constants import DB_FILENAME
    db_path = tmp_path / DB_FILENAME
    db_path.write_bytes(_golden_db_bytes)
    return db_path


@pytest.fixture
async def migrated_db(test_db_path: Path) -> AsyncGenerator[object, None]:
    """Yield an open aiosqlite connection against a fully-migrated test DB.

    The schema is already in place (copied from the session-level golden DB by
    ``test_db_path``), so no Alembic work is needed here.
    """
    from app.db.connection import startup, shutdown, _write_locks

    # Override the data directory to use the temp path.
    os.environ["TEQUILA_DATA_DIR"] = str(test_db_path.parent)

    # Reset the write lock registry for isolation between tests.
    _write_locks.clear()

    # Schema is already present — open the async connection directly.
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
