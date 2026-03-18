"""Tool definitions for the WhatsApp Business connector plugin (Sprint 16 §29.4 D4)."""
from __future__ import annotations

from typing import Any

WHATSAPP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "whatsapp_send",
        "description": (
            "Send a text message to a WhatsApp number via the "
            "WhatsApp Business Cloud API."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "number": {
                    "type": "string",
                    "description": (
                        "Recipient phone number in E.164 format "
                        "(e.g. +15551234567).  Omit the leading +."
                    ),
                },
                "text": {
                    "type": "string",
                    "description": "Message body text.",
                },
            },
            "required": ["number", "text"],
        },
    },
    {
        "name": "whatsapp_send_media",
        "description": (
            "Send an image, video, audio, or document to a WhatsApp number via "
            "the WhatsApp Business Cloud API."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "number": {
                    "type": "string",
                    "description": "Recipient phone number in E.164 format.",
                },
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the media file to send.",
                },
                "caption": {
                    "type": "string",
                    "description": "Optional caption for the media.",
                },
            },
            "required": ["number", "file_path"],
        },
    },
]
