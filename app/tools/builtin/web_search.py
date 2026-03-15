"""Sprint 06 — Web search built-in tool (§17.1).

Provides:
- ``web_search`` — search the web, returning ranked result snippets (read_only)

Architecture
------------
Search providers are registered in ``SearchProviderRegistry``.  The default
provider is DuckDuckGo via the ``duckduckgo-search`` library.

``SearchConfig`` (module-level singleton) controls defaults; it can be replaced
in tests via ``set_search_config()``.

Adding a new provider
---------------------
1. Subclass ``SearchProvider`` and implement ``search()``.
2. Register: ``get_search_registry().register("my_provider", MyProvider())``.
3. Set ``SearchConfig.default_provider = "my_provider"`` to make it the default.

Rate limiting
-------------
DuckDuckGo imposes rate limits.  Simple exponential back-off is applied on
``RatelimitError``; the tool returns a partial result rather than failing hard.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from app.tools.registry import tool

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────


class SearchConfig(BaseModel):
    """Global configuration for the web search tool."""

    default_provider: str = "duckduckgo"
    max_results: int = 10
    safe_search: str = "moderate"  # "on" | "moderate" | "off"
    timeout_s: int = 15


_search_config = SearchConfig()


def get_search_config() -> SearchConfig:
    return _search_config


def set_search_config(cfg: SearchConfig) -> None:
    """Replace the module-level config (useful in tests)."""
    global _search_config  # noqa: PLW0603
    _search_config = cfg


# ── Provider protocol ─────────────────────────────────────────────────────────


class SearchProvider(ABC):
    """Abstract base class for web search providers."""

    @abstractmethod
    def search(
        self,
        query: str,
        max_results: int,
        safe_search: str,
    ) -> list[dict[str, Any]]:
        """Return a list of result dicts: {title, url, snippet, source}."""


# ── DuckDuckGo provider ───────────────────────────────────────────────────────


class DuckDuckGoProvider(SearchProvider):
    """Web search via the ``duckduckgo-search`` library."""

    def search(
        self,
        query: str,
        max_results: int,
        safe_search: str,
    ) -> list[dict[str, Any]]:
        from duckduckgo_search import DDGS  # lazy import

        safesearch_map = {"on": "on", "moderate": "moderate", "off": "off"}
        safesearch = safesearch_map.get(safe_search, "moderate")

        results: list[dict[str, Any]] = []
        retries = 0
        max_retries = 3

        while retries <= max_retries:
            try:
                with DDGS() as ddgs:
                    for r in ddgs.text(query, max_results=max_results, safesearch=safesearch):
                        results.append({
                            "title": r.get("title", ""),
                            "url": r.get("href", ""),
                            "snippet": r.get("body", ""),
                            "source": "duckduckgo",
                        })
                break  # success
            except Exception as exc:
                err_name = type(exc).__name__
                if "Ratelimit" in err_name or "ratelimit" in str(exc).lower():
                    wait = 2 ** retries
                    logger.warning(
                        "DuckDuckGo rate limit hit, retrying in %ds (attempt %d/%d)",
                        wait, retries + 1, max_retries,
                    )
                    time.sleep(wait)
                    retries += 1
                    if retries > max_retries:
                        logger.error("DuckDuckGo: max retries exceeded, returning empty results")
                        break
                else:
                    logger.error("DuckDuckGo search failed: %s", exc, exc_info=True)
                    raise

        return results


# ── Provider registry ─────────────────────────────────────────────────────────


class SearchProviderRegistry:
    """Registry of named search providers."""

    def __init__(self) -> None:
        self._providers: dict[str, SearchProvider] = {}

    def register(self, name: str, provider: SearchProvider) -> None:
        self._providers[name] = provider

    def get(self, name: str) -> SearchProvider:
        if name not in self._providers:
            raise KeyError(f"Unknown search provider: {name!r}. Available: {list(self._providers)}")
        return self._providers[name]

    def names(self) -> list[str]:
        return list(self._providers)


_search_registry: SearchProviderRegistry | None = None


def get_search_registry() -> SearchProviderRegistry:
    """Return (creating if necessary) the global search provider registry."""
    global _search_registry  # noqa: PLW0603
    if _search_registry is None:
        _search_registry = SearchProviderRegistry()
        _search_registry.register("duckduckgo", DuckDuckGoProvider())
    return _search_registry


# ── Tool: web_search ──────────────────────────────────────────────────────────


@tool(
    description=(
        "Search the web for information about a topic. "
        "Returns a list of results with title, URL, and a short snippet. "
        "Use for finding current information, documentation, news, or any web content."
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query string.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return. Default 10.",
            },
            "search_type": {
                "type": "string",
                "description": "Search type hint: 'general', 'news', 'code'. Currently informational only.",
            },
        },
        "required": ["query"],
    },
)
def web_search(
    query: str,
    max_results: int | None = None,
    search_type: str = "general",
) -> list[dict[str, Any]]:
    """Search the web and return ranked result snippets."""
    cfg = get_search_config()
    n = max_results if max_results is not None else cfg.max_results
    provider = get_search_registry().get(cfg.default_provider)

    logger.info("web_search: query=%r provider=%r max=%d", query, cfg.default_provider, n)
    results = provider.search(query=query, max_results=n, safe_search=cfg.safe_search)
    logger.info("web_search: returned %d results", len(results))
    return results
