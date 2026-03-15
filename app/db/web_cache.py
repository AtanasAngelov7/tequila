"""Sprint 06 — Web cache storage (§17.2).

``WebCache`` wraps the ``web_cache`` SQLite table created by migration 0006.

Cache behaviour
---------------
- TTL default: 3600 s (1 hour).  Entries with ``fetched_at + ttl_s < now`` are
  considered stale.
- Conditional GET: ``etag`` and ``last_modified`` are stored and returned so the
  ``web_fetch`` tool can send conditional request headers.
- ``purge_expired()`` deletes all stale rows; call periodically or at startup.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiosqlite

logger = logging.getLogger(__name__)

DEFAULT_TTL_S: int = 3600


class WebCache:
    """Async web content cache backed by SQLite ``web_cache`` table.

    Parameters
    ----------
    db:
        Open ``aiosqlite.Connection``.  Typically the application-lifetime
        connection obtained via ``get_app_db()``.
    default_ttl_s:
        Seconds before a cached entry is considered stale.
    """

    def __init__(self, db: aiosqlite.Connection, default_ttl_s: int = DEFAULT_TTL_S) -> None:
        self._db = db
        self._default_ttl_s = default_ttl_s

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(tz=timezone.utc).isoformat()

    # ── Public API ────────────────────────────────────────────────────────────

    async def get(self, url: str) -> dict | None:
        """Return a cached entry for *url* if it exists and is still fresh.

        Returns
        -------
        dict | None
            Dict with keys ``content``, ``content_type``, ``etag``,
            ``last_modified`` — or ``None`` if not cached / stale.
        """
        async with self._db.execute(
            "SELECT content, content_type, fetched_at, ttl_s, etag, last_modified "
            "FROM web_cache WHERE url = ?",
            (url,),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return None

        fetched_at_str = row["fetched_at"]
        ttl_s = row["ttl_s"] or self._default_ttl_s

        try:
            fetched_at = datetime.fromisoformat(fetched_at_str)
        except ValueError:
            logger.warning("web_cache: invalid fetched_at for %r — treating as stale", url)
            return None

        now = datetime.now(tz=timezone.utc)
        if fetched_at.tzinfo is None:
            # Normalise naive datetimes stored by older code
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)

        if (now - fetched_at).total_seconds() > ttl_s:
            logger.debug("web_cache: stale entry for %r", url)
            return None

        return {
            "content": row["content"],
            "content_type": row["content_type"],
            "etag": row["etag"],
            "last_modified": row["last_modified"],
        }

    async def get_conditional_headers(self, url: str) -> dict[str, str]:
        """Return conditional GET headers (If-None-Match / If-Modified-Since) for *url*.

        Useful even when the entry is stale — the server may return 304 and
        confirm the cached content is still valid.
        """
        async with self._db.execute(
            "SELECT etag, last_modified FROM web_cache WHERE url = ?",
            (url,),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return {}

        headers: dict[str, str] = {}
        if row["etag"]:
            headers["If-None-Match"] = row["etag"]
        if row["last_modified"]:
            headers["If-Modified-Since"] = row["last_modified"]
        return headers

    async def set(
        self,
        url: str,
        content: str,
        content_type: str = "text/plain",
        ttl_s: int | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        """Store or update a cache entry for *url*."""
        from app.db.connection import write_transaction

        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT INTO web_cache
                    (url, content, content_type, fetched_at, ttl_s, etag, last_modified)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    content       = excluded.content,
                    content_type  = excluded.content_type,
                    fetched_at    = excluded.fetched_at,
                    ttl_s         = excluded.ttl_s,
                    etag          = excluded.etag,
                    last_modified = excluded.last_modified
                """,
                (
                    url,
                    content,
                    content_type,
                    self._now_iso(),
                    ttl_s if ttl_s is not None else self._default_ttl_s,
                    etag,
                    last_modified,
                ),
            )

    async def purge_expired(self) -> int:
        """Delete all stale entries.  Returns the number of rows deleted."""
        from app.db.connection import write_transaction

        # SQLite doesn't support datetime arithmetic natively, so we load and filter.
        async with self._db.execute(
            "SELECT url, fetched_at, ttl_s FROM web_cache"
        ) as cursor:
            rows = await cursor.fetchall()

        now = datetime.now(tz=timezone.utc)
        stale_urls: list[str] = []
        for row in rows:
            try:
                fetched_at = datetime.fromisoformat(row["fetched_at"])
                if fetched_at.tzinfo is None:
                    fetched_at = fetched_at.replace(tzinfo=timezone.utc)
                ttl = row["ttl_s"] or self._default_ttl_s
                if (now - fetched_at).total_seconds() > ttl:
                    stale_urls.append(row["url"])
            except Exception:
                stale_urls.append(row["url"])  # remove unparseable entries

        if stale_urls:
            async with write_transaction(self._db):
                placeholders = ",".join("?" * len(stale_urls))
                await self._db.execute(
                    f"DELETE FROM web_cache WHERE url IN ({placeholders})",
                    stale_urls,
                )
            logger.info("web_cache: purged %d expired entries", len(stale_urls))

        return len(stale_urls)


# ── Singleton ─────────────────────────────────────────────────────────────────

_web_cache: WebCache | None = None


def get_web_cache() -> WebCache:
    """Return the application-lifetime WebCache.

    Raises ``RuntimeError`` if ``init_web_cache()`` has not been called.
    """
    if _web_cache is None:
        raise RuntimeError("WebCache not initialised. Call init_web_cache() at startup.")
    return _web_cache


def init_web_cache(db: aiosqlite.Connection, default_ttl_s: int = DEFAULT_TTL_S) -> WebCache:
    """Initialise the global ``WebCache`` singleton.

    Called once in the FastAPI lifespan startup handler after the DB connection
    is established.
    """
    global _web_cache  # noqa: PLW0603
    _web_cache = WebCache(db, default_ttl_s=default_ttl_s)
    logger.info("WebCache initialised (TTL=%ds)", default_ttl_s)
    return _web_cache
