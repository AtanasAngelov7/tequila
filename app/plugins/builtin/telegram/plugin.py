"""Telegram Bot connector plugin (Sprint 12, §8.6).

Uses the Telegram Bot HTTP API directly (via httpx) — no third-party
Telegram SDK required.  Requires the ``httpx`` package (already a project
dependency via FastAPI).

Credential required: ``bot_token``
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiosqlite

from app.plugins.base import PluginBase
from app.plugins.builtin.telegram.tools import TELEGRAM_TOOLS
from app.plugins.models import (
    ChannelAdapterSpec,
    PluginAuth,
    PluginDependencies,
    PluginHealthResult,
    PluginTestResult,
)

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


class TelegramPlugin(PluginBase):
    """Telegram Bot API connector."""

    plugin_id = "telegram"
    name = "Telegram"
    description = "Send and receive Telegram messages via the Bot API."
    version = "1.0.0"
    plugin_type = "connector"
    connector_type = "builtin"

    def __init__(self) -> None:
        self._token: str | None = None
        self._polling_task: asyncio.Task[None] | None = None
        self._offset: int = 0
        self._active = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def configure(self, config: dict[str, Any], auth_store: Any) -> None:
        token = await auth_store("telegram", "bot_token")
        if not token:
            raise ValueError("Telegram bot_token not configured. Save it via the credentials endpoint.")
        self._token = token

    async def activate(self) -> None:
        if not self._token:
            raise RuntimeError("Plugin not configured. Call configure() first.")
        self._active = True
        self._polling_task = asyncio.create_task(
            self._poll_loop(), name="telegram-poll-loop"
        )
        logger.info("TelegramPlugin activated — long polling started.")

    async def deactivate(self) -> None:
        self._active = False
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
        logger.info("TelegramPlugin deactivated.")

    # ── Tools ─────────────────────────────────────────────────────────────────

    async def get_tools(self) -> list[Any]:
        return TELEGRAM_TOOLS

    # ── Channel adapter ───────────────────────────────────────────────────────

    async def get_channel_adapter(self) -> ChannelAdapterSpec:
        return ChannelAdapterSpec(
            channel_name="telegram",
            supports_inbound=True,
            supports_outbound=True,
            polling_mode=True,
        )

    # ── Auth & schema ─────────────────────────────────────────────────────────

    def get_auth_spec(self) -> PluginAuth:
        return PluginAuth(kind="token", key_label="Bot Token")

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "allowed_chat_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional whitelist of chat IDs that can interact.",
                },
            },
        }

    def get_dependencies(self) -> PluginDependencies:
        # httpx is already a transitive dependency of FastAPI
        return PluginDependencies(python_packages=["httpx>=0.25"])

    # ── Health & test ─────────────────────────────────────────────────────────

    async def health_check(self) -> PluginHealthResult:
        if not self._token:
            return PluginHealthResult(healthy=False, message="Not configured.")
        try:
            info = await self._api_call("getMe")
            username = info.get("result", {}).get("username", "unknown")
            return PluginHealthResult(
                healthy=True,
                message=f"Connected as @{username}",
                details={"username": username},
            )
        except Exception as exc:
            return PluginHealthResult(healthy=False, message=str(exc))

    async def test(self) -> PluginTestResult:
        if not self._token:
            return PluginTestResult(success=False, message="Not configured.")
        import time

        start = time.monotonic()
        try:
            info = await self._api_call("getMe")
            latency = int((time.monotonic() - start) * 1000)
            username = info.get("result", {}).get("username", "unknown")
            return PluginTestResult(
                success=True,
                message=f"Bot API OK — @{username}",
                latency_ms=latency,
            )
        except Exception as exc:
            return PluginTestResult(success=False, message=str(exc))

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _api_call(self, method: str, **params: Any) -> dict[str, Any]:
        import httpx

        url = _TELEGRAM_API.format(token=self._token, method=method)
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=params or None)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data.get('description', 'unknown')}")
        return data

    async def _poll_loop(self) -> None:
        """Long-poll the Telegram Bot API for incoming updates."""
        while self._active:
            try:
                data = await self._api_call(
                    "getUpdates",
                    offset=self._offset,
                    timeout=30,
                    allowed_updates=["message"],
                )
                updates = data.get("result", [])
                for update in updates:
                    self._offset = update["update_id"] + 1
                    await self._handle_update(update)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("Telegram poll error: %s", exc)
                await asyncio.sleep(5)

    async def _handle_update(self, update: dict[str, Any]) -> None:
        """Process a single incoming Telegram update."""
        message = update.get("message") or update.get("channel_post")
        if not message:
            return
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "")
        logger.debug("Telegram message from chat %s: %r", chat_id, text[:80])
        # TODO: forward to gateway session routing in a future sprint
