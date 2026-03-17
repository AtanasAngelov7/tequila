"""Unit tests for the Google Calendar built-in plugin (Sprint 12)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.plugins.builtin.google_calendar.plugin import GoogleCalendarPlugin
from app.plugins.builtin.google_calendar.tools import GCAL_TOOLS


# ── Metadata ──────────────────────────────────────────────────────────────────


def test_plugin_id():
    assert GoogleCalendarPlugin.plugin_id == "google_calendar"


def test_plugin_type():
    assert GoogleCalendarPlugin.plugin_type == "connector"


def test_auth_spec_is_oauth2():
    plugin = GoogleCalendarPlugin()
    spec = plugin.get_auth_spec()
    assert spec.kind == "oauth2"
    assert spec.oauth2_config.provider == "google"


def test_dependencies():
    plugin = GoogleCalendarPlugin()
    deps = plugin.get_dependencies()
    packages = " ".join(deps.python_packages)
    assert "google-auth" in packages
    assert "google-api-python-client" in packages


# ── Tools ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_tools_returns_five_tools():
    plugin = GoogleCalendarPlugin()
    tools = await plugin.get_tools()
    names = [t["name"] for t in tools]
    assert "calendar_list_events" in names
    assert "calendar_create_event" in names
    assert "calendar_update_event" in names
    assert "calendar_delete_event" in names
    assert "calendar_preview" in names


def test_create_event_required_params():
    tool = next(t for t in GCAL_TOOLS if t["name"] == "calendar_create_event")
    required = tool["parameters"]["required"]
    assert "summary" in required
    assert "start" in required
    assert "end" in required


def test_update_event_required_params():
    tool = next(t for t in GCAL_TOOLS if t["name"] == "calendar_update_event")
    assert "event_id" in tool["parameters"]["required"]


# ── Configure ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_configure_raises_without_credentials():
    plugin = GoogleCalendarPlugin()
    with pytest.raises(ValueError, match="OAuth2"):
        await plugin.configure({}, AsyncMock(return_value=None))


@pytest.mark.asyncio
async def test_configure_succeeds_with_credentials():
    plugin = GoogleCalendarPlugin()
    creds = {"client_id": "cid", "client_secret": "csecret", "refresh_token": "rtoken"}

    async def mock_auth(plugin_id, key):
        return creds.get(key)

    await plugin.configure({}, mock_auth)
    assert plugin._client_id == "cid"
    assert plugin._default_calendar == "primary"


@pytest.mark.asyncio
async def test_configure_custom_calendar_id():
    plugin = GoogleCalendarPlugin()
    creds = {"client_id": "cid", "client_secret": "csecret", "refresh_token": "rtoken"}

    async def mock_auth(plugin_id, key):
        return creds.get(key)

    await plugin.configure({"calendar_id": "work@group.calendar.google.com"}, mock_auth)
    assert plugin._default_calendar == "work@group.calendar.google.com"


# ── Lifecycle ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_activate_builds_service():
    plugin = GoogleCalendarPlugin()
    creds = {"client_id": "cid", "client_secret": "csecret", "refresh_token": "rtoken"}

    async def mock_auth(plugin_id, key):
        return creds.get(key)

    await plugin.configure({}, mock_auth)

    with patch.object(plugin, "_build_service", return_value=None):
        await plugin.activate()
        assert plugin._active is True

    await plugin.deactivate()
    assert plugin._active is False


# ── Health & test (no service) ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_check_not_activated():
    plugin = GoogleCalendarPlugin()
    result = await plugin.health_check()
    assert result.healthy is False


@pytest.mark.asyncio
async def test_test_not_activated():
    plugin = GoogleCalendarPlugin()
    result = await plugin.test()
    assert result.success is False
