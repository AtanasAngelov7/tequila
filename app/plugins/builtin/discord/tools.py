"""Tool definitions for the Discord connector plugin (Sprint 16 §29.3 D3)."""
from __future__ import annotations

from typing import Any

DISCORD_TOOLS: list[dict[str, Any]] = [
    {
        "name": "discord_send",
        "description": "Send a message to a Discord channel.",
        "parameters": {
            "type": "object",
            "properties": {
                "channel_id": {
                    "type": "string",
                    "description": "Discord channel snowflake ID.",
                },
                "text": {
                    "type": "string",
                    "description": "Message content (supports Discord markdown).",
                },
            },
            "required": ["channel_id", "text"],
        },
    },
    {
        "name": "discord_react",
        "description": "Add an emoji reaction to a Discord message.",
        "parameters": {
            "type": "object",
            "properties": {
                "channel_id": {
                    "type": "string",
                    "description": "Discord channel snowflake ID.",
                },
                "message_id": {
                    "type": "string",
                    "description": "Discord message snowflake ID.",
                },
                "emoji": {
                    "type": "string",
                    "description": "Unicode emoji or custom emoji in format name:id.",
                },
            },
            "required": ["channel_id", "message_id", "emoji"],
        },
    },
    {
        "name": "discord_get_messages",
        "description": "Retrieve recent messages from a Discord channel.",
        "parameters": {
            "type": "object",
            "properties": {
                "channel_id": {
                    "type": "string",
                    "description": "Discord channel snowflake ID.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of messages to retrieve (1–100, default: 10).",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100,
                },
                "before": {
                    "type": "string",
                    "description": "Retrieve messages before this message ID (optional).",
                },
            },
            "required": ["channel_id"],
        },
    },
]
