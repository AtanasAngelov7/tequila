"""Unit tests for Sprint 13 D3 — new web search providers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.tools.builtin.web_search import (
    BingProvider,
    BraveProvider,
    GoogleProvider,
    SearXNGProvider,
    TavilyProvider,
    SearchConfig,
    set_search_config,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mock_httpx_response(json_data: dict):
    """Return a mock synchronous httpx response with given JSON body."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = json_data
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


# ── BraveProvider ─────────────────────────────────────────────────────────────


def test_brave_provider_returns_results():
    set_search_config(SearchConfig(brave_api_key="test-brave-key"))
    brave_data = {
        "web": {
            "results": [
                {"title": "Brave Result 1", "url": "https://example.com/1", "description": "Desc 1"},
                {"title": "Brave Result 2", "url": "https://example.com/2", "description": "Desc 2"},
            ]
        }
    }
    with patch("httpx.get", return_value=_mock_httpx_response(brave_data)):
        provider = BraveProvider()
        results = provider.search(query="test brave", max_results=2, safe_search="moderate")

    assert len(results) == 2
    assert results[0]["title"] == "Brave Result 1"
    assert results[0]["url"] == "https://example.com/1"


def test_brave_provider_empty_results():
    set_search_config(SearchConfig(brave_api_key="test-brave-key"))
    with patch("httpx.get", return_value=_mock_httpx_response({"web": {"results": []}})):
        provider = BraveProvider()
        results = provider.search(query="nothing", max_results=5, safe_search="off")

    assert results == []


# ── TavilyProvider ────────────────────────────────────────────────────────────


def test_tavily_provider_returns_results():
    set_search_config(SearchConfig(tavily_api_key="tvly-test"))
    tavily_data = {
        "results": [
            {"title": "Tavily 1", "url": "https://tavily.com/1", "content": "Content 1"},
        ]
    }
    with patch("httpx.post", return_value=_mock_httpx_response(tavily_data)):
        provider = TavilyProvider()
        results = provider.search(query="test tavily", max_results=1, safe_search="moderate")

    assert len(results) == 1
    assert results[0]["title"] == "Tavily 1"


# ── GoogleProvider ────────────────────────────────────────────────────────────


def test_google_provider_returns_results():
    set_search_config(SearchConfig(google_api_key="AIza-test", google_cx="abc123"))
    google_data = {
        "items": [
            {"title": "Google 1", "link": "https://google.com/1", "snippet": "Snippet 1"},
            {"title": "Google 2", "link": "https://google.com/2", "snippet": "Snippet 2"},
        ]
    }
    with patch("httpx.get", return_value=_mock_httpx_response(google_data)):
        provider = GoogleProvider()
        results = provider.search(query="google test", max_results=2, safe_search="moderate")

    assert len(results) == 2
    assert results[0]["title"] == "Google 1"


# ── BingProvider ──────────────────────────────────────────────────────────────


def test_bing_provider_returns_results():
    set_search_config(SearchConfig(bing_api_key="bing-test"))
    bing_data = {
        "webPages": {
            "value": [
                {"name": "Bing 1", "url": "https://bing.com/1", "snippet": "Bing Snip 1"},
            ]
        }
    }
    with patch("httpx.get", return_value=_mock_httpx_response(bing_data)):
        provider = BingProvider()
        results = provider.search(query="bing test", max_results=1, safe_search="moderate")

    assert len(results) == 1
    assert results[0]["title"] == "Bing 1"
    assert results[0]["url"] == "https://bing.com/1"


# ── SearchConfig provider override ────────────────────────────────────────────


def test_get_search_registry_contains_all_providers():
    from app.tools.builtin.web_search import get_search_registry

    registry = get_search_registry()
    names = registry.names()
    for expected in ("duckduckgo", "brave", "tavily", "google", "bing", "searxng"):
        assert expected in names, f"Provider {expected!r} missing from registry"
