"""Async SQLite connection lifecycle and write-transaction helper (§20.1, §20.2).

### Design decisions
- One global ``asyncio.Lock`` per database path serialises all writes; WAL mode
  allows unlimited concurrent readers without holding the lock.
- ``write_transaction`` wraps mutations in ``BEGIN IMMEDIATE`` so that SQLite
  immediately acquires a write lock, preventing ``SQLITE_BUSY`` under async
  concurrency.
- The application-lifetime connection (opened at startup, closed at shutdown)
  is stored in ``_app_conn`` and accessed via ``get_app_db()``.  Request-scoped
  connections are opened on demand through ``get_db`` / ``get_write_db``.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, TypeVar

import aiosqlite

logger = logging.getLogger(__name__)

# ── WAL pragmas ───────────────────────────────────────────────────────────────

_PRAGMAS: str = """
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
"""

# ── Per-path write locks (TD-235: reentrant) ─────────────────────────────────

class _ReentrantAsyncLock:
    """Async lock that allows the **same** asyncio Task to re-acquire."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task[Any] | None = None
        self._count: int = 0

    async def acquire(self) -> None:
        me = asyncio.current_task()
        if me is not None and me is self._owner:
            self._count += 1
            return
        await self._lock.acquire()
        self._owner = me
        self._count = 1

    def release(self) -> None:
        self._count -= 1
        if self._count == 0:
            self._owner = None
            self._lock.release()

    async def __aenter__(self) -> "_ReentrantAsyncLock":
        await self.acquire()
        return self

    async def __aexit__(self, *args: Any) -> None:
        self.release()


_write_locks: dict[Path, _ReentrantAsyncLock] = {}


def _get_write_lock(path: Path) -> _ReentrantAsyncLock:
    """Return (creating if necessary) the reentrant write lock for *path*."""
    if path not in _write_locks:
        _write_locks[path] = _ReentrantAsyncLock()
    return _write_locks[path]


# ── Application-lifetime connection ──────────────────────────────────────────

_app_conn: aiosqlite.Connection | None = None
_app_db_path: Path | None = None

T = TypeVar("T")


# ── Connection helpers ────────────────────────────────────────────────────────


async def open_db(path: Path) -> aiosqlite.Connection:
    """Open a new aiosqlite connection to *path* and apply WAL pragmas.

    The caller is responsible for closing the returned connection.
    Row factory is set to ``aiosqlite.Row`` so columns are accessible by name.
    """
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    await conn.executescript(_PRAGMAS)
    logger.debug("Opened DB connection", extra={"db_path": str(path)})
    return conn


@asynccontextmanager
async def get_db(path: Path | None = None) -> AsyncGenerator[aiosqlite.Connection, None]:
    """Read-only context manager — yields a connection without acquiring the write lock.

    WAL mode allows concurrent readers, so this is safe to use any time.
    If *path* is ``None``, falls back to the application-lifetime connection.
    """
    if path is None:
        yield get_app_db()
        return
    conn = await open_db(path)
    try:
        yield conn
    finally:
        await conn.close()


@asynccontextmanager
async def get_write_db(path: Path | None = None) -> AsyncGenerator[aiosqlite.Connection, None]:
    """Write context manager — acquires the write lock then opens ``BEGIN IMMEDIATE``.

    Combines ``_get_write_lock`` + ``write_transaction`` so callers get a
    fully-protected write connection in a single ``async with`` block.
    """
    effective_path = path or _app_db_path
    if effective_path is None:
        raise RuntimeError("No database path available; did startup() run?")
    lock = _get_write_lock(effective_path)
    if path is None:
        # Use the already-open app connection rather than opening a new one.
        conn = get_app_db()
        async with lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                await conn.commit()
            except BaseException:
                await conn.rollback()
                raise
    else:
        conn = await open_db(path)
        try:
            async with lock:
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    yield conn
                    await conn.commit()
                except BaseException:
                    await conn.rollback()
                    raise
        finally:
            await conn.close()


@asynccontextmanager
async def write_transaction(
    conn: aiosqlite.Connection,
    path: Path | None = None,
) -> AsyncGenerator[aiosqlite.Connection, None]:
    """Wrap *conn* in a serialised ``BEGIN IMMEDIATE`` transaction.

    Acquires the write lock for *path* (or ``_app_db_path`` if ``None``),
    issues ``BEGIN IMMEDIATE``, commits on success, rolls back on any exception.

    Usage::

        async with write_transaction(db):
            await db.execute("INSERT INTO ...", (...))
    """
    effective_path = path or _app_db_path
    if effective_path is None:
        raise RuntimeError("No database path available; did startup() run?")
    lock = _get_write_lock(effective_path)
    async with lock:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise


# ── Lifecycle ─────────────────────────────────────────────────────────────────


async def startup(path: Path) -> None:
    """Open the application-lifetime connection and apply WAL pragmas.

    Called once inside the FastAPI lifespan startup handler.  The connection
    remains open for the entire process lifetime.
    """
    global _app_conn, _app_db_path  # noqa: PLW0603
    path.parent.mkdir(parents=True, exist_ok=True)
    _app_conn = await open_db(path)
    _app_db_path = path
    logger.info("Database startup complete", extra={"db_path": str(path)})


async def shutdown() -> None:
    """Close the application-lifetime connection gracefully.

    Called inside the FastAPI lifespan shutdown handler.
    """
    global _app_conn  # noqa: PLW0603
    if _app_conn is not None:
        await _app_conn.close()
        _app_conn = None
        logger.info("Database connection closed.")


def get_app_db() -> aiosqlite.Connection:
    """Return the open application-lifetime connection.

    Raises ``RuntimeError`` if ``startup()`` has not been called yet.
    Intended for use in FastAPI ``Depends`` providers (see ``app.api.deps``).
    """
    if _app_conn is None:
        raise RuntimeError("Database not initialised. Call db.startup() first.")
    return _app_conn
