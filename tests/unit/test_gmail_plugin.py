"""Unit tests for the Gmail built-in plugin (Sprint 12)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.plugins.builtin.gmail.plugin import GmailPlugin
from app.plugins.builtin.gmail.tools import GMAIL_TOOLS


# ── Metadata ──────────────────────────────────────────────────────────────────


def test_plugin_id():
    assert GmailPlugin.plugin_id == "gmail"


def test_plugin_type():
    assert GmailPlugin.plugin_type == "connector"


def test_auth_spec_is_oauth2():
    plugin = GmailPlugin()
    spec = plugin.get_auth_spec()
    assert spec.kind == "oauth2"
    assert spec.oauth2_config is not None
    assert spec.oauth2_config.provider == "google"


def test_dependencies():
    plugin = GmailPlugin()
    deps = plugin.get_dependencies()
    packages = " ".join(deps.python_packages)
    assert "google-auth" in packages
    assert "google-api-python-client" in packages


# ── Tools ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_tools_returns_four_tools():
    plugin = GmailPlugin()
    tools = await plugin.get_tools()
    names = [t["name"] for t in tools]
    assert "gmail_list_messages" in names
    assert "gmail_get_message" in names
    assert "gmail_send" in names
    assert "gmail_mark_read" in names


def test_gmail_send_required_params():
    tool = next(t for t in GMAIL_TOOLS if t["name"] == "gmail_send")
    required = tool["parameters"]["required"]
    assert "to" in required
    assert "subject" in required
    assert "body" in required


# ── Configure ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_configure_raises_without_credentials():
    plugin = GmailPlugin()
    with pytest.raises(ValueError, match="OAuth2"):
        await plugin.configure({}, AsyncMock(return_value=None))


@pytest.mark.asyncio
async def test_configure_succeeds_with_credentials():
    plugin = GmailPlugin()
    creds = {
        "client_id": "cid",
        "client_secret": "csecret",
        "refresh_token": "rtoken",
    }

    async def mock_auth(plugin_id, key):
        return creds.get(key)

    await plugin.configure({}, mock_auth)
    assert plugin._client_id == "cid"
    assert plugin._refresh_token == "rtoken"


# ── Lifecycle ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_activate_builds_service():
    plugin = GmailPlugin()
    creds = {"client_id": "cid", "client_secret": "csecret", "refresh_token": "rtoken"}

    async def mock_auth(plugin_id, key):
        return creds.get(key)

    await plugin.configure({}, mock_auth)

    with patch.object(plugin, "_build_service", return_value=None) as mock_build:
        await plugin.activate()
        mock_build.assert_called_once()
        assert plugin._active is True

    await plugin.deactivate()
    assert plugin._active is False


# ── Health check (no service) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_check_not_activated():
    plugin = GmailPlugin()
    result = await plugin.health_check()
    assert result.healthy is False


@pytest.mark.asyncio
async def test_test_not_activated():
    plugin = GmailPlugin()
    result = await plugin.test()
    assert result.success is False
