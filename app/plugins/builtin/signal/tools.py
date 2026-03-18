"""Tool definitions for the Signal CLI bridge connector plugin (Sprint 16 §29.5 D5)."""
from __future__ import annotations

from typing import Any

SIGNAL_TOOLS: list[dict[str, Any]] = [
    {
        "name": "signal_send",
        "description": (
            "Send a text message to a Signal recipient via a local "
            "signal-cli daemon (JSON-RPC mode)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "recipient": {
                    "type": "string",
                    "description": (
                        "Recipient phone number (E.164 format, e.g. +15551234567) "
                        "or group ID."
                    ),
                },
                "message": {
                    "type": "string",
                    "description": "Message body text.",
                },
            },
            "required": ["recipient", "message"],
        },
    },
    {
        "name": "signal_send_file",
        "description": (
            "Send a file (image, video, document) to a Signal recipient "
            "via a local signal-cli daemon."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "recipient": {
                    "type": "string",
                    "description": "Recipient phone number (E.164 format) or group ID.",
                },
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file to send.",
                },
                "caption": {
                    "type": "string",
                    "description": "Optional caption accompanying the file.",
                },
            },
            "required": ["recipient", "file_path"],
        },
    },
]
