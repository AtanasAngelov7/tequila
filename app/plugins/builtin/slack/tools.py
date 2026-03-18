"""Tool definitions for the Slack connector plugin (Sprint 16 §29.2 D2)."""
from __future__ import annotations

from typing import Any

SLACK_TOOLS: list[dict[str, Any]] = [
    {
        "name": "slack_send",
        "description": "Send a message to a Slack channel or user.",
        "parameters": {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "Channel ID, channel name (e.g. #general), or user ID.",
                },
                "text": {
                    "type": "string",
                    "description": "Message text (supports Slack markdown).",
                },
                "thread_ts": {
                    "type": "string",
                    "description": "Thread timestamp to reply in a thread (optional).",
                },
            },
            "required": ["channel", "text"],
        },
    },
    {
        "name": "slack_search",
        "description": "Search messages in Slack using Slack's full-text search API.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string (supports Slack search modifiers).",
                },
                "count": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 10).",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "slack_react",
        "description": "Add an emoji reaction to a Slack message.",
        "parameters": {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "Channel ID containing the message.",
                },
                "message_ts": {
                    "type": "string",
                    "description": "Timestamp of the message to react to.",
                },
                "emoji": {
                    "type": "string",
                    "description": "Emoji name without colons (e.g. thumbsup, wave).",
                },
            },
            "required": ["channel", "message_ts", "emoji"],
        },
    },
]
