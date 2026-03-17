"""Gmail connector plugin (Sprint 12, §8.6).

Uses the Google Gmail REST API v1 via ``google-api-python-client``.
Authentication is Google OAuth2 — tokens are stored encrypted in
``plugin_credentials`` and refreshed automatically.

Required pip packages (declared as dependencies):
- ``google-auth>=2.0``
- ``google-auth-oauthlib>=1.0``
- ``google-api-python-client>=2.0``

OAuth2 credentials to store (via ``/api/plugins/gmail/credentials``):
- ``client_id``      — from Google Cloud Console
- ``client_secret``  — from Google Cloud Console
- ``refresh_token``  — obtained after completing OAuth2 flow
"""
from __future__ import annotations

import asyncio
import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from app.plugins.base import PluginBase
from app.plugins.builtin.gmail.tools import GMAIL_TOOLS
from app.plugins.models import (
    ChannelAdapterSpec,
    OAuth2Config,
    PluginAuth,
    PluginDependencies,
    PluginHealthResult,
    PluginTestResult,
)

logger = logging.getLogger(__name__)

_GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


class GmailPlugin(PluginBase):
    """Google Gmail API connector."""

    plugin_id = "gmail"
    name = "Gmail"
    description = "Read, send and manage emails via the Google Gmail API."
    version = "1.0.0"
    plugin_type = "connector"
    connector_type = "builtin"

    def __init__(self) -> None:
        self._service: Any = None
        self._credentials: Any = None
        self._active = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def configure(self, config: dict[str, Any], auth_store: Any) -> None:
        pid = self.plugin_id
        client_id = await auth_store(pid, "client_id")
        client_secret = await auth_store(pid, "client_secret")
        refresh_token = await auth_store(pid, "refresh_token")

        if not all([client_id, client_secret, refresh_token]):
            raise ValueError(
                "Gmail requires client_id, client_secret and refresh_token credentials. "
                "Complete the OAuth2 flow and store them via the credentials endpoint."
            )
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token

    async def activate(self) -> None:
        await asyncio.to_thread(self._build_service)
        self._active = True

    async def deactivate(self) -> None:
        self._service = None
        self._active = False

    # ── Tools ─────────────────────────────────────────────────────────────────

    async def get_tools(self) -> list[Any]:
        return GMAIL_TOOLS

    async def get_channel_adapter(self) -> ChannelAdapterSpec:
        return ChannelAdapterSpec(
            channel_name="gmail",
            supports_inbound=True,
            supports_outbound=True,
            polling_mode=True,
        )

    def get_auth_spec(self) -> PluginAuth:
        return PluginAuth(
            kind="oauth2",
            oauth2_config=OAuth2Config(
                provider="google",
                scopes=_GMAIL_SCOPES,
                auth_url="https://accounts.google.com/o/oauth2/v2/auth",
                token_url="https://oauth2.googleapis.com/token",
            ),
        )

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "user_email": {
                    "type": "string",
                    "description": "Gmail address to use (defaults to 'me' — the authenticated user).",
                },
            },
        }

    def get_dependencies(self) -> PluginDependencies:
        return PluginDependencies(
            python_packages=[
                "google-auth>=2.0",
                "google-auth-oauthlib>=1.0",
                "google-api-python-client>=2.0",
            ]
        )

    # ── Health & test ─────────────────────────────────────────────────────────

    async def health_check(self) -> PluginHealthResult:
        if not self._service:
            return PluginHealthResult(healthy=False, message="Not configured or not activated.")
        try:
            profile = await asyncio.to_thread(
                lambda: self._service.users().getProfile(userId="me").execute()
            )
            email = profile.get("emailAddress", "unknown")
            return PluginHealthResult(
                healthy=True,
                message=f"Gmail OK — {email}",
                details={"email": email, "messages_total": profile.get("messagesTotal", 0)},
            )
        except Exception as exc:
            return PluginHealthResult(healthy=False, message=str(exc))

    async def test(self) -> PluginTestResult:
        if not self._service:
            return PluginTestResult(success=False, message="Not activated.")
        import time

        start = time.monotonic()
        try:
            await asyncio.to_thread(
                lambda: self._service.users().getProfile(userId="me").execute()
            )
            latency = int((time.monotonic() - start) * 1000)
            return PluginTestResult(success=True, message="Gmail API OK.", latency_ms=latency)
        except Exception as exc:
            return PluginTestResult(success=False, message=str(exc))

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_service(self) -> None:
        """Build the Gmail API service client (blocking, run via to_thread)."""
        from google.oauth2.credentials import Credentials  # type: ignore[import]
        from googleapiclient.discovery import build  # type: ignore[import]

        creds = Credentials(
            token=None,
            refresh_token=self._refresh_token,
            client_id=self._client_id,
            client_secret=self._client_secret,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=_GMAIL_SCOPES,
        )
        self._credentials = creds
        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    def list_messages_sync(
        self,
        query: str = "",
        max_results: int = 20,
        label_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not self._service:
            raise RuntimeError("Plugin not activated.")
        params: dict[str, Any] = {"userId": "me", "maxResults": max_results}
        if query:
            params["q"] = query
        if label_ids:
            params["labelIds"] = label_ids
        result = self._service.users().messages().list(**params).execute()
        messages = result.get("messages", [])
        summaries = []
        for m in messages:
            msg = self._service.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            ).execute()
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            summaries.append({
                "id": m["id"],
                "subject": headers.get("Subject", ""),
                "from": headers.get("From", ""),
                "date": headers.get("Date", ""),
                "snippet": msg.get("snippet", ""),
            })
        return summaries

    def send_email_sync(
        self,
        to: str,
        subject: str,
        body: str,
        html: bool = False,
    ) -> dict[str, Any]:
        if not self._service:
            raise RuntimeError("Plugin not activated.")
        msg = MIMEMultipart("alternative")
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html" if html else "plain"))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        result = self._service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        return result
