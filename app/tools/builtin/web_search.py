"""Sprint 06 — Web search built-in tool (§17.1).
Sprint 13 — Additional providers: Brave, Tavily, Google, Bing, SearXNG (§17.3).

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

    # Provider API keys (Sprint 13)
    brave_api_key: str = ""
    tavily_api_key: str = ""
    google_api_key: str = ""
    google_cx: str = ""  # Google Custom Search engine ID
    bing_api_key: str = ""
    searxng_url: str = ""  # SearXNG base URL e.g. "http://localhost:8080"


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


# ── Brave Search provider (Sprint 13) ────────────────────────────────────────


class BraveProvider(SearchProvider):
    """Brave Search API (https://api.search.brave.com).

    Requires ``brave_api_key`` in :class:`SearchConfig`.
    """

    def search(
        self,
        query: str,
        max_results: int,
        safe_search: str,
    ) -> list[dict[str, Any]]:
        import httpx  # type: ignore[import-untyped]

        cfg = get_search_config()
        if not cfg.brave_api_key:
            raise RuntimeError("Brave Search requires brave_api_key in SearchConfig.")

        safe_map = {"on": "strict", "moderate": "moderate", "off": "off"}
        params = {
            "q": query,
            "count": min(max_results, 20),
            "safesearch": safe_map.get(safe_search, "moderate"),
        }
        resp = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params=params,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": cfg.brave_api_key,
            },
            timeout=cfg.timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        results: list[dict[str, Any]] = []
        for r in data.get("web", {}).get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("description", ""),
                "source": "brave",
            })
        return results


# ── Tavily provider (Sprint 13) ───────────────────────────────────────────────


class TavilyProvider(SearchProvider):
    """Tavily Search API (https://tavily.com).

    Requires ``tavily_api_key`` in :class:`SearchConfig`.
    """

    def search(
        self,
        query: str,
        max_results: int,
        safe_search: str,
    ) -> list[dict[str, Any]]:
        import httpx  # type: ignore[import-untyped]

        cfg = get_search_config()
        if not cfg.tavily_api_key:
            raise RuntimeError("Tavily Search requires tavily_api_key in SearchConfig.")

        payload = {
            "api_key": cfg.tavily_api_key,
            "query": query,
            "max_results": min(max_results, 20),
            "include_raw_content": False,
        }
        resp = httpx.post(
            "https://api.tavily.com/search",
            json=payload,
            timeout=cfg.timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        results: list[dict[str, Any]] = []
        for r in data.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
                "source": "tavily",
            })
        return results


# ── Google Custom Search provider (Sprint 13) ─────────────────────────────────


class GoogleProvider(SearchProvider):
    """Google Custom Search JSON API.

    Requires ``google_api_key`` and ``google_cx`` in :class:`SearchConfig`.
    """

    def search(
        self,
        query: str,
        max_results: int,
        safe_search: str,
    ) -> list[dict[str, Any]]:
        import httpx  # type: ignore[import-untyped]

        cfg = get_search_config()
        if not cfg.google_api_key or not cfg.google_cx:
            raise RuntimeError("Google Search requires google_api_key and google_cx in SearchConfig.")

        safe_map = {"on": "active", "moderate": "active", "off": "off"}
        params = {
            "key": cfg.google_api_key,
            "cx": cfg.google_cx,
            "q": query,
            "num": min(max_results, 10),  # Google caps at 10
            "safe": safe_map.get(safe_search, "active"),
        }
        resp = httpx.get(
            "https://www.googleapis.com/customsearch/v1",
            params=params,
            timeout=cfg.timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        results: list[dict[str, Any]] = []
        for r in data.get("items", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("link", ""),
                "snippet": r.get("snippet", ""),
                "source": "google",
            })
        return results


# ── Bing Search provider (Sprint 13) ─────────────────────────────────────────


class BingProvider(SearchProvider):
    """Bing Web Search API v7.

    Requires ``bing_api_key`` in :class:`SearchConfig`.
    """

    def search(
        self,
        query: str,
        max_results: int,
        safe_search: str,
    ) -> list[dict[str, Any]]:
        import httpx  # type: ignore[import-untyped]

        cfg = get_search_config()
        if not cfg.bing_api_key:
            raise RuntimeError("Bing Search requires bing_api_key in SearchConfig.")

        safe_map = {"on": "Strict", "moderate": "Moderate", "off": "Off"}
        params = {
            "q": query,
            "count": min(max_results, 50),
            "safeSearch": safe_map.get(safe_search, "Moderate"),
        }
        resp = httpx.get(
            "https://api.bing.microsoft.com/v7.0/search",
            params=params,
            headers={"Ocp-Apim-Subscription-Key": cfg.bing_api_key},
            timeout=cfg.timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        results: list[dict[str, Any]] = []
        for r in data.get("webPages", {}).get("value", []):
            results.append({
                "title": r.get("name", ""),
                "url": r.get("url", ""),
                "snippet": r.get("snippet", ""),
                "source": "bing",
            })
        return results


# ── SearXNG provider (Sprint 13) ──────────────────────────────────────────────


class SearXNGProvider(SearchProvider):
    """SearXNG self-hosted meta-search engine.

    Requires ``searxng_url`` in :class:`SearchConfig`, e.g.
    ``"http://localhost:8080"``.  No API key required.
    """

    def search(
        self,
        query: str,
        max_results: int,
        safe_search: str,
    ) -> list[dict[str, Any]]:
        import httpx  # type: ignore[import-untyped]

        cfg = get_search_config()
        if not cfg.searxng_url:
            raise RuntimeError("SearXNG requires searxng_url in SearchConfig.")

        safe_int = {"on": 2, "moderate": 1, "off": 0}
        params = {
            "q": query,
            "format": "json",
            "pageno": 1,
            "safesearch": safe_int.get(safe_search, 1),
        }
        resp = httpx.get(
            cfg.searxng_url.rstrip("/") + "/search",
            params=params,
            timeout=cfg.timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        results: list[dict[str, Any]] = []
        for r in data.get("results", [])[:max_results]:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
                "source": "searxng",
            })
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
        _search_registry.register("brave", BraveProvider())
        _search_registry.register("tavily", TavilyProvider())
        _search_registry.register("google", GoogleProvider())
        _search_registry.register("bing", BingProvider())
        _search_registry.register("searxng", SearXNGProvider())
    return _search_registry


# ── Tool: web_search ──────────────────────────────────────────────────────────


@tool(
    description=(
        "Search the web for information about a topic. "
        "Returns a list of results with title, URL, and a short snippet. "
        "Use for finding current information, documentation, news, or any web content. "
        "Available providers: duckduckgo (default), brave, tavily, google, bing, searxng."
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
            "provider": {
                "type": "string",
                "description": (
                    "Search provider override. One of: duckduckgo, brave, tavily, "
                    "google, bing, searxng. Defaults to the configured default_provider."
                ),
            },
        },
        "required": ["query"],
    },
)
def web_search(
    query: str,
    max_results: int | None = None,
    search_type: str = "general",
    provider: str | None = None,
) -> list[dict[str, Any]]:
    """Search the web and return ranked result snippets."""
    cfg = get_search_config()
    n = max_results if max_results is not None else cfg.max_results
    provider_name = provider or cfg.default_provider
    prov = get_search_registry().get(provider_name)

    logger.info("web_search: query=%r provider=%r max=%d", query, provider_name, n)
    results = prov.search(query=query, max_results=n, safe_search=cfg.safe_search)
    logger.info("web_search: returned %d results", len(results))
    return results
