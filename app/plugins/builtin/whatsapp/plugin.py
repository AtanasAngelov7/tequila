"""WhatsApp Business connector plugin (Sprint 16 §29.4 D4).

Uses the WhatsApp Business Cloud API (Meta) via httpx.
Required credentials:
  - ``phone_number_id``  — WhatsApp Business phone number ID
  - ``access_token``     — Meta Graph API access token
"""
from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any

from app.plugins.base import PluginBase
from app.plugins.builtin.whatsapp.tools import WHATSAPP_TOOLS
from app.plugins.models import (
    ChannelAdapterSpec,
    PluginAuth,
    PluginDependencies,
    PluginHealthResult,
    PluginTestResult,
)

logger = logging.getLogger(__name__)

_WA_API = "https://graph.facebook.com/v19.0"


class WhatsAppPlugin(PluginBase):
    """WhatsApp Business Cloud API connector."""

    plugin_id = "whatsapp"
    name = "WhatsApp"
    description = "Send text messages and media via the WhatsApp Business Cloud API."
    version = "1.0.0"
    plugin_type = "connector"
    connector_type = "builtin"

    def __init__(self) -> None:
        self._phone_number_id: str | None = None
        self._access_token: str | None = None
        self._active = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def configure(self, config: dict[str, Any], auth_store: Any) -> None:
        self._phone_number_id = await auth_store("whatsapp", "phone_number_id")
        self._access_token = await auth_store("whatsapp", "access_token")
        if not self._phone_number_id or not self._access_token:
            raise ValueError(
                "WhatsApp requires phone_number_id and access_token credentials."
            )

    async def activate(self) -> None:
        if not self._phone_number_id or not self._access_token:
            raise RuntimeError("Plugin not configured. Call configure() first.")
        self._active = True
        logger.info("WhatsAppPlugin activated.")

    async def deactivate(self) -> None:
        self._active = False
        logger.info("WhatsAppPlugin deactivated.")

    # ── Tools ─────────────────────────────────────────────────────────────────

    async def get_tools(self) -> list[Any]:
        return WHATSAPP_TOOLS

    # ── Channel adapter ───────────────────────────────────────────────────────

    async def get_channel_adapter(self) -> ChannelAdapterSpec:
        return ChannelAdapterSpec(
            channel_name="whatsapp",
            supports_inbound=True,
            supports_outbound=True,
            polling_mode=False,  # Inbound via Meta webhooks
        )

    # ── Auth & schema ─────────────────────────────────────────────────────────

    def get_auth_spec(self) -> PluginAuth:
        return PluginAuth(kind="api_key", key_label="Meta Graph API Access Token")

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "verify_token": {
                    "type": "string",
                    "description": "Webhook verify token for Meta webhook subscription.",
                },
            },
        }

    def get_dependencies(self) -> PluginDependencies:
        return PluginDependencies(python_packages=["httpx>=0.25"])

    # ── Health & test ─────────────────────────────────────────────────────────

    async def health_check(self) -> PluginHealthResult:
        if not self._phone_number_id or not self._access_token:
            return PluginHealthResult(healthy=False, message="Not configured.")
        try:
            data = await self._api_get(f"/{self._phone_number_id}")
            display = data.get("display_phone_number", self._phone_number_id)
            return PluginHealthResult(
                healthy=True,
                message=f"Connected — number: {display}",
                details={"phone_number": display},
            )
        except Exception as exc:  # noqa: BLE001
            return PluginHealthResult(healthy=False, message=str(exc))

    async def test(self) -> PluginTestResult:
        if not self._phone_number_id or not self._access_token:
            return PluginTestResult(success=False, message="Not configured.")
        import time

        start = time.monotonic()
        try:
            data = await self._api_get(f"/{self._phone_number_id}")
            latency = int((time.monotonic() - start) * 1000)
            display = data.get("display_phone_number", "unknown")
            return PluginTestResult(
                success=True,
                message=f"WhatsApp API OK — {display}",
                latency_ms=latency,
            )
        except Exception as exc:  # noqa: BLE001
            return PluginTestResult(success=False, message=str(exc))

    # ── API helpers ───────────────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    async def _api_get(self, path: str) -> dict[str, Any]:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_WA_API}{path}", headers=self._auth_headers()
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]

    async def _send_message_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        import httpx

        url = f"{_WA_API}/{self._phone_number_id}/messages"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url, headers=self._auth_headers(), json=payload
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]

    # ── Public send helpers ───────────────────────────────────────────────────

    async def send_text(self, number: str, text: str) -> dict[str, Any]:
        return await self._send_message_payload(
            {
                "messaging_product": "whatsapp",
                "to": number.lstrip("+"),
                "type": "text",
                "text": {"body": text},
            }
        )

    async def send_media(
        self, number: str, file_path: str, caption: str | None = None
    ) -> dict[str, Any]:
        path = Path(file_path)
        mime, _ = mimetypes.guess_type(str(path))
        mime = mime or "application/octet-stream"

        # Determine media type category.
        if mime.startswith("image/"):
            media_type = "image"
        elif mime.startswith("video/"):
            media_type = "video"
        elif mime.startswith("audio/"):
            media_type = "audio"
        else:
            media_type = "document"

        import httpx

        # Upload media first to get a media_id.
        upload_url = f"{_WA_API}/{self._phone_number_id}/media"
        with path.open("rb") as fh:
            async with httpx.AsyncClient(timeout=60) as client:
                upload_resp = await client.post(
                    upload_url,
                    headers=self._auth_headers(),
                    data={"messaging_product": "whatsapp"},
                    files={"file": (path.name, fh, mime)},
                )
                upload_resp.raise_for_status()
                media_id = upload_resp.json()["id"]

        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": number.lstrip("+"),
            "type": media_type,
            media_type: {"id": media_id},
        }
        if caption:
            payload[media_type]["caption"] = caption

        return await self._send_message_payload(payload)
