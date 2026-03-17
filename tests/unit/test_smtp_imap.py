"""Unit tests for the SMTP/IMAP built-in plugin (Sprint 12)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.plugins.builtin.smtp_imap.plugin import SmtpImapPlugin
from app.plugins.builtin.smtp_imap.tools import SMTP_IMAP_TOOLS


# ── Metadata ──────────────────────────────────────────────────────────────────


def test_plugin_id():
    assert SmtpImapPlugin.plugin_id == "smtp_imap"


def test_plugin_type():
    assert SmtpImapPlugin.plugin_type == "connector"


def test_no_external_dependencies():
    plugin = SmtpImapPlugin()
    deps = plugin.get_dependencies()
    assert deps.python_packages == []


# ── Tools ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_tools_returns_four_tools():
    plugin = SmtpImapPlugin()
    tools = await plugin.get_tools()
    names = [t["name"] for t in tools]
    assert "email_list_messages" in names
    assert "email_get_message" in names
    assert "email_send" in names
    assert "email_mark_read" in names


def test_email_send_required_params():
    tool = next(t for t in SMTP_IMAP_TOOLS if t["name"] == "email_send")
    required = tool["parameters"]["required"]
    assert "to" in required
    assert "subject" in required
    assert "body" in required


# ── Configure ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_configure_raises_if_no_smtp_host():
    plugin = SmtpImapPlugin()
    with pytest.raises(ValueError, match="smtp_host"):
        await plugin.configure({}, AsyncMock(return_value=None))


@pytest.mark.asyncio
async def test_configure_from_config_dict():
    plugin = SmtpImapPlugin()
    config = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "user@example.com",
        "imap_host": "imap.example.com",
    }

    async def mock_auth(plugin_id, key):
        return {
            "smtp_password": "password",
            "imap_password": "password",
        }.get(key)

    await plugin.configure(config, mock_auth)
    assert plugin._smtp_config["host"] == "smtp.example.com"
    assert plugin._smtp_config["port"] == 587


@pytest.mark.asyncio
async def test_activate_and_deactivate():
    plugin = SmtpImapPlugin()
    config = {"smtp_host": "smtp.example.com"}

    await plugin.configure(config, AsyncMock(return_value=None))
    await plugin.activate()
    assert plugin._active is True
    await plugin.deactivate()
    assert plugin._active is False


# ── Health & test ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_check_not_configured():
    plugin = SmtpImapPlugin()
    result = await plugin.health_check()
    assert result.healthy is False


@pytest.mark.asyncio
async def test_health_check_smtp_ok():
    plugin = SmtpImapPlugin()
    plugin._smtp_config = {"host": "smtp.example.com", "port": 587, "username": "u", "password": "p", "use_tls": False}

    with patch.object(plugin, "_smtp_noop", return_value=None):
        result = await plugin.health_check()
        assert result.healthy is True


@pytest.mark.asyncio
async def test_health_check_smtp_error():
    plugin = SmtpImapPlugin()
    plugin._smtp_config = {"host": "bad.example.com", "port": 587, "username": "", "password": "", "use_tls": False}

    with patch.object(plugin, "_smtp_noop", side_effect=ConnectionRefusedError("refused")):
        result = await plugin.health_check()
        assert result.healthy is False


@pytest.mark.asyncio
async def test_test_not_configured():
    plugin = SmtpImapPlugin()
    result = await plugin.test()
    assert result.success is False


@pytest.mark.asyncio
async def test_test_smtp_ok():
    plugin = SmtpImapPlugin()
    plugin._smtp_config = {"host": "smtp.example.com", "port": 587, "username": "", "password": "", "use_tls": False}

    with patch.object(plugin, "_smtp_noop", return_value=None):
        result = await plugin.test()
        assert result.success is True
        assert result.latency_ms is not None
