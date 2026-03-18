"""Unit tests for the Discord connector plugin (Sprint 16 §29.3 D3)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.plugins.builtin.discord.plugin import DiscordPlugin
from app.plugins.builtin.discord.tools import DISCORD_TOOLS


# ── Tools ─────────────────────────────────────────────────────────────────────

class TestDiscordTools:
    def test_three_tools(self):
        assert len(DISCORD_TOOLS) == 3

    def test_tool_names(self):
        names = {t["name"] for t in DISCORD_TOOLS}
        assert names == {"discord_send", "discord_react", "discord_get_messages"}

    def test_send_required(self):
        send = next(t for t in DISCORD_TOOLS if t["name"] == "discord_send")
        assert "channel_id" in send["parameters"]["required"]
        assert "text" in send["parameters"]["required"]

    def test_react_required(self):
        react = next(t for t in DISCORD_TOOLS if t["name"] == "discord_react")
        for field in ("channel_id", "message_id", "emoji"):
            assert field in react["parameters"]["required"]

    def test_get_messages_required(self):
        get_msgs = next(t for t in DISCORD_TOOLS if t["name"] == "discord_get_messages")
        assert "channel_id" in get_msgs["parameters"]["required"]


# ── Metadata ──────────────────────────────────────────────────────────────────

class TestDiscordPluginMetadata:
    def test_plugin_id(self):
        assert DiscordPlugin.plugin_id == "discord"

    def test_plugin_type(self):
        assert DiscordPlugin.plugin_type == "connector"

    def test_name(self):
        assert "Discord" in DiscordPlugin.name


# ── Lifecycle ─────────────────────────────────────────────────────────────────

class TestDiscordPluginLifecycle:
    @pytest.fixture
    def plugin(self) -> DiscordPlugin:
        return DiscordPlugin()

    @pytest.mark.asyncio
    async def test_configure_sets_token(self, plugin: DiscordPlugin):
        async def store(pid, key):
            return "Bot.test.token" if key == "bot_token" else None
        await plugin.configure({}, store)
        assert plugin._token == "Bot.test.token"

    @pytest.mark.asyncio
    async def test_configure_missing_raises(self, plugin: DiscordPlugin):
        async def store(pid, key):
            return None
        with pytest.raises(ValueError, match="bot_token"):
            await plugin.configure({}, store)

    @pytest.mark.asyncio
    async def test_activate(self, plugin: DiscordPlugin):
        plugin._token = "test"
        await plugin.activate()
        assert plugin._active is True

    @pytest.mark.asyncio
    async def test_deactivate(self, plugin: DiscordPlugin):
        plugin._token = "test"
        await plugin.activate()
        await plugin.deactivate()
        assert plugin._active is False

    @pytest.mark.asyncio
    async def test_get_tools(self, plugin: DiscordPlugin):
        tools = await plugin.get_tools()
        assert len(tools) == 3


# ── Health & test ─────────────────────────────────────────────────────────────

class TestDiscordPluginHealth:
    @pytest.mark.asyncio
    async def test_health_not_configured(self):
        plugin = DiscordPlugin()
        result = await plugin.health_check()
        assert result.healthy is False

    @pytest.mark.asyncio
    async def test_health_ok(self):
        plugin = DiscordPlugin()
        plugin._token = "test"
        mock_user = {"username": "tequila_bot", "discriminator": "1234"}
        with patch.object(plugin, "_api_get", new=AsyncMock(return_value=mock_user)):
            result = await plugin.health_check()
        assert result.healthy is True
        assert "tequila_bot" in result.message

    @pytest.mark.asyncio
    async def test_health_api_failure(self):
        plugin = DiscordPlugin()
        plugin._token = "test"
        with patch.object(
            plugin, "_api_get", new=AsyncMock(side_effect=Exception("401 Unauthorized"))
        ):
            result = await plugin.health_check()
        assert result.healthy is False

    @pytest.mark.asyncio
    async def test_test_ok(self):
        plugin = DiscordPlugin()
        plugin._token = "test"
        mock_user = {"username": "tequila_bot", "discriminator": "0"}
        with patch.object(plugin, "_api_get", new=AsyncMock(return_value=mock_user)):
            result = await plugin.test()
        assert result.success is True
        assert result.latency_ms is not None


# ── Channel adapter ───────────────────────────────────────────────────────────

class TestDiscordChannelAdapter:
    @pytest.mark.asyncio
    async def test_channel_adapter(self):
        plugin = DiscordPlugin()
        adapter = await plugin.get_channel_adapter()
        assert adapter.channel_name == "discord"
        assert adapter.supports_inbound is True
        assert adapter.supports_outbound is True
        assert adapter.polling_mode is False
