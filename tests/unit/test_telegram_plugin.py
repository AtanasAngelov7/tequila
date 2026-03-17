"""Unit tests for the Telegram built-in plugin (Sprint 12)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.plugins.builtin.telegram.plugin import TelegramPlugin
from app.plugins.builtin.telegram.tools import TELEGRAM_TOOLS


# ── Metadata ──────────────────────────────────────────────────────────────────


def test_plugin_id():
    assert TelegramPlugin.plugin_id == "telegram"


def test_plugin_type():
    assert TelegramPlugin.plugin_type == "connector"


def test_auth_spec():
    plugin = TelegramPlugin()
    spec = plugin.get_auth_spec()
    assert spec.kind == "token"


def test_dependencies():
    plugin = TelegramPlugin()
    deps = plugin.get_dependencies()
    assert any("httpx" in p for p in deps.python_packages)


# ── Tools schema ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_tools_returns_two_tools():
    plugin = TelegramPlugin()
    tools = await plugin.get_tools()
    names = [t["name"] for t in tools]
    assert "telegram_send_message" in names
    assert "telegram_list_chats" in names


def test_telegram_send_message_has_required_params():
    tool = next(t for t in TELEGRAM_TOOLS if t["name"] == "telegram_send_message")
    required = tool["parameters"]["required"]
    assert "chat_id" in required
    assert "text" in required


# ── Configure ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_configure_raises_without_token():
    plugin = TelegramPlugin()
    with pytest.raises(ValueError, match="bot_token"):
        await plugin.configure({}, AsyncMock(return_value=None))


@pytest.mark.asyncio
async def test_configure_succeeds_with_token():
    plugin = TelegramPlugin()

    async def mock_auth(plugin_id, key):
        return "fake-token" if key == "bot_token" else None

    await plugin.configure({}, mock_auth)
    assert plugin._token == "fake-token"


# ── Activate / deactivate ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_activate_starts_polling():
    plugin = TelegramPlugin()

    async def mock_auth(plugin_id, key):
        return "fake-token" if key == "bot_token" else None

    await plugin.configure({}, mock_auth)

    with patch.object(plugin, "_poll_loop", new_callable=AsyncMock) as mock_loop:
        import asyncio
        mock_loop.return_value = None
        await plugin.activate()
        assert plugin._active is True
        await plugin.deactivate()
        assert plugin._active is False


@pytest.mark.asyncio
async def test_deactivate_before_activate_is_safe():
    plugin = TelegramPlugin()
    await plugin.deactivate()  # Should not raise


# ── Health check ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_check_not_configured():
    plugin = TelegramPlugin()
    result = await plugin.health_check()
    assert result.healthy is False
    assert "configured" in result.message


@pytest.mark.asyncio
async def test_health_check_api_ok():
    plugin = TelegramPlugin()
    plugin._token = "fake-token"

    with patch.object(
        plugin,
        "_api_call",
        new_callable=AsyncMock,
        return_value={"ok": True, "result": {"username": "testbot"}},
    ):
        result = await plugin.health_check()
        assert result.healthy is True
        assert "testbot" in result.message


@pytest.mark.asyncio
async def test_health_check_api_error():
    plugin = TelegramPlugin()
    plugin._token = "bad-token"

    with patch.object(plugin, "_api_call", side_effect=RuntimeError("Unauthorized")):
        result = await plugin.health_check()
        assert result.healthy is False


# ── Test method ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_test_not_configured():
    plugin = TelegramPlugin()
    result = await plugin.test()
    assert result.success is False


@pytest.mark.asyncio
async def test_test_api_ok():
    plugin = TelegramPlugin()
    plugin._token = "fake-token"

    with patch.object(
        plugin,
        "_api_call",
        new_callable=AsyncMock,
        return_value={"ok": True, "result": {"username": "testbot"}},
    ):
        result = await plugin.test()
        assert result.success is True
        assert result.latency_ms is not None
