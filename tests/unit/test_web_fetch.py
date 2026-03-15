"""Unit tests for app/tools/builtin/web_fetch.py and app/db/web_cache.py"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from app.tools.builtin.web_fetch import (
    _extract_article,
    _extract_markdown,
    _extract_content,
    _truncate,
    web_fetch,
)


# ── Extraction helpers ─────────────────────────────────────────────────────────


def test_truncate_short_string() -> None:
    assert _truncate("hello", 100) == "hello"


def test_truncate_long_string() -> None:
    long = "x" * 1000
    result = _truncate(long, 100)
    assert len(result) > 100  # includes the notice
    assert "truncated" in result
    assert result.startswith("x" * 100)


def test_extract_markdown_returns_string() -> None:
    html = "<h1>Title</h1><p>Paragraph text.</p>"
    result = _extract_markdown(html)
    assert isinstance(result, str)
    assert "Title" in result or "title" in result.lower() or result.strip() != ""


def test_extract_content_raw_html() -> None:
    html = "<b>bold</b>"
    result = _extract_content(html, "https://example.com", "raw_html")
    assert result == html


def test_extract_content_markdown_mode() -> None:
    html = "<p>Hello world</p>"
    result = _extract_content(html, "https://example.com", "markdown")
    assert isinstance(result, str)
    assert "Hello" in result


# ── web_fetch (mocked network) ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_web_fetch_returns_content() -> None:
    html = "<html><body><article><p>Test article content here.</p></article></body></html>"

    with patch("app.tools.builtin.web_fetch._fetch_url") as mock_fetch:
        mock_fetch.return_value = (200, html, {"content-type": "text/html"})
        result = await web_fetch("https://example.com", extract_mode="markdown")

    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_web_fetch_http_error() -> None:
    with patch("app.tools.builtin.web_fetch._fetch_url") as mock_fetch:
        mock_fetch.return_value = (404, "", {})
        result = await web_fetch("https://example.com/missing")

    assert "404" in result
    assert "[Error]" in result


@pytest.mark.asyncio
async def test_web_fetch_network_error() -> None:
    import httpx
    with patch("app.tools.builtin.web_fetch._fetch_url") as mock_fetch:
        mock_fetch.side_effect = httpx.RequestError("connection refused")
        result = await web_fetch("https://unreachable.example.com")

    assert "[Error]" in result


@pytest.mark.asyncio
async def test_web_fetch_timeout() -> None:
    import httpx
    with patch("app.tools.builtin.web_fetch._fetch_url") as mock_fetch:
        mock_fetch.side_effect = httpx.TimeoutException("timed out")
        result = await web_fetch("https://slow.example.com")

    assert "timed out" in result.lower()


@pytest.mark.asyncio
async def test_web_fetch_truncates_large_content() -> None:
    large_html = "<p>" + "word " * 20_000 + "</p>"

    with patch("app.tools.builtin.web_fetch._fetch_url") as mock_fetch:
        mock_fetch.return_value = (200, large_html, {"content-type": "text/html"})
        result = await web_fetch("https://example.com", extract_mode="raw_html", max_chars=100)

    assert "truncated" in result


# ── WebCache ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_web_cache_set_and_get(migrated_db) -> None:
    """WebCache stores and retrieves a fresh entry."""
    from app.db.web_cache import WebCache

    cache = WebCache(migrated_db, default_ttl_s=3600)
    await cache.set("https://example.com", "some content", content_type="text/html")
    result = await cache.get("https://example.com")

    assert result is not None
    assert result["content"] == "some content"
    assert result["content_type"] == "text/html"


@pytest.mark.asyncio
async def test_web_cache_get_stale_returns_none(migrated_db) -> None:
    """Stale cache entries return None."""
    from app.db.web_cache import WebCache
    from app.db.connection import write_transaction

    cache = WebCache(migrated_db, default_ttl_s=10)

    # Insert with a past timestamp directly
    past = (datetime.now(tz=timezone.utc) - timedelta(hours=2)).isoformat()
    async with write_transaction(migrated_db):
        await migrated_db.execute(
            "INSERT INTO web_cache (url, content, content_type, fetched_at, ttl_s) "
            "VALUES (?, ?, ?, ?, ?)",
            ("https://stale.com", "old content", "text/html", past, 10),
        )

    result = await cache.get("https://stale.com")
    assert result is None


@pytest.mark.asyncio
async def test_web_cache_get_miss_returns_none(migrated_db) -> None:
    from app.db.web_cache import WebCache

    cache = WebCache(migrated_db)
    result = await cache.get("https://notcached.example.com")
    assert result is None


@pytest.mark.asyncio
async def test_web_cache_conditional_headers(migrated_db) -> None:
    from app.db.web_cache import WebCache

    cache = WebCache(migrated_db)
    await cache.set(
        "https://example.com",
        "content",
        etag='"abc123"',
        last_modified="Wed, 01 Jan 2025 00:00:00 GMT",
    )
    headers = await cache.get_conditional_headers("https://example.com")
    assert headers.get("If-None-Match") == '"abc123"'
    assert "If-Modified-Since" in headers


@pytest.mark.asyncio
async def test_web_cache_purge_expired(migrated_db) -> None:
    from app.db.web_cache import WebCache
    from app.db.connection import write_transaction

    cache = WebCache(migrated_db, default_ttl_s=60)

    past = (datetime.now(tz=timezone.utc) - timedelta(hours=5)).isoformat()
    async with write_transaction(migrated_db):
        await migrated_db.execute(
            "INSERT INTO web_cache (url, content, content_type, fetched_at, ttl_s) "
            "VALUES (?, ?, ?, ?, ?)",
            ("https://expired1.com", "x", "text/html", past, 60),
        )
        await migrated_db.execute(
            "INSERT INTO web_cache (url, content, content_type, fetched_at, ttl_s) "
            "VALUES (?, ?, ?, ?, ?)",
            ("https://expired2.com", "y", "text/html", past, 60),
        )

    # Fresh entry
    await cache.set("https://fresh.com", "fresh content", ttl_s=9999)

    purged = await cache.purge_expired()
    assert purged == 2

    # Fresh entry should still be there
    result = await cache.get("https://fresh.com")
    assert result is not None


@pytest.mark.asyncio
async def test_web_cache_overwrite(migrated_db) -> None:
    """Setting the same URL twice should update the entry, not duplicate."""
    from app.db.web_cache import WebCache

    cache = WebCache(migrated_db)
    await cache.set("https://example.com", "v1")
    await cache.set("https://example.com", "v2")

    result = await cache.get("https://example.com")
    assert result is not None
    assert result["content"] == "v2"


def test_web_fetch_tools_registered() -> None:
    from app.tools.registry import get_tool_registry
    from app.tools.builtin import register_all_builtin_tools
    register_all_builtin_tools()
    reg = get_tool_registry()
    entry = reg.get("web_fetch")
    assert entry is not None
    td, _ = entry
    assert td.safety == "read_only"
