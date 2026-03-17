"""Browser automation connector plugin (Sprint 13, §8.6, D2).

Uses Playwright (async API) to control a headless/headed Chromium browser.
Playwright is lazily imported — the package is only required when this plugin
is enabled.

To install Playwright + browser binaries:
    pip install playwright
    playwright install chromium
"""
from __future__ import annotations

import logging
from typing import Any

from app.plugins.base import PluginBase
from app.plugins.builtin.browser.tools import BROWSER_TOOLS, TOOL_FN_MAP
from app.plugins.models import PluginDependencies

logger = logging.getLogger(__name__)


class BrowserPlugin(PluginBase):
    """Playwright-based browser automation plugin — 25 browser tools."""

    plugin_id = "browser"
    name = "Browser"
    description = (
        "Control a headless Chromium browser. Navigate pages, click elements, take "
        "screenshots, fill forms, and extract content from JavaScript-heavy sites."
    )
    version = "1.0.0"
    plugin_type = "connector"

    def __init__(self) -> None:
        self._active = False
        self._default_headless = True
        self._default_viewport_width = 1280
        self._default_viewport_height = 800

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def configure(self, config: dict[str, Any], auth_store: Any) -> None:
        """Apply display / viewport configuration — no credentials required."""
        self._default_headless = config.get("headless", True)
        self._default_viewport_width = int(config.get("viewport_width", 1280))
        self._default_viewport_height = int(config.get("viewport_height", 800))

    async def activate(self) -> None:
        """Register browser tools in the global ToolRegistry."""
        from app.tools.registry import ToolDefinition, get_tool_registry

        registry = get_tool_registry()
        for tool_def in BROWSER_TOOLS:
            td = ToolDefinition(
                name=tool_def["name"],
                description=tool_def["description"],
                parameters=tool_def["parameters"],
                safety=tool_def.get("safety", "side_effect"),
            )
            fn = TOOL_FN_MAP[tool_def["name"]]
            registry.register(td, fn)

        self._active = True
        logger.info("BrowserPlugin activated — %d tools registered.", len(BROWSER_TOOLS))

    async def deactivate(self) -> None:
        """Close all open browser sessions and deactivate."""
        from app.plugins.builtin.browser.tools import _sessions
        import asyncio

        for session_id in list(_sessions.keys()):
            sess = _sessions.pop(session_id, None)
            if not sess:
                continue
            try:
                if sess.get("browser"):
                    await sess["browser"].close()
                if sess.get("playwright"):
                    await sess["playwright"].stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error closing browser session %r: %s", session_id, exc)

        self._active = False
        logger.info("BrowserPlugin deactivated — all sessions closed.")

    # ── Tools ─────────────────────────────────────────────────────────────────

    async def get_tools(self) -> list[Any]:
        return [
            {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}
            for t in BROWSER_TOOLS
        ]

    # ── Config schema ─────────────────────────────────────────────────────────

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "headless": {
                    "type": "boolean",
                    "default": True,
                    "description": "Run browser in headless mode (no visible window).",
                },
                "viewport_width": {
                    "type": "integer",
                    "default": 1280,
                },
                "viewport_height": {
                    "type": "integer",
                    "default": 800,
                },
            },
        }

    def get_auth_spec(self) -> None:
        return None

    def get_dependencies(self) -> PluginDependencies:
        return PluginDependencies(
            python_packages=["playwright>=1.40"],
            system_commands=["playwright install chromium"],
        )
