"""Sprint 06 — Web fetch built-in tool (§17.2).

Provides:
- ``web_fetch`` — fetch a URL and return extracted text (read_only)

Extraction modes
----------------
- ``article``   — extracts main article content using trafilatura (best for articles/blogs)
- ``markdown``  — converts full HTML to Markdown using html2text
- ``raw_html``  — returns the raw HTML without parsing

Caching
-------
Results are cached in the ``web_cache`` SQLite table (migration 0006) with a
configurable TTL.  Conditional GET (ETag / Last-Modified) is attempted for
stale entries.

The cache is optional: if ``WebCache`` has not been initialised (e.g. in unit
tests), fetches proceed without caching.

Content size
------------
Returned text is truncated to *max_chars* characters (default 50 000) to
avoid flooding the LLM context window.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.tools.registry import tool

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHARS: int = 50_000
DEFAULT_TIMEOUT_S: int = 30
DEFAULT_EXTRACT_MODE: str = "article"

# ── Content extraction helpers ─────────────────────────────────────────────────


def _extract_article(html: str, url: str) -> str:
    """Use trafilatura to extract the main article text."""
    try:
        import trafilatura

        text = trafilatura.extract(
            html,
            url=url,
            include_links=False,
            include_images=False,
            no_fallback=False,
        )
        return text or ""
    except Exception as exc:
        logger.warning("trafilatura extraction failed: %s", exc)
        return ""


def _extract_markdown(html: str) -> str:
    """Convert HTML to Markdown using html2text."""
    try:
        import html2text

        converter = html2text.HTML2Text()
        converter.ignore_links = False
        converter.ignore_images = True
        converter.body_width = 0  # no wrapping
        return converter.handle(html)
    except Exception as exc:
        logger.warning("html2text conversion failed: %s", exc)
        return html


def _extract_content(html: str, url: str, mode: str) -> str:
    """Dispatch to the appropriate extraction function."""
    if mode == "article":
        text = _extract_article(html, url)
        if not text:
            # Fall back to markdown if trafilatura returns nothing
            logger.debug("web_fetch: trafilatura returned empty, falling back to markdown")
            text = _extract_markdown(html)
        return text
    if mode == "markdown":
        return _extract_markdown(html)
    # raw_html or unrecognised
    return html


# ── Async fetch ────────────────────────────────────────────────────────────────


async def _fetch_url(
    url: str,
    conditional_headers: dict[str, str] | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> tuple[int, str, dict[str, str]]:
    """Fetch *url* and return ``(status_code, body_text, response_headers)``."""
    headers: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; Tequila-Agent/1.0; "
            "+https://github.com/tequila-project/tequila)"
        ),
    }
    if conditional_headers:
        headers.update(conditional_headers)

    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout_s) as client:
        response = await client.get(url, headers=headers)

    resp_headers = dict(response.headers)
    return response.status_code, response.text, resp_headers


# ── Tool: web_fetch ────────────────────────────────────────────────────────────


@tool(
    description=(
        "Fetch the content of a web page at a given URL. "
        "Returns extracted text content ready for analysis. "
        "extract_mode controls how content is extracted: "
        "'article' extracts the main article text (best for blogs/news), "
        "'markdown' converts the full page to Markdown, "
        "'raw_html' returns raw HTML. "
        "Results are cached for 1 hour to avoid repeat network requests."
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch.",
            },
            "extract_mode": {
                "type": "string",
                "description": "Content extraction mode: 'article', 'markdown', or 'raw_html'. Default 'article'.",
            },
            "max_chars": {
                "type": "integer",
                "description": f"Maximum characters to return. Default {DEFAULT_MAX_CHARS}.",
            },
            "bypass_cache": {
                "type": "boolean",
                "description": "If true, ignore cached content and always re-fetch. Default false.",
            },
        },
        "required": ["url"],
    },
)
async def web_fetch(
    url: str,
    extract_mode: str = DEFAULT_EXTRACT_MODE,
    max_chars: int = DEFAULT_MAX_CHARS,
    bypass_cache: bool = False,
) -> str:
    """Fetch *url* and return extracted/converted text content."""
    logger.info("web_fetch: url=%r mode=%r bypass_cache=%s", url, extract_mode, bypass_cache)

    # ── Try cache first ────────────────────────────────────────────────────────
    cache = _get_cache_optional()

    if cache is not None and not bypass_cache:
        try:
            cached = await cache.get(url)
            if cached is not None:
                logger.debug("web_fetch: cache hit for %r", url)
                content = cached["content"]
                return _truncate(content, max_chars)
        except Exception as exc:
            logger.debug("web_fetch: cache read failed (%s), proceeding without cache", exc)
            cache = None

    # ── Conditional GET headers ────────────────────────────────────────────────
    cond_headers: dict[str, str] = {}
    if cache is not None and not bypass_cache:
        try:
            cond_headers = await cache.get_conditional_headers(url)
        except Exception as exc:
            logger.debug("web_fetch: cache headers failed (%s)", exc)
            cond_headers = {}

    # ── Network fetch ──────────────────────────────────────────────────────────
    try:
        status, raw_body, resp_headers = await _fetch_url(url, cond_headers)
    except httpx.TimeoutException:
        return f"[Error] Request timed out after {DEFAULT_TIMEOUT_S}s: {url}"
    except httpx.RequestError as exc:
        return f"[Error] Network error fetching {url}: {exc}"

    if status == 304 and cache is not None:
        # Server says content unchanged — refresh cache TTL and return cached
        cached = await cache.get(url)
        if cached is not None:
            logger.debug("web_fetch: 304 Not Modified, returning cached content for %r", url)
            return _truncate(cached["content"], max_chars)

    if status >= 400:
        return f"[Error] HTTP {status} from {url}"

    # ── Extract content ─────────────────────────────────────────────────────────
    content = _extract_content(raw_body, url, extract_mode)

    if not content.strip():
        # Last resort: return raw text
        logger.warning("web_fetch: extraction returned empty for %r, returning raw text", url)
        content = raw_body

    # ── Store in cache ─────────────────────────────────────────────────────────
    if cache is not None:
        try:
            await cache.set(
                url=url,
                content=content,
                content_type=resp_headers.get("content-type", "text/html"),
                etag=resp_headers.get("etag"),
                last_modified=resp_headers.get("last-modified"),
            )
        except Exception as exc:
            logger.warning("web_fetch: failed to cache %r: %s", url, exc)

    return _truncate(content, max_chars)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _truncate(text: str, max_chars: int) -> str:
    if len(text) > max_chars:
        return text[:max_chars] + f"\n\n[Content truncated — exceeded {max_chars} characters]"
    return text


def _get_cache_optional():
    """Return the WebCache singleton if available, else None."""
    try:
        from app.db.web_cache import get_web_cache
        return get_web_cache()
    except RuntimeError:
        return None
    except Exception:
        return None
