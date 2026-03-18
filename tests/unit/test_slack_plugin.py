"""Unit tests for the Slack connector plugin (Sprint 16 §29.2 D2).

Tests cover:
  - Tool list structure
  - configure() / activate() / deactivate()
  - health_check() / test() (mocked API)
  - Plugin metadata
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.plugins.builtin.slack.plugin import SlackPlugin
from app.plugins.builtin.slack.tools import SLACK_TOOLS


# ── Tools ─────────────────────────────────────────────────────────────────────

class TestSlackTools:
    def test_three_tools(self):
        assert len(SLACK_TOOLS) == 3

    def test_tool_names(self):
        names = {t["name"] for t in SLACK_TOOLS}
        assert names == {"slack_send", "slack_search", "slack_react"}

    def test_send_required_fields(self):
        send = next(t for t in SLACK_TOOLS if t["name"] == "slack_send")
        assert "channel" in send["parameters"]["required"]
        assert "text" in send["parameters"]["required"]

    def test_search_required_fields(self):
        search = next(t for t in SLACK_TOOLS if t["name"] == "slack_search")
        assert "query" in search["parameters"]["required"]

    def test_react_required_fields(self):
        react = next(t for t in SLACK_TOOLS if t["name"] == "slack_react")
        for field in ("channel", "message_ts", "emoji"):
            assert field in react["parameters"]["required"]


# ── Metadata ──────────────────────────────────────────────────────────────────

class TestSlackPluginMetadata:
    def test_plugin_id(self):
        assert SlackPlugin.plugin_id == "slack"

    def test_plugin_type(self):
        assert SlackPlugin.plugin_type == "connector"

    def test_name(self):
        assert "Slack" in SlackPlugin.name


# ── Lifecycle ─────────────────────────────────────────────────────────────────

class TestSlackPluginLifecycle:
    @pytest.fixture
    def plugin(self) -> SlackPlugin:
        return SlackPlugin()

    @pytest.mark.asyncio
    async def test_configure_sets_token(self, plugin: SlackPlugin):
        async def store(pid, key):
            return "xoxb-test-token" if key == "bot_token" else None
        await plugin.configure({}, store)
        assert plugin._token == "xoxb-test-token"

    @pytest.mark.asyncio
    async def test_configure_missing_token_raises(self, plugin: SlackPlugin):
        async def store(pid, key):
            return None
        with pytest.raises(ValueError, match="bot_token"):
            await plugin.configure({}, store)

    @pytest.mark.asyncio
    async def test_activate(self, plugin: SlackPlugin):
        plugin._token = "xoxb-test"
        await plugin.activate()
        assert plugin._active is True

    @pytest.mark.asyncio
    async def test_activate_unconfigured_raises(self, plugin: SlackPlugin):
        with pytest.raises(RuntimeError):
            await plugin.activate()

    @pytest.mark.asyncio
    async def test_deactivate(self, plugin: SlackPlugin):
        plugin._token = "xoxb-test"
        await plugin.activate()
        await plugin.deactivate()
        assert plugin._active is False

    @pytest.mark.asyncio
    async def test_get_tools(self, plugin: SlackPlugin):
        tools = await plugin.get_tools()
        assert len(tools) == 3


# ── Health & test ─────────────────────────────────────────────────────────────

class TestSlackPluginHealth:
    @pytest.mark.asyncio
    async def test_health_not_configured(self):
        plugin = SlackPlugin()
        result = await plugin.health_check()
        assert result.healthy is False

    @pytest.mark.asyncio
    async def test_health_ok(self):
        plugin = SlackPlugin()
        plugin._token = "xoxb-test"
        mock_response = {"ok": True, "team": "TestTeam", "user": "testbot"}
        with patch.object(plugin, "_api_call", new=AsyncMock(return_value=mock_response)):
            result = await plugin.health_check()
        assert result.healthy is True
        assert "TestTeam" in result.message

    @pytest.mark.asyncio
    async def test_health_api_error(self):
        plugin = SlackPlugin()
        plugin._token = "xoxb-test"
        with patch.object(
            plugin, "_api_call", new=AsyncMock(side_effect=RuntimeError("invalid_auth"))
        ):
            result = await plugin.health_check()
        assert result.healthy is False
        assert "invalid_auth" in result.message

    @pytest.mark.asyncio
    async def test_test_ok(self):
        plugin = SlackPlugin()
        plugin._token = "xoxb-test"
        mock_response = {"ok": True, "user": "testbot", "team": "TestTeam"}
        with patch.object(plugin, "_api_call", new=AsyncMock(return_value=mock_response)):
            result = await plugin.test()
        assert result.success is True
        assert result.latency_ms is not None

    @pytest.mark.asyncio
    async def test_test_not_configured(self):
        plugin = SlackPlugin()
        result = await plugin.test()
        assert result.success is False


# ── Auth spec ─────────────────────────────────────────────────────────────────

class TestSlackPluginSpec:
    def test_auth_spec(self):
        plugin = SlackPlugin()
        spec = plugin.get_auth_spec()
        assert spec.kind == "token"

    def test_channel_adapter(self):
        plugin = SlackPlugin()
        import asyncio
        adapter = asyncio.get_event_loop().run_until_complete(plugin.get_channel_adapter())
        assert adapter.channel_name == "slack"
        assert adapter.supports_outbound is True
