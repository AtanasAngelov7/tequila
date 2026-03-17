"""Gmail API tool definitions (Sprint 12, §8.6)."""
from __future__ import annotations

from typing import Any

GMAIL_TOOLS: list[dict[str, Any]] = [
    {
        "name": "gmail_list_messages",
        "description": "List Gmail messages matching an optional query.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail search query, e.g. 'is:unread from:boss@example.com'.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of messages to return (1–100). Defaults to 20.",
                },
                "label_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of Gmail label IDs to filter by, e.g. ['INBOX', 'UNREAD'].",
                },
            },
            "required": [],
        },
    },
    {
        "name": "gmail_get_message",
        "description": "Fetch the full content of a Gmail message by its ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "Gmail message ID.",
                },
            },
            "required": ["message_id"],
        },
    },
    {
        "name": "gmail_send",
        "description": "Send an email via Gmail.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address.",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line.",
                },
                "body": {
                    "type": "string",
                    "description": "Email body (plain text or HTML).",
                },
                "html": {
                    "type": "boolean",
                    "description": "Send body as HTML. Defaults to false.",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "gmail_mark_read",
        "description": "Mark a Gmail message as read by removing the UNREAD label.",
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "Gmail message ID.",
                },
            },
            "required": ["message_id"],
        },
    },
]
