"""Unit tests for WhatsApp and Signal connector plugins (Sprint 16 D4/D5)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.plugins.builtin.whatsapp.plugin import WhatsAppPlugin
from app.plugins.builtin.whatsapp.tools import WHATSAPP_TOOLS
from app.plugins.builtin.signal.plugin import SignalPlugin
from app.plugins.builtin.signal.tools import SIGNAL_TOOLS


# ── WhatsApp tools ────────────────────────────────────────────────────────────

class TestWhatsAppTools:
    def test_two_tools(self):
        assert len(WHATSAPP_TOOLS) == 2

    def test_tool_names(self):
        names = {t["name"] for t in WHATSAPP_TOOLS}
        assert names == {"whatsapp_send", "whatsapp_send_media"}

    def test_send_required(self):
        send = next(t for t in WHATSAPP_TOOLS if t["name"] == "whatsapp_send")
        assert "number" in send["parameters"]["required"]
        assert "text" in send["parameters"]["required"]

    def test_send_media_required(self):
        media = next(t for t in WHATSAPP_TOOLS if t["name"] == "whatsapp_send_media")
        assert "number" in media["parameters"]["required"]
        assert "file_path" in media["parameters"]["required"]


# ── WhatsApp plugin lifecycle ─────────────────────────────────────────────────

class TestWhatsAppPluginLifecycle:
    @pytest.fixture
    def plugin(self) -> WhatsAppPlugin:
        return WhatsAppPlugin()

    @pytest.mark.asyncio
    async def test_configure_both_credentials(self, plugin: WhatsAppPlugin):
        async def store(pid, key):
            return {"phone_number_id": "12345", "access_token": "EAAt..."}.get(key)
        await plugin.configure({}, store)
        assert plugin._phone_number_id == "12345"
        assert plugin._access_token == "EAAt..."

    @pytest.mark.asyncio
    async def test_configure_missing_raises(self, plugin: WhatsAppPlugin):
        async def store(pid, key):
            return None
        with pytest.raises(ValueError, match="phone_number_id"):
            await plugin.configure({}, store)

    @pytest.mark.asyncio
    async def test_activate(self, plugin: WhatsAppPlugin):
        plugin._phone_number_id = "12345"
        plugin._access_token = "EAAt..."
        await plugin.activate()
        assert plugin._active is True

    @pytest.mark.asyncio
    async def test_deactivate(self, plugin: WhatsAppPlugin):
        plugin._phone_number_id = "12345"
        plugin._access_token = "EAAt..."
        await plugin.activate()
        await plugin.deactivate()
        assert plugin._active is False

    @pytest.mark.asyncio
    async def test_get_tools(self, plugin: WhatsAppPlugin):
        tools = await plugin.get_tools()
        assert len(tools) == 2


class TestWhatsAppPluginHealth:
    @pytest.mark.asyncio
    async def test_health_not_configured(self):
        plugin = WhatsAppPlugin()
        result = await plugin.health_check()
        assert result.healthy is False

    @pytest.mark.asyncio
    async def test_health_ok(self):
        plugin = WhatsAppPlugin()
        plugin._phone_number_id = "12345"
        plugin._access_token = "token"
        mock_data = {"display_phone_number": "+1 555 000 0000"}
        with patch.object(plugin, "_api_get", new=AsyncMock(return_value=mock_data)):
            result = await plugin.health_check()
        assert result.healthy is True

    @pytest.mark.asyncio
    async def test_health_api_error(self):
        plugin = WhatsAppPlugin()
        plugin._phone_number_id = "12345"
        plugin._access_token = "token"
        with patch.object(
            plugin, "_api_get", new=AsyncMock(side_effect=Exception("401"))
        ):
            result = await plugin.health_check()
        assert result.healthy is False


# ── Signal tools ──────────────────────────────────────────────────────────────

class TestSignalTools:
    def test_two_tools(self):
        assert len(SIGNAL_TOOLS) == 2

    def test_tool_names(self):
        names = {t["name"] for t in SIGNAL_TOOLS}
        assert names == {"signal_send", "signal_send_file"}

    def test_send_required(self):
        send = next(t for t in SIGNAL_TOOLS if t["name"] == "signal_send")
        assert "recipient" in send["parameters"]["required"]
        assert "message" in send["parameters"]["required"]

    def test_send_file_required(self):
        sf = next(t for t in SIGNAL_TOOLS if t["name"] == "signal_send_file")
        assert "recipient" in sf["parameters"]["required"]
        assert "file_path" in sf["parameters"]["required"]


# ── Signal plugin lifecycle ───────────────────────────────────────────────────

class TestSignalPluginLifecycle:
    @pytest.fixture
    def plugin(self) -> SignalPlugin:
        return SignalPlugin()

    @pytest.mark.asyncio
    async def test_configure_account(self, plugin: SignalPlugin):
        async def store(pid, key):
            return "+15551234567" if key == "account" else None
        await plugin.configure({}, store)
        assert plugin._account == "+15551234567"

    @pytest.mark.asyncio
    async def test_configure_missing_raises(self, plugin: SignalPlugin):
        async def store(pid, key):
            return None
        with pytest.raises(ValueError, match="account"):
            await plugin.configure({}, store)

    @pytest.mark.asyncio
    async def test_activate(self, plugin: SignalPlugin):
        plugin._account = "+15551234567"
        await plugin.activate()
        assert plugin._active is True

    @pytest.mark.asyncio
    async def test_deactivate(self, plugin: SignalPlugin):
        plugin._account = "+15551234567"
        await plugin.activate()
        await plugin.deactivate()
        assert plugin._active is False

    @pytest.mark.asyncio
    async def test_get_tools(self, plugin: SignalPlugin):
        tools = await plugin.get_tools()
        assert len(tools) == 2

    @pytest.mark.asyncio
    async def test_configure_custom_http_url(self, plugin: SignalPlugin):
        async def store(pid, key):
            return {
                "account": "+15551234567",
                "http_url": "http://192.168.1.50:8080",
            }.get(key)
        await plugin.configure({}, store)
        assert plugin._http_url == "http://192.168.1.50:8080"


class TestSignalPluginHealth:
    @pytest.mark.asyncio
    async def test_health_not_configured(self):
        plugin = SignalPlugin()
        result = await plugin.health_check()
        assert result.healthy is False

    @pytest.mark.asyncio
    async def test_health_account_found(self):
        plugin = SignalPlugin()
        plugin._account = "+15551234567"
        mock_result = {"result": [{"number": "+15551234567"}]}
        with patch.object(plugin, "_rpc_call", new=AsyncMock(return_value=mock_result)):
            result = await plugin.health_check()
        assert result.healthy is True

    @pytest.mark.asyncio
    async def test_health_account_not_in_daemon(self):
        plugin = SignalPlugin()
        plugin._account = "+15551234567"
        mock_result = {"result": [{"number": "+19999999999"}]}
        with patch.object(plugin, "_rpc_call", new=AsyncMock(return_value=mock_result)):
            result = await plugin.health_check()
        assert result.healthy is False
        assert "not found" in result.message

    @pytest.mark.asyncio
    async def test_health_daemon_unreachable(self):
        plugin = SignalPlugin()
        plugin._account = "+15551234567"
        with patch.object(
            plugin, "_rpc_call", new=AsyncMock(side_effect=Exception("Connection refused"))
        ):
            result = await plugin.health_check()
        assert result.healthy is False


# ── Metadata ──────────────────────────────────────────────────────────────────

class TestConnectorMetadata:
    def test_whatsapp_id(self):
        assert WhatsAppPlugin.plugin_id == "whatsapp"
        assert WhatsAppPlugin.plugin_type == "connector"

    def test_signal_id(self):
        assert SignalPlugin.plugin_id == "signal"
        assert SignalPlugin.plugin_type == "connector"
