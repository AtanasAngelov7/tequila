"""Slack Bot connector plugin (Sprint 16 §29.2 D2).

Uses the Slack Web API via httpx — no Slack SDK required.
Required credentials: ``bot_token`` (xoxb-... token with chat:write scope).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.plugins.base import PluginBase
from app.plugins.builtin.slack.tools import SLACK_TOOLS
from app.plugins.models import (
    ChannelAdapterSpec,
    PluginAuth,
    PluginDependencies,
    PluginHealthResult,
    PluginTestResult,
)

logger = logging.getLogger(__name__)

_SLACK_API = "https://slack.com/api"


class SlackPlugin(PluginBase):
    """Slack Bot API connector."""

    plugin_id = "slack"
    name = "Slack"
    description = "Send messages, search conversations, and react to messages in Slack."
    version = "1.0.0"
    plugin_type = "connector"
    connector_type = "builtin"

    def __init__(self) -> None:
        self._token: str | None = None
        self._active = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def configure(self, config: dict[str, Any], auth_store: Any) -> None:
        token = await auth_store("slack", "bot_token")
        if not token:
            raise ValueError(
                "Slack bot_token not configured. Save it via the credentials endpoint."
            )
        self._token = token

    async def activate(self) -> None:
        if not self._token:
            raise RuntimeError("Plugin not configured. Call configure() first.")
        self._active = True
        logger.info("SlackPlugin activated.")

    async def deactivate(self) -> None:
        self._active = False
        logger.info("SlackPlugin deactivated.")

    # ── Tools ─────────────────────────────────────────────────────────────────

    async def get_tools(self) -> list[Any]:
        return SLACK_TOOLS

    # ── Channel adapter ───────────────────────────────────────────────────────

    async def get_channel_adapter(self) -> ChannelAdapterSpec:
        return ChannelAdapterSpec(
            channel_name="slack",
            supports_inbound=True,
            supports_outbound=True,
            polling_mode=False,  # Slack uses event subscriptions (webhooks)
        )

    # ── Auth & schema ─────────────────────────────────────────────────────────

    def get_auth_spec(self) -> PluginAuth:
        return PluginAuth(kind="token", key_label="Bot Token (xoxb-...)")

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "default_channel": {
                    "type": "string",
                    "description": "Default channel to send messages to.",
                },
                "signing_secret": {
                    "type": "string",
                    "description": "Slack signing secret for webhook verification.",
                },
            },
        }

    def get_dependencies(self) -> PluginDependencies:
        return PluginDependencies(python_packages=["httpx>=0.25"])

    # ── Health & test ─────────────────────────────────────────────────────────

    async def health_check(self) -> PluginHealthResult:
        if not self._token:
            return PluginHealthResult(healthy=False, message="Not configured.")
        try:
            data = await self._api_call("auth.test")
            team = data.get("team", "unknown")
            user = data.get("user", "unknown")
            return PluginHealthResult(
                healthy=True,
                message=f"Connected as @{user} in workspace '{team}'",
                details={"team": team, "user": user},
            )
        except Exception as exc:  # noqa: BLE001
            return PluginHealthResult(healthy=False, message=str(exc))

    async def test(self) -> PluginTestResult:
        if not self._token:
            return PluginTestResult(success=False, message="Not configured.")
        import time

        start = time.monotonic()
        try:
            data = await self._api_call("auth.test")
            latency = int((time.monotonic() - start) * 1000)
            user = data.get("user", "unknown")
            return PluginTestResult(
                success=True,
                message=f"Slack API OK — @{user}",
                latency_ms=latency,
            )
        except Exception as exc:  # noqa: BLE001
            return PluginTestResult(success=False, message=str(exc))

    # ── API helper ────────────────────────────────────────────────────────────

    async def _api_call(
        self, method: str, *, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        import httpx

        url = f"{_SLACK_API}/{method}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json=json or {})
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        if not data.get("ok"):
            error = data.get("error", "unknown_error")
            raise RuntimeError(f"Slack API error: {error}")
        return data
