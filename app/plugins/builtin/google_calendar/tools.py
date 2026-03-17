"""Google Calendar API tool definitions (Sprint 12, §8.6)."""
from __future__ import annotations

from typing import Any

GCAL_TOOLS: list[dict[str, Any]] = [
    {
        "name": "calendar_list_events",
        "description": "List upcoming Google Calendar events.",
        "parameters": {
            "type": "object",
            "properties": {
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID. Defaults to 'primary'.",
                },
                "time_min": {
                    "type": "string",
                    "description": "Start of time range (ISO 8601). Defaults to now.",
                },
                "time_max": {
                    "type": "string",
                    "description": "End of time range (ISO 8601). Defaults to 7 days from now.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum events to return (1–250). Defaults to 10.",
                },
                "query": {
                    "type": "string",
                    "description": "Free-text search filter.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "calendar_create_event",
        "description": "Create a new event on Google Calendar.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Event title.",
                },
                "start": {
                    "type": "string",
                    "description": "Event start date/time (ISO 8601), e.g. '2024-12-25T10:00:00+00:00'.",
                },
                "end": {
                    "type": "string",
                    "description": "Event end date/time (ISO 8601).",
                },
                "description": {
                    "type": "string",
                    "description": "Optional event description.",
                },
                "location": {
                    "type": "string",
                    "description": "Optional event location.",
                },
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of attendee email addresses.",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID. Defaults to 'primary'.",
                },
            },
            "required": ["summary", "start", "end"],
        },
    },
    {
        "name": "calendar_update_event",
        "description": "Update an existing Google Calendar event.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "Google Calendar event ID.",
                },
                "summary": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "description": {"type": "string"},
                "location": {"type": "string"},
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID. Defaults to 'primary'.",
                },
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "calendar_delete_event",
        "description": "Delete a Google Calendar event.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "Google Calendar event ID.",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID. Defaults to 'primary'.",
                },
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "calendar_preview",
        "description": "Get a plain-text preview of the calendar for a time range.",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days ahead to preview. Defaults to 7.",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID. Defaults to 'primary'.",
                },
            },
            "required": [],
        },
    },
]
