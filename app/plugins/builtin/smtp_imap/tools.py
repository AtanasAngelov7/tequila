"""SMTP/IMAP email tool definitions (Sprint 12, §8.6)."""
from __future__ import annotations

from typing import Any

SMTP_IMAP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "email_list_messages",
        "description": "List recent email messages from the IMAP inbox.",
        "parameters": {
            "type": "object",
            "properties": {
                "folder": {
                    "type": "string",
                    "description": "IMAP folder to read. Defaults to 'INBOX'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of messages to return (1–100). Defaults to 20.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "email_get_message",
        "description": "Fetch full contents of a specific email by UID.",
        "parameters": {
            "type": "object",
            "properties": {
                "uid": {
                    "type": "string",
                    "description": "IMAP UID of the message.",
                },
                "folder": {
                    "type": "string",
                    "description": "IMAP folder containing the message. Defaults to 'INBOX'.",
                },
            },
            "required": ["uid"],
        },
    },
    {
        "name": "email_send",
        "description": "Send an email via SMTP.",
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
                    "description": "Plain-text or HTML body of the email.",
                },
                "html": {
                    "type": "boolean",
                    "description": "If true, body is sent as HTML. Defaults to false.",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "email_mark_read",
        "description": "Mark a message as read (sets the \\Seen IMAP flag).",
        "parameters": {
            "type": "object",
            "properties": {
                "uid": {
                    "type": "string",
                    "description": "IMAP UID of the message.",
                },
                "folder": {
                    "type": "string",
                    "description": "IMAP folder containing the message. Defaults to 'INBOX'.",
                },
            },
            "required": ["uid"],
        },
    },
]
