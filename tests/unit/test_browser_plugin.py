"""Unit tests for Sprint 13 D2 — BrowserPlugin (mocked Playwright)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── BrowserPlugin metadata ────────────────────────────────────────────────────


def test_browser_plugin_metadata():
    from app.plugins.builtin.browser.plugin import BrowserPlugin

    p = BrowserPlugin()
    assert p.plugin_id == "browser"
    assert p.plugin_type in ("connector", "builtin")


@pytest.mark.asyncio
async def test_browser_plugin_get_tools_returns_list():
    from app.plugins.builtin.browser.plugin import BrowserPlugin

    p = BrowserPlugin()
    tools = await p.get_tools()
    assert isinstance(tools, list)
    assert len(tools) >= 10  # At least 10 operation tools
    names = {t["name"] for t in tools}
    assert "browser_launch" in names
    assert "browser_navigate" in names
    assert "browser_screenshot" in names
    assert "browser_close" in names


# ── Individual tools with mocked Playwright ───────────────────────────────────


@pytest.mark.asyncio
async def test_browser_launch_creates_session():
    """browser_launch() must populate the _sessions dict."""
    playwright = pytest.importorskip("playwright", reason="playwright not installed")
    from app.plugins.builtin.browser import tools as bt

    # Clear sessions before test
    bt._sessions.clear()

    mock_page = AsyncMock()
    mock_page.set_default_timeout = MagicMock()

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    mock_pw = MagicMock()
    mock_pw.chromium = MagicMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

    # browser_launch calls: pw = await async_playwright().start()
    mock_ap_instance = MagicMock()
    mock_ap_instance.start = AsyncMock(return_value=mock_pw)
    mock_async_playwright = MagicMock(return_value=mock_ap_instance)

    with patch("playwright.async_api.async_playwright", mock_async_playwright):
        result = await bt.TOOL_FN_MAP["browser_launch"](
            session_id="test-session",
            headless=True,
        )

    assert "test-session" in bt._sessions
    assert result["status"] == "launched"
    bt._sessions.clear()


@pytest.mark.asyncio
async def test_browser_navigate():
    """browser_navigate() should call page.goto() with the given URL."""
    from app.plugins.builtin.browser import tools as bt

    bt._sessions.clear()

    mock_response = MagicMock()
    mock_response.status = 200

    mock_page = AsyncMock()
    mock_page.goto = AsyncMock(return_value=mock_response)
    mock_page.title = AsyncMock(return_value="Test Page")
    mock_page.url = "https://example.com"

    session_id = "nav-session"
    bt._sessions[session_id] = {
        "playwright": None,
        "browser": None,
        "context": None,
        "pages": {"0": mock_page},
        "active_page": mock_page,  # active_page is the Page object directly
    }

    result = await bt.TOOL_FN_MAP["browser_navigate"](
        "https://example.com",
        session_id=session_id,
        wait_until="load",
    )
    mock_page.goto.assert_called_once_with("https://example.com", wait_until="load")
    assert result["status_code"] == 200
    bt._sessions.clear()


@pytest.mark.asyncio
async def test_browser_get_text():
    """browser_get_text() should return inner_text of the page body."""
    from app.plugins.builtin.browser import tools as bt

    bt._sessions.clear()

    mock_page = AsyncMock()
    mock_page.inner_text = AsyncMock(return_value="Page content goes here")

    session_id = "text-session"
    bt._sessions[session_id] = {
        "playwright": None,
        "browser": None,
        "context": None,
        "pages": {"0": mock_page},
        "active_page": mock_page,
    }

    result = await bt.TOOL_FN_MAP["browser_get_text"](session_id=session_id)
    assert isinstance(result, dict)
    assert "Page content goes here" == result["text"]
    bt._sessions.clear()


@pytest.mark.asyncio
async def test_browser_evaluate():
    """browser_evaluate() should return JavaScript evaluation result."""
    from app.plugins.builtin.browser import tools as bt

    bt._sessions.clear()

    mock_page = AsyncMock()
    mock_page.evaluate = AsyncMock(return_value=42)

    session_id = "eval-session"
    bt._sessions[session_id] = {
        "playwright": None,
        "browser": None,
        "context": None,
        "pages": {"0": mock_page},
        "active_page": mock_page,
    }

    result = await bt.TOOL_FN_MAP["browser_evaluate"](
        "1 + 1",  # script is the first positional arg
        session_id=session_id,
    )
    assert isinstance(result, dict)
    assert result["result"] == 42
    bt._sessions.clear()


@pytest.mark.asyncio
async def test_browser_tool_missing_session_raises():
    """Operations on a non-existent session_id must raise RuntimeError."""
    from app.plugins.builtin.browser import tools as bt

    bt._sessions.clear()
    with pytest.raises(RuntimeError, match="not launched"):
        await bt.TOOL_FN_MAP["browser_navigate"](
            "https://example.com",
            session_id="nonexistent",
        )
