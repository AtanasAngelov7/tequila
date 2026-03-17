"""Google Calendar connector plugin (Sprint 12, §8.6).

Shares the same Google OAuth2 credential flow as the Gmail plugin.
Required credentials (stored via ``/api/plugins/google_calendar/credentials``):
- ``client_id``, ``client_secret``, ``refresh_token``

Required pip packages:
- ``google-auth>=2.0``
- ``google-api-python-client>=2.0``
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.plugins.base import PluginBase
from app.plugins.builtin.google_calendar.tools import GCAL_TOOLS
from app.plugins.models import (
    OAuth2Config,
    PluginAuth,
    PluginDependencies,
    PluginHealthResult,
    PluginTestResult,
)

logger = logging.getLogger(__name__)

_GCAL_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]


class GoogleCalendarPlugin(PluginBase):
    """Google Calendar API connector."""

    plugin_id = "google_calendar"
    name = "Google Calendar"
    description = "Create, read and manage events via the Google Calendar API."
    version = "1.0.0"
    plugin_type = "connector"
    connector_type = "builtin"

    def __init__(self) -> None:
        self._service: Any = None
        self._active = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def configure(self, config: dict[str, Any], auth_store: Any) -> None:
        pid = self.plugin_id
        client_id = await auth_store(pid, "client_id")
        client_secret = await auth_store(pid, "client_secret")
        refresh_token = await auth_store(pid, "refresh_token")
        if not all([client_id, client_secret, refresh_token]):
            raise ValueError(
                "Google Calendar requires client_id, client_secret and refresh_token. "
                "Complete the OAuth2 flow first."
            )
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._default_calendar = config.get("calendar_id", "primary")

    async def activate(self) -> None:
        await asyncio.to_thread(self._build_service)
        self._active = True

    async def deactivate(self) -> None:
        self._service = None
        self._active = False

    # ── Tools ─────────────────────────────────────────────────────────────────

    async def get_tools(self) -> list[Any]:
        return GCAL_TOOLS

    def get_auth_spec(self) -> PluginAuth:
        return PluginAuth(
            kind="oauth2",
            oauth2_config=OAuth2Config(
                provider="google",
                scopes=_GCAL_SCOPES,
                auth_url="https://accounts.google.com/o/oauth2/v2/auth",
                token_url="https://oauth2.googleapis.com/token",
            ),
        )

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "calendar_id": {
                    "type": "string",
                    "description": "Default calendar ID (defaults to 'primary').",
                },
                "timezone": {
                    "type": "string",
                    "description": "Timezone for event creation, e.g. 'Europe/London'.",
                },
            },
        }

    def get_dependencies(self) -> PluginDependencies:
        return PluginDependencies(
            python_packages=[
                "google-auth>=2.0",
                "google-api-python-client>=2.0",
            ]
        )

    # ── Health & test ─────────────────────────────────────────────────────────

    async def health_check(self) -> PluginHealthResult:
        if not self._service:
            return PluginHealthResult(healthy=False, message="Not activated.")
        try:
            await asyncio.to_thread(
                lambda: self._service.calendarList().get(
                    calendarId=self._default_calendar
                ).execute()
            )
            return PluginHealthResult(healthy=True, message="Google Calendar API OK.")
        except Exception as exc:
            return PluginHealthResult(healthy=False, message=str(exc))

    async def test(self) -> PluginTestResult:
        import time

        if not self._service:
            return PluginTestResult(success=False, message="Not activated.")
        start = time.monotonic()
        try:
            await asyncio.to_thread(
                lambda: self._service.calendarList().list(maxResults=1).execute()
            )
            latency = int((time.monotonic() - start) * 1000)
            return PluginTestResult(success=True, message="Google Calendar API OK.", latency_ms=latency)
        except Exception as exc:
            return PluginTestResult(success=False, message=str(exc))

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_service(self) -> None:
        from google.oauth2.credentials import Credentials  # type: ignore[import]
        from googleapiclient.discovery import build  # type: ignore[import]

        creds = Credentials(
            token=None,
            refresh_token=self._refresh_token,
            client_id=self._client_id,
            client_secret=self._client_secret,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=_GCAL_SCOPES,
        )
        self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    def list_events_sync(
        self,
        calendar_id: str | None = None,
        time_min: str | None = None,
        time_max: str | None = None,
        max_results: int = 10,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self._service:
            raise RuntimeError("Plugin not activated.")
        now = datetime.now(UTC)
        params: dict[str, Any] = {
            "calendarId": calendar_id or self._default_calendar,
            "timeMin": time_min or now.isoformat(),
            "timeMax": time_max or (now + timedelta(days=7)).isoformat(),
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if query:
            params["q"] = query
        result = self._service.events().list(**params).execute()
        events = result.get("items", [])
        return [
            {
                "id": e.get("id"),
                "summary": e.get("summary", ""),
                "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
                "end": e.get("end", {}).get("dateTime") or e.get("end", {}).get("date"),
                "location": e.get("location", ""),
                "description": e.get("description", ""),
            }
            for e in events
        ]

    def create_event_sync(
        self,
        summary: str,
        start: str,
        end: str,
        description: str = "",
        location: str = "",
        attendees: list[str] | None = None,
        calendar_id: str | None = None,
    ) -> dict[str, Any]:
        if not self._service:
            raise RuntimeError("Plugin not activated.")
        body: dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        if attendees:
            body["attendees"] = [{"email": e} for e in attendees]

        result = self._service.events().insert(
            calendarId=calendar_id or self._default_calendar,
            body=body,
        ).execute()
        return result
