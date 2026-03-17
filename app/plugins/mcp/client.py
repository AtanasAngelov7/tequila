"""MCP (Model Context Protocol) client (Sprint 13, §8.6, §17.3).

Supports two transports:
- **stdio**: spawn an external process and exchange JSON-RPC over stdin/stdout.
- **http**:  exchange JSON-RPC over HTTP POST (SSE event streaming also accepted).

Protocol summary (MCP is JSON-RPC 2.0 wrapped):
1. Send ``initialize`` → receive ``InitializeResult`` with server capabilities.
2. Send ``tools/list`` → receive list of available tools.
3. Send ``tools/call`` with ``{name, arguments}`` → receive JSON result.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0  # seconds


class MCPError(RuntimeError):
    """Raised when the MCP server returns an error response."""


class MCPClient:
    """Thin async MCP client supporting stdio and http transports.

    Parameters
    ----------
    transport:
        ``"stdio"`` or ``"http"``.
    url_or_command:
        - For **stdio**: shell command string or list of args to spawn, e.g.
          ``["npx", "-y", "@modelcontextprotocol/server-everything"]``.
        - For **http**: base URL of the MCP HTTP endpoint, e.g.
          ``"http://localhost:8080"``.
    auth:
        Optional ``{"header": "Authorization", "value": "Bearer <token>"}``
        dict for http transport.
    timeout:
        Per-request timeout in seconds (default 30).
    """

    def __init__(
        self,
        transport: str,
        url_or_command: str | list[str],
        auth: dict[str, str] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        if transport not in ("stdio", "http"):
            raise ValueError(f"Unknown transport {transport!r}. Expected 'stdio' or 'http'.")
        self.transport = transport
        self.url_or_command = url_or_command
        self.auth = auth or {}
        self.timeout = timeout

        # stdio state
        self._proc: asyncio.subprocess.Process | None = None
        self._msg_id = 0

        # http state
        self._base_url: str = ""
        self._http_client: Any = None  # httpx.AsyncClient, lazy import

    # ── Public lifecycle ──────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Open connection and run MCP handshake."""
        if self.transport == "stdio":
            await self._stdio_connect()
        else:
            await self._http_connect()

    async def disconnect(self) -> None:
        """Close connection."""
        if self.transport == "stdio":
            await self._stdio_disconnect()
        else:
            await self._http_disconnect()

    # ── Tool discovery ────────────────────────────────────────────────────────

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return the server's tool list as a list of MCP tool dicts."""
        result = await self._rpc("tools/list", {})
        return result.get("tools", [])

    # ── Tool invocation ───────────────────────────────────────────────────────

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call an MCP tool and return its result."""
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        # MCP returns {content: [{type: "text", text: "..."}], isError: bool}
        if result.get("isError"):
            content = result.get("content", [])
            msg = " ".join(c.get("text", "") for c in content if c.get("type") == "text")
            raise MCPError(f"MCP tool {name!r} returned error: {msg}")
        content = result.get("content", [])
        if len(content) == 1 and content[0].get("type") == "text":
            return content[0]["text"]
        return content

    # ── Health check ──────────────────────────────────────────────────────────

    async def ping(self) -> bool:
        """Return True if the server responds to a ping."""
        try:
            await self._rpc("ping", {})
            return True
        except Exception:  # noqa: BLE001
            return False

    # ── STDIO transport ───────────────────────────────────────────────────────

    async def _stdio_connect(self) -> None:
        cmd = self.url_or_command
        args: list[str]
        if isinstance(cmd, list):
            prog, *args = cmd
        else:
            import shlex
            parts = shlex.split(cmd)
            prog, *args = parts

        # TD-138: Allowlist permitted MCP commands to prevent arbitrary command execution
        import os
        _ALLOWED_MCP_COMMANDS = {
            "node", "npx", "python", "python3", "uvx",
            "mcp-server", "mcp", "deno", "bun",
        }
        prog_base = os.path.splitext(os.path.basename(prog))[0].lower()
        if prog_base not in _ALLOWED_MCP_COMMANDS:
            raise ValueError(
                f"MCP stdio command {prog!r} is not in the allowed list: "
                f"{sorted(_ALLOWED_MCP_COMMANDS)}. "
                "Add it to _ALLOWED_MCP_COMMANDS if it is a trusted MCP server binary."
            )

        self._proc = await asyncio.create_subprocess_exec(
            prog,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info("MCPClient stdio process started (pid=%s).", self._proc.pid)
        await self._initialize()

    async def _stdio_disconnect(self) -> None:
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.stdin.close()  # type: ignore[union-attr]
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except (asyncio.TimeoutError, Exception):
                self._proc.kill()
        self._proc = None

    async def _stdio_send(self, msg: dict[str, Any]) -> None:
        assert self._proc and self._proc.stdin
        line = json.dumps(msg) + "\n"
        self._proc.stdin.write(line.encode())
        await self._proc.stdin.drain()

    async def _stdio_recv(self) -> dict[str, Any]:
        assert self._proc and self._proc.stdout
        line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=self.timeout)
        return json.loads(line.decode().strip())

    # ── HTTP transport ────────────────────────────────────────────────────────

    async def _http_connect(self) -> None:
        base = self.url_or_command
        self._base_url = base if isinstance(base, str) else base[0]
        # TD-151: SSRF validation for MCP HTTP transport
        import ipaddress
        from urllib.parse import urlparse
        try:
            parsed = urlparse(self._base_url)
            hostname = parsed.hostname or ""
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                raise ValueError(f"MCP HTTP transport blocked: {hostname!r} is a private/reserved IP")
        except ValueError as exc:
            if "blocked" in str(exc):
                raise
            # Not an IP literal — will be resolved by httpx
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.auth:
            hdr = self.auth.get("header", "Authorization")
            val = self.auth.get("value", "")
            headers[hdr] = val
        import httpx
        self._http_client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=self.timeout,
        )
        await self._initialize()

    async def _http_disconnect(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def _http_send_recv(self, payload: dict[str, Any]) -> dict[str, Any]:
        assert self._http_client is not None
        resp = await self._http_client.post("/", json=payload)
        resp.raise_for_status()
        return resp.json()

    # ── JSON-RPC core ─────────────────────────────────────────────────────────

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def _build_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        req = self._build_request(method, params)
        if self.transport == "stdio":
            await self._stdio_send(req)
            resp = await self._stdio_recv()
        else:
            resp = await self._http_send_recv(req)

        if "error" in resp:
            raise MCPError(f"MCP RPC error ({method}): {resp['error']}")
        return resp.get("result", {})

    async def _initialize(self) -> None:
        """Send MCP initialize handshake."""
        # TD-184: Source version from app constants
        from app.constants import APP_VERSION
        try:
            await self._rpc(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "tequila", "version": APP_VERSION},
                },
            )
            logger.debug("MCPClient initialised (%s transport).", self.transport)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MCPClient initialize failed (non-fatal): %s", exc)
