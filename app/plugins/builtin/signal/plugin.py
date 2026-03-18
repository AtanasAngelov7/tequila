"""Signal CLI bridge connector plugin (Sprint 16 §29.5 D5).

Communicates with a locally running ``signal-cli`` daemon in JSON-RPC mode.
Required credentials:
  - ``account``     — registered Signal phone number (E.164 format)
  - ``socket_path`` — path to the signal-cli JSON-RPC unix socket (optional)
                      defaults to /var/run/signal-cli/socket
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.plugins.base import PluginBase
from app.plugins.builtin.signal.tools import SIGNAL_TOOLS
from app.plugins.models import (
    ChannelAdapterSpec,
    PluginAuth,
    PluginDependencies,
    PluginHealthResult,
    PluginTestResult,
)

logger = logging.getLogger(__name__)

_DEFAULT_SOCKET = "/var/run/signal-cli/socket"
_DEFAULT_HTTP_URL = "http://localhost:8080"


class SignalPlugin(PluginBase):
    """Signal CLI bridge connector (JSON-RPC daemon mode)."""

    plugin_id = "signal"
    name = "Signal"
    description = "Send messages and files via a locally running signal-cli daemon."
    version = "1.0.0"
    plugin_type = "connector"
    connector_type = "builtin"

    def __init__(self) -> None:
        self._account: str | None = None
        self._http_url: str = _DEFAULT_HTTP_URL
        self._active = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def configure(self, config: dict[str, Any], auth_store: Any) -> None:
        self._account = await auth_store("signal", "account")
        http_url = await auth_store("signal", "http_url")
        if http_url:
            self._http_url = http_url
        if not self._account:
            raise ValueError(
                "Signal plugin requires the 'account' credential "
                "(the registered phone number in E.164 format)."
            )

    async def activate(self) -> None:
        if not self._account:
            raise RuntimeError("Plugin not configured. Call configure() first.")
        self._active = True
        logger.info("SignalPlugin activated — account: %s", self._account)

    async def deactivate(self) -> None:
        self._active = False
        logger.info("SignalPlugin deactivated.")

    # ── Tools ─────────────────────────────────────────────────────────────────

    async def get_tools(self) -> list[Any]:
        return SIGNAL_TOOLS

    # ── Channel adapter ───────────────────────────────────────────────────────

    async def get_channel_adapter(self) -> ChannelAdapterSpec:
        return ChannelAdapterSpec(
            channel_name="signal",
            supports_inbound=True,
            supports_outbound=True,
            polling_mode=False,
        )

    # ── Auth & schema ─────────────────────────────────────────────────────────

    def get_auth_spec(self) -> PluginAuth:
        return PluginAuth(kind="token", key_label="Account (phone number in E.164)")

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "http_url": {
                    "type": "string",
                    "description": (
                        "Base URL of the signal-cli JSON-RPC HTTP server "
                        f"(default: {_DEFAULT_HTTP_URL})."
                    ),
                    "default": _DEFAULT_HTTP_URL,
                },
            },
        }

    def get_dependencies(self) -> PluginDependencies:
        return PluginDependencies(
            python_packages=["httpx>=0.25"],
            system_packages=["signal-cli>=0.12"],
        )

    # ── Health & test ─────────────────────────────────────────────────────────

    async def health_check(self) -> PluginHealthResult:
        if not self._account:
            return PluginHealthResult(healthy=False, message="Not configured.")
        try:
            result = await self._rpc_call("listAccounts", {})
            accounts = result.get("result", [])
            if any(acc.get("number") == self._account for acc in accounts):
                return PluginHealthResult(
                    healthy=True,
                    message=f"signal-cli daemon reachable — account: {self._account}",
                )
            return PluginHealthResult(
                healthy=False,
                message=f"Account {self._account} not found in signal-cli.",
            )
        except Exception as exc:  # noqa: BLE001
            return PluginHealthResult(healthy=False, message=str(exc))

    async def test(self) -> PluginTestResult:
        if not self._account:
            return PluginTestResult(success=False, message="Not configured.")
        import time

        start = time.monotonic()
        try:
            await self._rpc_call("listAccounts", {})
            latency = int((time.monotonic() - start) * 1000)
            return PluginTestResult(
                success=True,
                message="signal-cli daemon reachable",
                latency_ms=latency,
            )
        except Exception as exc:  # noqa: BLE001
            return PluginTestResult(success=False, message=str(exc))

    # ── JSON-RPC helper ───────────────────────────────────────────────────────

    async def _rpc_call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        import httpx

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._http_url}/api/v1/rpc",
                json=payload,
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()

        if "error" in data:
            raise RuntimeError(
                f"signal-cli RPC error: {data['error'].get('message', 'unknown')}"
            )
        return data

    # ── Public send helpers ───────────────────────────────────────────────────

    async def send_message(self, recipient: str, message: str) -> dict[str, Any]:
        return await self._rpc_call(
            "send",
            {"account": self._account, "recipient": [recipient], "message": message},
        )

    async def send_file(
        self, recipient: str, file_path: str, caption: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "account": self._account,
            "recipient": [recipient],
            "attachments": [file_path],
        }
        if caption:
            params["message"] = caption
        return await self._rpc_call("send", params)
