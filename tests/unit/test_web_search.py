"""Unit tests for app/tools/builtin/web_search.py"""
import pytest

from app.tools.builtin.web_search import (
    DuckDuckGoProvider,
    SearchConfig,
    SearchProvider,
    SearchProviderRegistry,
    get_search_config,
    get_search_registry,
    set_search_config,
    web_search,
)


# ── SearchConfig ──────────────────────────────────────────────────────────────


def test_search_config_defaults() -> None:
    cfg = SearchConfig()
    assert cfg.default_provider == "duckduckgo"
    assert cfg.max_results == 10
    assert cfg.safe_search == "moderate"


def test_set_search_config() -> None:
    original = get_search_config()
    custom = SearchConfig(default_provider="duckduckgo", max_results=5)
    set_search_config(custom)
    assert get_search_config().max_results == 5
    # Restore
    set_search_config(original)


# ── SearchProviderRegistry ────────────────────────────────────────────────────


def test_registry_register_and_get() -> None:
    reg = SearchProviderRegistry()

    class DummyProvider(SearchProvider):
        def search(self, query, max_results, safe_search):
            return [{"title": "t", "url": "u", "snippet": "s", "source": "dummy"}]

    reg.register("dummy", DummyProvider())
    provider = reg.get("dummy")
    assert isinstance(provider, DummyProvider)


def test_registry_unknown_provider_raises() -> None:
    reg = SearchProviderRegistry()
    with pytest.raises(KeyError, match="Unknown search provider"):
        reg.get("nosuchprovider")


def test_registry_names() -> None:
    reg = SearchProviderRegistry()

    class P(SearchProvider):
        def search(self, q, m, s):
            return []

    reg.register("alpha", P())
    reg.register("beta", P())
    assert set(reg.names()) == {"alpha", "beta"}


# ── DuckDuckGoProvider (mocked) ───────────────────────────────────────────────


def test_duckduckgo_provider_success() -> None:
    """DuckDuckGoProvider correctly maps DDGS results to our schema."""
    raw = [
        {"title": "Page A", "href": "https://a.com", "body": "About A"},
    ]

    import duckduckgo_search as dsm
    orig = dsm.DDGS

    class FakeDDGS:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def text(self, *a, **kw): return iter(raw)

    try:
        dsm.DDGS = FakeDDGS  # type: ignore[assignment]
        provider = DuckDuckGoProvider()
        results = provider.search("hello", max_results=5, safe_search="moderate")
        assert len(results) == 1
        assert results[0]["title"] == "Page A"
        assert results[0]["url"] == "https://a.com"
        assert results[0]["snippet"] == "About A"
        assert results[0]["source"] == "duckduckgo"
    finally:
        dsm.DDGS = orig


def test_duckduckgo_provider_empty_results() -> None:
    """Provider returns empty list when DDGS returns nothing."""
    import duckduckgo_search as dsm
    orig = dsm.DDGS

    class EmptyDDGS:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def text(self, *a, **kw): return iter([])

    try:
        dsm.DDGS = EmptyDDGS  # type: ignore[assignment]
        provider = DuckDuckGoProvider()
        results = provider.search("no results", max_results=5, safe_search="off")
        assert results == []
    finally:
        dsm.DDGS = orig


# ── web_search tool ───────────────────────────────────────────────────────────


def test_web_search_calls_provider() -> None:
    """web_search delegates to the registered provider."""
    fake_results = [
        {"title": "T", "url": "https://x.com", "snippet": "S", "source": "fake"}
    ]

    class FakeProvider(SearchProvider):
        def search(self, query, max_results, safe_search):
            return fake_results

    # Register fake provider and configure it as default
    registry = get_search_registry()
    registry.register("fake", FakeProvider())
    original_cfg = get_search_config()
    set_search_config(SearchConfig(default_provider="fake", max_results=5))

    try:
        results = web_search("anything")
        assert results == fake_results
    finally:
        set_search_config(original_cfg)


def test_web_search_respects_max_results() -> None:
    call_kwargs = {}

    class RecordingProvider(SearchProvider):
        def search(self, query, max_results, safe_search):
            call_kwargs["max_results"] = max_results
            return []

    registry = get_search_registry()
    registry.register("recording", RecordingProvider())
    original_cfg = get_search_config()
    set_search_config(SearchConfig(default_provider="recording"))

    try:
        web_search("query", max_results=7)
        assert call_kwargs["max_results"] == 7
    finally:
        set_search_config(original_cfg)


def test_web_search_tool_registered() -> None:
    from app.tools.registry import get_tool_registry
    from app.tools.builtin import register_all_builtin_tools
    register_all_builtin_tools()
    reg = get_tool_registry()
    entry = reg.get("web_search")
    assert entry is not None
    td, _ = entry
    assert td.safety == "read_only"
