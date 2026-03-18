"""Tool definitions for the Image Generation plugin (Sprint 16 §29.1 D1)."""
from __future__ import annotations

from typing import Any

IMAGE_GEN_TOOLS: list[dict[str, Any]] = [
    {
        "name": "image_generate",
        "description": (
            "Generate an image from a text prompt using an AI image model "
            "(DALL-E 3 by default).  Returns a URL or base-64 string."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed text description of the image to generate.",
                },
                "model": {
                    "type": "string",
                    "enum": ["dall-e-3", "dall-e-2", "stable-diffusion"],
                    "description": "Image generation model to use (default: dall-e-3).",
                    "default": "dall-e-3",
                },
                "size": {
                    "type": "string",
                    "enum": ["256x256", "512x512", "1024x1024", "1792x1024", "1024x1792"],
                    "description": "Output image dimensions (default: 1024x1024).",
                    "default": "1024x1024",
                },
                "style": {
                    "type": "string",
                    "enum": ["vivid", "natural"],
                    "description": "Image style — vivid (hyper-real) or natural (default: vivid).",
                    "default": "vivid",
                },
                "quality": {
                    "type": "string",
                    "enum": ["standard", "hd"],
                    "description": "Output quality — standard or hd (default: standard).",
                    "default": "standard",
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "image_edit",
        "description": (
            "Edit an existing image using a text prompt and an optional mask.  "
            "The mask designates which parts of the image to replace."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "Absolute path to the source PNG image (must be <4 MB, RGBA).",
                },
                "prompt": {
                    "type": "string",
                    "description": "Instruction describing what to add or change.",
                },
                "mask_path": {
                    "type": "string",
                    "description": (
                        "Optional path to a PNG mask (same size as image).  "
                        "Transparent areas indicate where to apply changes."
                    ),
                },
                "size": {
                    "type": "string",
                    "enum": ["256x256", "512x512", "1024x1024"],
                    "description": "Output size (default: 1024x1024).",
                    "default": "1024x1024",
                },
            },
            "required": ["image_path", "prompt"],
        },
    },
    {
        "name": "image_variations",
        "description": "Create one or more variations of an existing image.",
        "parameters": {
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "Absolute path to the source PNG image.",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of variations to create (1–10, default: 1).",
                    "default": 1,
                    "minimum": 1,
                    "maximum": 10,
                },
                "size": {
                    "type": "string",
                    "enum": ["256x256", "512x512", "1024x1024"],
                    "description": "Output size (default: 1024x1024).",
                    "default": "1024x1024",
                },
            },
            "required": ["image_path"],
        },
    },
]
