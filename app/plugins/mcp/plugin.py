"""MCP (Model Context Protocol) plugin (Sprint 13, §8.6, §17.3).

Each MCP server is configured as its own plugin instance.
On activate():
1. Connect to the MCP server (stdio or http).
2. List available tools.
3. Register each tool in the global ToolRegistry with a proxy callable.

The config dict is expected to have:
    {
        "transport": "stdio" | "http",
        "url_or_command": "...",       # URL or command to spawn
        "auth": {"header": "...", "value": "..."},  # optional
        "timeout": 30,                 # optional seconds
    }
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.plugins.base import PluginBase
from app.plugins.mcp.client import MCPClient
from app.plugins.models import PluginAuth, PluginDependencies, PluginHealthResult

logger = logging.getLogger(__name__)


class MCPPlugin(PluginBase):
    """Plugin that proxies an external MCP server's tools into Tequila's tool registry."""

    plugin_id = "mcp"
    name = "MCP Server"
    description = (
        "Connect to an external Model Context Protocol server (stdio or HTTP transport). "
        "All tools provided by the MCP server are auto-discovered and made available to agents."
    )
    version = "1.0.0"
    plugin_type = "connector"

    def __init__(self) -> None:
        self._client: MCPClient | None = None
        self._registered_names: list[str] = []
        self._config: dict[str, Any] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def configure(self, config: dict[str, Any], auth_store: Any) -> None:
        transport = config.get("transport", "http")
        url_or_command = config.get("url_or_command", "")
        if not url_or_command:
            raise ValueError("MCP plugin requires 'url_or_command' in config.")
        auth_header = await auth_store("mcp", "auth_header") or ""
        auth_value = await auth_store("mcp", "auth_value") or ""
        auth = {"header": auth_header, "value": auth_value} if auth_value else None
        self._config = {
            "transport": transport,
            "url_or_command": url_or_command,
            "auth": auth,
            "timeout": float(config.get("timeout", 30)),
        }

    async def activate(self) -> None:
        cfg = self._config
        self._client = MCPClient(
            transport=cfg["transport"],
            url_or_command=cfg["url_or_command"],
            auth=cfg.get("auth"),
            timeout=cfg.get("timeout", 30.0),
        )
        await self._client.connect()
        tools = await self._client.list_tools()
        await self._register_tools(tools)
        logger.info(
            "MCPPlugin activated — %d tools discovered from MCP server.",
            len(self._registered_names),
        )

    async def deactivate(self) -> None:
        # TD-149: Unregister MCP tools from the global ToolRegistry
        if self._registered_names:
            try:
                from app.tools.registry import get_tool_registry
                registry = get_tool_registry()
                for name in self._registered_names:
                    registry.unregister(name)
                logger.info("Unregistered %d MCP tools.", len(self._registered_names))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error unregistering MCP tools: %s", exc)
        if self._client:
            await self._client.disconnect()
            self._client = None
        self._registered_names = []
        logger.info("MCPPlugin deactivated.")

    # ── Tool registration ─────────────────────────────────────────────────────

    async def _register_tools(self, mcp_tools: list[dict[str, Any]]) -> None:
        """Convert MCP tool objects to ToolDefinition and register them."""
        from app.tools.registry import ToolDefinition, get_tool_registry

        registry = get_tool_registry()
        self._registered_names = []

        for mcp_tool in mcp_tools:
            name: str = mcp_tool["name"]
            description: str = mcp_tool.get("description", f"MCP tool: {name}")
            # MCP inputSchema is already a JSON Schema object
            parameters: dict[str, Any] = mcp_tool.get("inputSchema", {
                "type": "object",
                "properties": {},
                "required": [],
            })

            # Build a proxy callable captured in closure
            client_ref = self._client

            def _make_proxy(tool_name: str, client: MCPClient):  # noqa: ANN202
                async def proxy(**kwargs: Any) -> Any:
                    if client is None:
                        raise RuntimeError("MCP plugin not connected.")
                    return await client.call_tool(tool_name, kwargs)
                proxy.__name__ = tool_name
                return proxy

            td = ToolDefinition(
                name=name,
                description=description,
                parameters=parameters,
                safety="side_effect",
            )
            proxy_fn = _make_proxy(name, client_ref)
            registry.register(td, proxy_fn)
            self._registered_names.append(name)

    async def get_tools(self) -> list[Any]:
        """Return tool metadata for all tools proxied from the MCP server."""
        if not self._client:
            return []
        try:
            return await self._client.list_tools()
        except Exception:  # noqa: BLE001
            return []

    # ── Health check ──────────────────────────────────────────────────────────

    async def health_check(self) -> PluginHealthResult:
        if not self._client:
            return PluginHealthResult(healthy=False, message="Not connected.")
        alive = await self._client.ping()
        return PluginHealthResult(
            healthy=alive,
            message="pong" if alive else "MCP server did not respond to ping.",
        )

    # ── Config schema ─────────────────────────────────────────────────────────

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "transport": {
                    "type": "string",
                    "enum": ["stdio", "http"],
                    "description": "Transport to use when communicating with the MCP server.",
                },
                "url_or_command": {
                    "type": "string",
                    "description": "HTTP base URL or shell command to start the MCP server process.",
                },
                "timeout": {
                    "type": "number",
                    "default": 30,
                    "description": "Per-request timeout in seconds.",
                },
            },
            "required": ["transport", "url_or_command"],
        }

    def get_auth_spec(self) -> PluginAuth | None:
        return PluginAuth(kind="token", key_label="Auth Header Value (optional)")

    def get_dependencies(self) -> PluginDependencies:
        return PluginDependencies(python_packages=["httpx>=0.25"])
