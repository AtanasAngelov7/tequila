"""Telegram Bot API tools (Sprint 12, §8.6)."""
from __future__ import annotations

from typing import Any

# Tool definitions are lightweight data objects used by the tool registry.
# We define them as plain dicts here so the plugin can operate without the
# tool-registry import at registration time.

TELEGRAM_TOOLS: list[dict[str, Any]] = [
    {
        "name": "telegram_send_message",
        "description": "Send a Telegram message to a chat.",
        "parameters": {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "Telegram chat ID or @username.",
                },
                "text": {
                    "type": "string",
                    "description": "Message text to send (supports Markdown).",
                },
                "parse_mode": {
                    "type": "string",
                    "enum": ["Markdown", "HTML", ""],
                    "description": "Optional parse mode.  Defaults to 'Markdown'.",
                },
            },
            "required": ["chat_id", "text"],
        },
    },
    {
        "name": "telegram_list_chats",
        "description": "List recent Telegram chats/updates (up to 100).",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of updates to return (1–100).",
                },
            },
            "required": [],
        },
    },
]
