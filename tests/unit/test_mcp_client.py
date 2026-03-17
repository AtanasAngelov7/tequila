"""Unit tests for Sprint 13 D4 — MCPClient (stdio & http transports)."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.plugins.mcp.client import MCPClient


# ── Helpers ───────────────────────────────────────────────────────────────────


def _jsonrpc_response(id_: int, result: dict) -> bytes:
    return (json.dumps({"jsonrpc": "2.0", "id": id_, "result": result}) + "\n").encode()


# ── HTTP transport ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_http_list_tools():
    """MCPClient(http) should return tools from the remote server."""
    tools_response = {
        "tools": [
            {"name": "hello", "description": "Says hello", "inputSchema": {"type": "object", "properties": {}}}
        ]
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": tools_response}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        MockClient.return_value = mock_client

        client = MCPClient(transport="http", url_or_command="http://localhost:9000/mcp")
        await client.connect()
        tools = await client.list_tools()

    assert len(tools) == 1
    assert tools[0]["name"] == "hello"


@pytest.mark.asyncio
async def test_http_call_tool():
    """call_tool() should POST a JSON-RPC request and return the result."""
    call_response = {"content": [{"type": "text", "text": "world"}]}

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"jsonrpc": "2.0", "id": 2, "result": call_response}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        MockClient.return_value = mock_client

        client = MCPClient(transport="http", url_or_command="http://localhost:9000/mcp")
        await client.connect()
        result = await client.call_tool("hello", {})

    assert result == "world"


@pytest.mark.asyncio
async def test_http_call_tool_error_raises():
    """call_tool() should raise RuntimeError on a JSON-RPC error response."""
    error_response = {"jsonrpc": "2.0", "id": 2, "error": {"code": -32601, "message": "Method not found"}}

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = error_response
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        MockClient.return_value = mock_client

        client = MCPClient(transport="http", url_or_command="http://localhost:9000/mcp")
        await client.connect()
        with pytest.raises(RuntimeError, match="Method not found"):
            await client.call_tool("missing", {})


# ── Stdio transport ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stdio_list_tools():
    """MCPClient(stdio) should parse tools/list response from child process."""
    tools_payload = {
        "tools": [
            {"name": "greet", "description": "Greet", "inputSchema": {"type": "object", "properties": {}}}
        ]
    }

    # Simulate:  initialize ← reply,  tools/list ← reply
    responses = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "0.1", "capabilities": {}}}) + "\n",
        json.dumps({"jsonrpc": "2.0", "id": 2, "result": tools_payload}) + "\n",
    ]

    mock_process = MagicMock()
    mock_process.stdin = MagicMock()
    mock_process.stdin.write = MagicMock()
    mock_process.stdin.drain = AsyncMock()

    response_iter = iter(responses)

    async def fake_readline():
        try:
            return next(response_iter).encode()
        except StopIteration:
            return b""

    mock_process.stdout = MagicMock()
    mock_process.stdout.readline = fake_readline
    mock_process.returncode = None

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)):
        client = MCPClient(transport="stdio", url_or_command="npx mcp-server")
        await client.connect()
        tools = await client.list_tools()

    assert len(tools) == 1
    assert tools[0]["name"] == "greet"


# ── Ping ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ping_returns_true_when_rpc_succeeds():
    """ping() should return True when _rpc('ping', {}) succeeds."""
    client = MCPClient(transport="http", url_or_command="http://localhost:9000/mcp")

    async def fake_rpc(method, params):
        if method == "ping":
            return {}
        raise RuntimeError(f"Unexpected method {method}")

    client._rpc = fake_rpc  # type: ignore[assignment]
    result = await client.ping()
    assert result is True


@pytest.mark.asyncio
async def test_ping_returns_false_when_rpc_fails():
    """ping() should return False when _rpc raises an exception."""
    client = MCPClient(transport="http", url_or_command="http://localhost:9000/mcp")

    async def fake_rpc(method, params):
        raise ConnectionRefusedError("server down")

    client._rpc = fake_rpc  # type: ignore[assignment]
    result = await client.ping()
    assert result is False
