"""Browser automation tool definitions and implementations (Sprint 13, §8.6, D2).

All 25 browser tools using Playwright (async API).

Playwright is lazily imported — the plugin can be registered even if
``playwright`` is not installed; it will only fail on first use.

Dependencies (pip):
    playwright>=1.40           (+ ``playwright install chromium`` for browser binaries)

Session model:
    Tools share a per-session browser context stored in the module-level
    ``_sessions`` dict keyed by ``session_id``.  A default global session
    ``"__global__"`` is used when ``session_id`` is omitted.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session storage
# ---------------------------------------------------------------------------

# session_id → {"browser": Browser, "context": BrowserContext, "pages": {tab_id: Page}}
_sessions: dict[str, dict[str, Any]] = {}

_DEFAULT_SESSION = "__global__"
_DEFAULT_TIMEOUT = 30_000  # ms


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_or_create_session(session_id: str) -> dict[str, Any]:
    """Return existing session dict or create a new one."""
    from playwright.async_api import async_playwright  # type: ignore[import-untyped]
    if session_id not in _sessions:
        _sessions[session_id] = {
            "playwright": None,
            "browser": None,
            "context": None,
            "pages": {},
            "active_page": None,
        }
    return _sessions[session_id]


async def _active_page(session_id: str):  # noqa: ANN202
    """Return the currently active Page for a session; raises if not launched."""
    sess = _sessions.get(session_id)
    if not sess or not sess.get("active_page"):
        raise RuntimeError(
            f"Browser not launched for session {session_id!r}. "
            "Call browser_launch first."
        )
    return sess["active_page"]


# ---------------------------------------------------------------------------
# Tools — 25 browser automation functions
# ---------------------------------------------------------------------------

async def browser_launch(
    *,
    session_id: str = _DEFAULT_SESSION,
    headless: bool = True,
    viewport_width: int = 1280,
    viewport_height: int = 800,
    timeout: int = _DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Launch a Chromium browser instance for a session."""
    from playwright.async_api import async_playwright  # type: ignore[import-untyped]
    sess = await _get_or_create_session(session_id)
    if sess.get("browser"):
        return {"status": "already_launched", "session_id": session_id}
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=headless)
    context = await browser.new_context(
        viewport={"width": viewport_width, "height": viewport_height},
    )
    page = await context.new_page()
    page.set_default_timeout(timeout)
    sess.update({"playwright": pw, "browser": browser, "context": context,
                 "pages": {"0": page}, "active_page": page})
    return {"status": "launched", "session_id": session_id, "headless": headless}


async def browser_close(*, session_id: str = _DEFAULT_SESSION) -> dict[str, Any]:
    """Close the browser instance for a session and free its resources."""
    sess = _sessions.pop(session_id, None)
    if not sess:
        return {"status": "not_found", "session_id": session_id}
    try:
        if sess.get("browser"):
            await sess["browser"].close()
        if sess.get("playwright"):
            await sess["playwright"].stop()
    except Exception as exc:  # noqa: BLE001
        logger.warning("browser_close error: %s", exc)
    return {"status": "closed", "session_id": session_id}


async def browser_navigate(
    url: str,
    *,
    session_id: str = _DEFAULT_SESSION,
    wait_until: str = "load",
) -> dict[str, Any]:
    """Navigate to *url* in the active page."""
    page = await _active_page(session_id)
    response = await page.goto(url, wait_until=wait_until)
    status = response.status if response else None
    return {
        "url": page.url,
        "status_code": status,
        "title": await page.title(),
    }


async def browser_click(
    selector: str,
    *,
    session_id: str = _DEFAULT_SESSION,
    timeout: int | None = None,
) -> dict[str, Any]:
    """Click on an element matching *selector*."""
    page = await _active_page(session_id)
    kw: dict[str, Any] = {}
    if timeout is not None:
        kw["timeout"] = timeout
    await page.click(selector, **kw)
    return {"clicked": selector, "url": page.url}


async def browser_type(
    selector: str,
    text: str,
    *,
    session_id: str = _DEFAULT_SESSION,
    delay: int = 0,
) -> dict[str, Any]:
    """Type *text* into the element matching *selector*."""
    page = await _active_page(session_id)
    await page.type(selector, text, delay=delay)
    return {"typed_into": selector, "text_length": len(text)}


async def browser_screenshot(
    *,
    session_id: str = _DEFAULT_SESSION,
    full_page: bool = False,
    selector: str | None = None,
) -> dict[str, Any]:
    """Take a screenshot; return base64-encoded PNG."""
    page = await _active_page(session_id)
    if selector:
        element = await page.query_selector(selector)
        if element:
            img_bytes = await element.screenshot()
        else:
            raise ValueError(f"Selector {selector!r} not found.")
    else:
        img_bytes = await page.screenshot(full_page=full_page)
    b64 = base64.b64encode(img_bytes).decode()
    return {"format": "png", "base64": b64, "url": page.url, "full_page": full_page}


async def browser_evaluate(
    script: str,
    *,
    session_id: str = _DEFAULT_SESSION,
) -> dict[str, Any]:
    """Evaluate *script* in the page context and return the result."""
    page = await _active_page(session_id)
    result = await page.evaluate(script)
    return {"result": result}


async def browser_wait(
    *,
    session_id: str = _DEFAULT_SESSION,
    selector: str | None = None,
    state: str = "visible",
    milliseconds: int | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    """Wait for a selector to reach *state* or for *milliseconds* if no selector."""
    page = await _active_page(session_id)
    if milliseconds is not None:
        await page.wait_for_timeout(milliseconds)
        return {"waited_ms": milliseconds}
    if selector:
        kw: dict[str, Any] = {"state": state}
        if timeout is not None:
            kw["timeout"] = timeout
        await page.wait_for_selector(selector, **kw)
        return {"selector": selector, "state": state}
    raise ValueError("Provide either 'selector' or 'milliseconds'.")


async def browser_scroll(
    direction: str = "down",
    amount: int = 500,
    *,
    session_id: str = _DEFAULT_SESSION,
) -> dict[str, Any]:
    """Scroll the page. *direction*: 'up', 'down', 'left', 'right'."""
    page = await _active_page(session_id)
    dx = {"right": amount, "left": -amount}.get(direction, 0)
    dy = {"down": amount, "up": -amount}.get(direction, 0)
    await page.evaluate(f"window.scrollBy({dx}, {dy})")
    return {"scrolled": direction, "amount": amount}


async def browser_select(
    selector: str,
    value: str | list[str],
    *,
    session_id: str = _DEFAULT_SESSION,
) -> dict[str, Any]:
    """Select an option in a <select> element by value."""
    page = await _active_page(session_id)
    values = value if isinstance(value, list) else [value]
    selected = await page.select_option(selector, values)
    return {"selector": selector, "selected": selected}


async def browser_fill_form(
    form_data: dict[str, str],
    *,
    session_id: str = _DEFAULT_SESSION,
    submit_selector: str | None = None,
) -> dict[str, Any]:
    """Fill form fields. *form_data* is {selector → value}. Optionally click submit."""
    page = await _active_page(session_id)
    filled: list[str] = []
    for selector, value in form_data.items():
        await page.fill(selector, value)
        filled.append(selector)
    if submit_selector:
        await page.click(submit_selector)
    return {"filled": filled, "submitted": submit_selector is not None}


async def browser_get_text(
    selector: str | None = None,
    *,
    session_id: str = _DEFAULT_SESSION,
) -> dict[str, Any]:
    """Get inner text of *selector* or the whole page body if omitted."""
    page = await _active_page(session_id)
    if selector:
        element = await page.query_selector(selector)
        text = await element.inner_text() if element else ""
    else:
        text = await page.inner_text("body")
    return {"selector": selector, "text": text}


async def browser_get_html(
    selector: str | None = None,
    *,
    session_id: str = _DEFAULT_SESSION,
) -> dict[str, Any]:
    """Get inner HTML of *selector* or the whole page if omitted."""
    page = await _active_page(session_id)
    if selector:
        element = await page.query_selector(selector)
        html = await element.inner_html() if element else ""
    else:
        html = await page.content()
    return {"selector": selector, "html": html[:8000]}  # cap at 8KB


async def browser_get_url(*, session_id: str = _DEFAULT_SESSION) -> dict[str, Any]:
    """Return the current page URL and title."""
    page = await _active_page(session_id)
    return {"url": page.url, "title": await page.title()}


async def browser_go_back(*, session_id: str = _DEFAULT_SESSION) -> dict[str, Any]:
    """Navigate back in browser history."""
    page = await _active_page(session_id)
    await page.go_back()
    return {"url": page.url, "title": await page.title()}


async def browser_go_forward(*, session_id: str = _DEFAULT_SESSION) -> dict[str, Any]:
    """Navigate forward in browser history."""
    page = await _active_page(session_id)
    await page.go_forward()
    return {"url": page.url, "title": await page.title()}


async def browser_reload(*, session_id: str = _DEFAULT_SESSION) -> dict[str, Any]:
    """Reload the current page."""
    page = await _active_page(session_id)
    await page.reload()
    return {"url": page.url, "title": await page.title()}


async def browser_new_tab(*, session_id: str = _DEFAULT_SESSION) -> dict[str, Any]:
    """Open a new browser tab and make it the active page."""
    sess = _sessions.get(session_id)
    if not sess or not sess.get("context"):
        raise RuntimeError(f"Browser not launched for session {session_id!r}.")
    page = await sess["context"].new_page()
    tab_id = str(len(sess["pages"]))
    sess["pages"][tab_id] = page
    sess["active_page"] = page
    return {"tab_id": tab_id, "url": page.url}


async def browser_close_tab(
    tab_id: str | None = None,
    *,
    session_id: str = _DEFAULT_SESSION,
) -> dict[str, Any]:
    """Close the specified tab (or the active tab if omitted)."""
    sess = _sessions.get(session_id)
    if not sess:
        raise RuntimeError(f"Browser not launched for session {session_id!r}.")
    if tab_id is None:
        # find active page tab_id
        active = sess.get("active_page")
        tab_id = next((k for k, v in sess["pages"].items() if v is active), None)
    if tab_id and tab_id in sess["pages"]:
        page = sess["pages"].pop(tab_id)
        await page.close()
        # Switch to last remaining page
        remaining = list(sess["pages"].values())
        sess["active_page"] = remaining[-1] if remaining else None
    return {"closed_tab": tab_id, "remaining_tabs": list(sess.get("pages", {}).keys())}


async def browser_list_tabs(*, session_id: str = _DEFAULT_SESSION) -> dict[str, Any]:
    """List all open tabs with their URLs."""
    sess = _sessions.get(session_id)
    if not sess:
        return {"tabs": []}
    tabs: list[dict] = []
    for tab_id, page in sess.get("pages", {}).items():
        try:
            tabs.append({"tab_id": tab_id, "url": page.url, "title": await page.title()})
        except Exception:  # noqa: BLE001
            tabs.append({"tab_id": tab_id, "url": "unknown", "title": "closed"})
    return {"tabs": tabs}


async def browser_switch_tab(
    tab_id: str,
    *,
    session_id: str = _DEFAULT_SESSION,
) -> dict[str, Any]:
    """Switch to a tab by *tab_id*."""
    sess = _sessions.get(session_id)
    if not sess:
        raise RuntimeError(f"Browser not launched for session {session_id!r}.")
    page = sess["pages"].get(tab_id)
    if not page:
        raise ValueError(f"Tab {tab_id!r} not found.")
    sess["active_page"] = page
    await page.bring_to_front()
    return {"active_tab": tab_id, "url": page.url}


async def browser_wait_for_navigation(
    *,
    session_id: str = _DEFAULT_SESSION,
    wait_until: str = "load",
    timeout: int = 30_000,
) -> dict[str, Any]:
    """Wait for navigation to complete after triggering an action."""
    page = await _active_page(session_id)
    await page.wait_for_load_state(wait_until, timeout=timeout)
    return {"url": page.url, "title": await page.title(), "state": wait_until}


async def browser_hover(
    selector: str,
    *,
    session_id: str = _DEFAULT_SESSION,
) -> dict[str, Any]:
    """Hover over an element (useful for triggering dropdowns/tooltips)."""
    page = await _active_page(session_id)
    await page.hover(selector)
    return {"hovered": selector}


async def browser_press_key(
    key: str,
    *,
    session_id: str = _DEFAULT_SESSION,
    selector: str | None = None,
) -> dict[str, Any]:
    """Press a keyboard key. If *selector* given, focuses it first."""
    page = await _active_page(session_id)
    if selector:
        await page.focus(selector)
    await page.keyboard.press(key)
    return {"key_pressed": key, "selector": selector}


async def browser_fetch_page(
    url: str,
    *,
    session_id: str = _DEFAULT_SESSION,
    wait_until: str = "networkidle",
    extract_text: bool = True,
) -> dict[str, Any]:
    """Navigate to *url* and return rendered HTML/text (bypasses JavaScript restrictions)."""
    page = await _active_page(session_id)
    await page.goto(url, wait_until=wait_until)
    if extract_text:
        text = await page.inner_text("body")
        return {"url": page.url, "title": await page.title(), "text": text[:10000]}
    html = await page.content()
    return {"url": page.url, "title": await page.title(), "html": html[:15000]}


async def browser_query_all(
    selector: str,
    attribute: str | None = None,
    *,
    session_id: str = _DEFAULT_SESSION,
) -> dict[str, Any]:
    """Query all elements matching *selector*, returning text or an attribute."""
    page = await _active_page(session_id)
    elements = await page.query_selector_all(selector)
    results: list[str] = []
    for el in elements:
        if attribute:
            val = await el.get_attribute(attribute)
            results.append(val or "")
        else:
            results.append(await el.inner_text())
    return {"selector": selector, "count": len(results), "results": results}


# ---------------------------------------------------------------------------
# Tool definition list
# ---------------------------------------------------------------------------

BROWSER_TOOLS: list[dict[str, Any]] = [
    {
        "name": "browser_launch",
        "fn": browser_launch,
        "description": "Launch a Chromium browser instance for a session.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "default": _DEFAULT_SESSION},
                "headless": {"type": "boolean", "default": True},
                "viewport_width": {"type": "integer", "default": 1280},
                "viewport_height": {"type": "integer", "default": 800},
            },
            "required": [],
        },
        "safety": "side_effect",
    },
    {
        "name": "browser_close",
        "fn": browser_close,
        "description": "Close the browser instance for a session and free its resources.",
        "parameters": {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": [],
        },
        "safety": "side_effect",
    },
    {
        "name": "browser_navigate",
        "fn": browser_navigate,
        "description": "Navigate to a URL in the current browser tab.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "session_id": {"type": "string"},
                "wait_until": {"type": "string", "enum": ["load", "domcontentloaded", "networkidle"], "default": "load"},
            },
            "required": ["url"],
        },
        "safety": "side_effect",
    },
    {
        "name": "browser_click",
        "fn": browser_click,
        "description": "Click on an element matching a CSS selector.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "session_id": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": ["selector"],
        },
        "safety": "side_effect",
    },
    {
        "name": "browser_type",
        "fn": browser_type,
        "description": "Type text into an input element matching a CSS selector.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "text": {"type": "string"},
                "session_id": {"type": "string"},
                "delay": {"type": "integer", "default": 0, "description": "Delay between keystrokes in ms."},
            },
            "required": ["selector", "text"],
        },
        "safety": "side_effect",
    },
    {
        "name": "browser_screenshot",
        "fn": browser_screenshot,
        "description": "Take a screenshot of the page or a specific element; returns base64 PNG.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "full_page": {"type": "boolean", "default": False},
                "selector": {"type": "string"},
            },
            "required": [],
        },
        "safety": "read_only",
    },
    {
        "name": "browser_evaluate",
        "fn": browser_evaluate,
        "description": "Evaluate a JavaScript expression in the page context and return the result.",
        "parameters": {
            "type": "object",
            "properties": {
                "script": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["script"],
        },
        "safety": "side_effect",
    },
    {
        "name": "browser_wait",
        "fn": browser_wait,
        "description": "Wait for a selector to appear or for a fixed number of milliseconds.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "selector": {"type": "string"},
                "state": {"type": "string", "enum": ["visible", "hidden", "attached", "detached"], "default": "visible"},
                "milliseconds": {"type": "integer"},
                "timeout": {"type": "integer"},
            },
            "required": [],
        },
        "safety": "read_only",
    },
    {
        "name": "browser_scroll",
        "fn": browser_scroll,
        "description": "Scroll the page in a direction by a given pixel amount.",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"], "default": "down"},
                "amount": {"type": "integer", "default": 500},
                "session_id": {"type": "string"},
            },
            "required": [],
        },
        "safety": "side_effect",
    },
    {
        "name": "browser_select",
        "fn": browser_select,
        "description": "Select an option in a <select> dropdown by value.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "value": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                "session_id": {"type": "string"},
            },
            "required": ["selector", "value"],
        },
        "safety": "side_effect",
    },
    {
        "name": "browser_fill_form",
        "fn": browser_fill_form,
        "description": "Fill multiple form fields from a {selector: value} map; optionally submit.",
        "parameters": {
            "type": "object",
            "properties": {
                "form_data": {"type": "object", "additionalProperties": {"type": "string"}},
                "session_id": {"type": "string"},
                "submit_selector": {"type": "string"},
            },
            "required": ["form_data"],
        },
        "safety": "side_effect",
    },
    {
        "name": "browser_get_text",
        "fn": browser_get_text,
        "description": "Get the visible text content of a selector or the full page body.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": [],
        },
        "safety": "read_only",
    },
    {
        "name": "browser_get_html",
        "fn": browser_get_html,
        "description": "Get the inner HTML of a selector or the full page (capped at 8KB).",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": [],
        },
        "safety": "read_only",
    },
    {
        "name": "browser_get_url",
        "fn": browser_get_url,
        "description": "Return the current page URL and title.",
        "parameters": {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": [],
        },
        "safety": "read_only",
    },
    {
        "name": "browser_go_back",
        "fn": browser_go_back,
        "description": "Navigate back in browser history.",
        "parameters": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": []},
        "safety": "side_effect",
    },
    {
        "name": "browser_go_forward",
        "fn": browser_go_forward,
        "description": "Navigate forward in browser history.",
        "parameters": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": []},
        "safety": "side_effect",
    },
    {
        "name": "browser_reload",
        "fn": browser_reload,
        "description": "Reload the current page.",
        "parameters": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": []},
        "safety": "side_effect",
    },
    {
        "name": "browser_new_tab",
        "fn": browser_new_tab,
        "description": "Open a new browser tab and switch to it.",
        "parameters": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": []},
        "safety": "side_effect",
    },
    {
        "name": "browser_close_tab",
        "fn": browser_close_tab,
        "description": "Close the active tab or a specific tab by tab_id.",
        "parameters": {
            "type": "object",
            "properties": {
                "tab_id": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": [],
        },
        "safety": "side_effect",
    },
    {
        "name": "browser_list_tabs",
        "fn": browser_list_tabs,
        "description": "List all open browser tabs with their URLs and titles.",
        "parameters": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": []},
        "safety": "read_only",
    },
    {
        "name": "browser_switch_tab",
        "fn": browser_switch_tab,
        "description": "Switch to a specific browser tab by tab_id.",
        "parameters": {
            "type": "object",
            "properties": {
                "tab_id": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["tab_id"],
        },
        "safety": "side_effect",
    },
    {
        "name": "browser_wait_for_navigation",
        "fn": browser_wait_for_navigation,
        "description": "Wait for page navigation to complete after triggering an action.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "wait_until": {"type": "string", "enum": ["load", "domcontentloaded", "networkidle"], "default": "load"},
                "timeout": {"type": "integer", "default": 30000},
            },
            "required": [],
        },
        "safety": "read_only",
    },
    {
        "name": "browser_hover",
        "fn": browser_hover,
        "description": "Hover over an element to trigger hover effects like tooltips or dropdowns.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["selector"],
        },
        "safety": "side_effect",
    },
    {
        "name": "browser_press_key",
        "fn": browser_press_key,
        "description": "Press a keyboard key (e.g. 'Enter', 'Tab', 'ArrowDown').",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key name (e.g. 'Enter', 'Tab', 'ArrowDown')."},
                "selector": {"type": "string", "description": "Optional: focus this element first."},
                "session_id": {"type": "string"},
            },
            "required": ["key"],
        },
        "safety": "side_effect",
    },
    {
        "name": "browser_fetch_page",
        "fn": browser_fetch_page,
        "description": "Navigate to a URL and return the rendered text/HTML (handles JavaScript-heavy sites).",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "session_id": {"type": "string"},
                "wait_until": {"type": "string", "enum": ["load", "domcontentloaded", "networkidle"], "default": "networkidle"},
                "extract_text": {"type": "boolean", "default": True},
            },
            "required": ["url"],
        },
        "safety": "read_only",
    },
]

TOOL_FN_MAP: dict[str, Any] = {t["name"]: t["fn"] for t in BROWSER_TOOLS}
