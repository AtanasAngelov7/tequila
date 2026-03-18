"""Discord Bot connector plugin (Sprint 16 §29.3 D3).

Uses the Discord REST API directly via httpx — no discord.py SDK required.
Required credentials: ``bot_token`` (Discord bot token).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.plugins.base import PluginBase
from app.plugins.builtin.discord.tools import DISCORD_TOOLS
from app.plugins.models import (
    ChannelAdapterSpec,
    PluginAuth,
    PluginDependencies,
    PluginHealthResult,
    PluginTestResult,
)

logger = logging.getLogger(__name__)

_DISCORD_API = "https://discord.com/api/v10"


class DiscordPlugin(PluginBase):
    """Discord Bot API connector (REST-based, no gateway websocket)."""

    plugin_id = "discord"
    name = "Discord"
    description = "Send messages, react, and read channels in Discord servers."
    version = "1.0.0"
    plugin_type = "connector"
    connector_type = "builtin"

    def __init__(self) -> None:
        self._token: str | None = None
        self._active = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def configure(self, config: dict[str, Any], auth_store: Any) -> None:
        token = await auth_store("discord", "bot_token")
        if not token:
            raise ValueError(
                "Discord bot_token not configured. Save it via the credentials endpoint."
            )
        self._token = token

    async def activate(self) -> None:
        if not self._token:
            raise RuntimeError("Plugin not configured. Call configure() first.")
        self._active = True
        logger.info("DiscordPlugin activated.")

    async def deactivate(self) -> None:
        self._active = False
        logger.info("DiscordPlugin deactivated.")

    # ── Tools ─────────────────────────────────────────────────────────────────

    async def get_tools(self) -> list[Any]:
        return DISCORD_TOOLS

    # ── Channel adapter ───────────────────────────────────────────────────────

    async def get_channel_adapter(self) -> ChannelAdapterSpec:
        return ChannelAdapterSpec(
            channel_name="discord",
            supports_inbound=True,
            supports_outbound=True,
            polling_mode=False,  # Discord uses Gateway websocket or webhooks
        )

    # ── Auth & schema ─────────────────────────────────────────────────────────

    def get_auth_spec(self) -> PluginAuth:
        return PluginAuth(kind="token", key_label="Bot Token")

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "guild_id": {
                    "type": "string",
                    "description": "Default Discord server (guild) ID.",
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
            data = await self._api_get("/users/@me")
            username = data.get("username", "unknown")
            discriminator = data.get("discriminator", "0000")
            return PluginHealthResult(
                healthy=True,
                message=f"Connected as {username}#{discriminator}",
                details={"username": username},
            )
        except Exception as exc:  # noqa: BLE001
            return PluginHealthResult(healthy=False, message=str(exc))

    async def test(self) -> PluginTestResult:
        if not self._token:
            return PluginTestResult(success=False, message="Not configured.")
        import time

        start = time.monotonic()
        try:
            data = await self._api_get("/users/@me")
            latency = int((time.monotonic() - start) * 1000)
            username = data.get("username", "unknown")
            return PluginTestResult(
                success=True,
                message=f"Discord API OK — {username}",
                latency_ms=latency,
            )
        except Exception as exc:  # noqa: BLE001
            return PluginTestResult(success=False, message=str(exc))

    # ── API helpers ───────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bot {self._token}",
            "Content-Type": "application/json",
            "User-Agent": "Tequila/1.0 (https://github.com/tequila-ai/tequila)",
        }

    async def _api_get(self, path: str) -> dict[str, Any]:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_DISCORD_API}{path}", headers=self._headers()
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]

    async def _api_post(
        self, path: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_DISCORD_API}{path}", headers=self._headers(), json=payload
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
