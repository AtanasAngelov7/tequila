"""Sprint 06 — Vision built-in tools (§17.4, §17.6).

Provides four tools:
- ``vision_describe``      — describe what is in an image
- ``vision_extract_text``  — extract text / OCR from an image
- ``vision_compare``       — compare two or more images
- ``vision_analyze``       — answer a specific question about an image

Image sources
-------------
Each tool accepts an ``image_source`` string in one of these formats:

- File path:  ``/home/user/image.png`` or ``~/screenshots/shot.png``
- URL:        ``https://example.com/photo.jpg``
- Base64:     ``data:image/jpeg;base64,<data>``

VisionConfig
------------
``VisionConfig`` determines which model to use and image size limits.
Set ``preferred_model`` to a specific ``provider:model`` string, or leave
empty to auto-select the first registered vision-capable model.
``max_image_size_px`` triggers auto-resize via Pillow if set.

Graceful failure
----------------
If no vision-capable model is configured, the tools raise ``RuntimeError``
with a clear message rather than silently failing.
"""
from __future__ import annotations

import base64
import io
import logging
import mimetypes
from typing import Any

import httpx
from pydantic import BaseModel

from app.tools.registry import tool

logger = logging.getLogger(__name__)

# ── VisionConfig ──────────────────────────────────────────────────────────────


class VisionConfig(BaseModel):
    """Global configuration for the vision tools."""

    preferred_model: str = ""
    """Provider-qualified model id, e.g. 'anthropic:claude-opus-4-5'. Auto-select if empty."""

    max_image_size_px: int | None = 1568
    """Resize images to this maximum dimension if Pillow is available. None = no resize."""

    default_max_tokens: int = 1024


_vision_config = VisionConfig()


def get_vision_config() -> VisionConfig:
    return _vision_config


def set_vision_config(cfg: VisionConfig) -> None:
    """Replace the module-level config (useful in tests)."""
    global _vision_config  # noqa: PLW0603
    _vision_config = cfg


# ── Image loading ─────────────────────────────────────────────────────────────


def _load_image_as_base64(source: str) -> tuple[str, str]:
    """Load an image from *source* and return ``(base64_data, media_type)``.

    Parameters
    ----------
    source:
        File path, URL, or data-URI (``data:image/...;base64,...``).

    Returns
    -------
    (base64_data, media_type)
    """
    # Data URI
    if source.startswith("data:"):
        header, _, data = source.partition(",")
        media_type = header.split(";")[0].replace("data:", "") or "image/jpeg"
        return data, media_type

    # URL
    if source.startswith(("http://", "https://")):
        response = httpx.get(source, follow_redirects=True, timeout=30)
        response.raise_for_status()
        raw = response.content
        content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
        media_type = content_type or "image/jpeg"
        encoded = base64.standard_b64encode(raw).decode()
        return _maybe_resize(encoded, media_type), media_type

    # File path
    from pathlib import Path
    path = Path(source).expanduser().resolve()
    raw = path.read_bytes()
    guessed, _ = mimetypes.guess_type(str(path))
    media_type = guessed or "image/jpeg"
    encoded = base64.standard_b64encode(raw).decode()
    return _maybe_resize(encoded, media_type), media_type


def _maybe_resize(b64_data: str, media_type: str) -> str:
    """Resize the image if it exceeds ``VisionConfig.max_image_size_px``."""
    cfg = get_vision_config()
    max_px = cfg.max_image_size_px
    if max_px is None:
        return b64_data

    try:
        from PIL import Image

        raw = base64.b64decode(b64_data)
        img = Image.open(io.BytesIO(raw))
        w, h = img.size
        if w <= max_px and h <= max_px:
            return b64_data

        # Downscale preserving aspect ratio
        scale = max_px / max(w, h)
        new_w, new_h = int(w * scale), int(h * scale)
        img_resized = img.resize((new_w, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        fmt = "JPEG" if "jpeg" in media_type else "PNG"
        img_resized.save(buf, format=fmt)
        resized_b64 = base64.standard_b64encode(buf.getvalue()).decode()
        logger.debug(
            "vision: resized image from %dx%d to %dx%d", w, h, new_w, new_h
        )
        return resized_b64

    except ImportError:
        logger.debug("vision: Pillow not available, skipping resize")
        return b64_data
    except Exception as exc:
        logger.warning("vision: image resize failed (%s), using original", exc)
        return b64_data


# ── Provider selection ─────────────────────────────────────────────────────────


async def _get_vision_provider_and_model() -> tuple[Any, str]:
    """Return ``(provider, model_id)`` for the first vision-capable model.

    Raises
    ------
    RuntimeError
        If no vision-capable model / provider is available.
    """
    from app.providers.registry import ProviderRegistry

    reg = ProviderRegistry.global_registry()
    cfg = get_vision_config()

    # Honour explicit preferred_model
    if cfg.preferred_model:
        parts = cfg.preferred_model.split(":", 1)
        if len(parts) == 2:
            provider_id, model_id = parts
            try:
                provider = reg.get(provider_id)
                caps = provider.get_model_capabilities(model_id)
                if caps.supports_vision:
                    return provider, model_id
            except KeyError:
                pass
            logger.warning(
                "vision: preferred_model %r not usable, falling back to auto-select",
                cfg.preferred_model,
            )

    # Auto-select: iterate all providers and their models
    for provider in reg.list_providers():
        try:
            models = await provider.list_models()
            for model_info in models:
                bare_id = model_info.id.split(":", 1)[-1]
                caps = provider.get_model_capabilities(bare_id)
                if caps.supports_vision:
                    return provider, bare_id
        except Exception as exc:
            logger.debug("vision: provider %r model listing failed: %s", provider.provider_id, exc)
            continue

    raise RuntimeError(
        "No vision-capable model is available. "
        "Configure a vision-capable model (e.g. claude-opus-4-5, gpt-4o) in your provider settings."
    )


# ── Vision API call ────────────────────────────────────────────────────────────


def _build_vision_message(
    prompt: str,
    image_sources: list[str],
) -> list[dict[str, Any]]:
    """Build the content list for a vision request message."""
    content: list[dict[str, Any]] = []

    for src in image_sources:
        b64_data, media_type = _load_image_as_base64(src)
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": b64_data,
            },
        })

    content.append({"type": "text", "text": prompt})
    return content


async def _call_vision(prompt: str, image_sources: list[str]) -> str:
    """Send a vision request and return the text response."""
    from app.providers.base import Message

    provider, model_id = await _get_vision_provider_and_model()
    cfg = get_vision_config()

    content = _build_vision_message(prompt, image_sources)
    messages = [Message(role="user", content=content)]

    # Collect all text deltas
    response_parts: list[str] = []
    async for event in provider.stream_completion(
        messages=messages,
        model=model_id,
        max_tokens=cfg.default_max_tokens,
    ):
        if event.kind == "text_delta" and event.text:
            response_parts.append(event.text)
        elif event.kind == "error":
            raise RuntimeError(f"Vision provider error: {event.error_message}")

    return "".join(response_parts)


# ── Tool: vision_describe ──────────────────────────────────────────────────────


@tool(
    description=(
        "Describe the contents of an image in detail. "
        "Accepts a file path, URL, or base64 data-URI as image_source. "
        "Returns a natural language description of what the image shows."
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "image_source": {
                "type": "string",
                "description": "Image source: file path, URL, or base64 data-URI.",
            },
        },
        "required": ["image_source"],
    },
)
async def vision_describe(image_source: str) -> str:
    """Describe the image at *image_source*."""
    prompt = (
        "Please describe this image in detail. "
        "Include what you see, the context, colours, objects, people, text, "
        "and any other relevant details."
    )
    return await _call_vision(prompt, [image_source])


# ── Tool: vision_extract_text ──────────────────────────────────────────────────


@tool(
    description=(
        "Extract all readable text from an image (OCR). "
        "Returns the extracted text as a string. "
        "Accepts a file path, URL, or base64 data-URI."
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "image_source": {
                "type": "string",
                "description": "Image source: file path, URL, or base64 data-URI.",
            },
        },
        "required": ["image_source"],
    },
)
async def vision_extract_text(image_source: str) -> str:
    """Extract all text visible in the image at *image_source*."""
    prompt = (
        "Please extract all the text you can read from this image. "
        "Output only the extracted text, preserving line breaks and layout as much as possible. "
        "If there is no text, say 'No text found'."
    )
    return await _call_vision(prompt, [image_source])


# ── Tool: vision_compare ───────────────────────────────────────────────────────


@tool(
    description=(
        "Compare two or more images and describe their similarities and differences. "
        "Accepts a list of image sources (file paths, URLs, or base64 data-URIs). "
        "Returns a natural language comparison."
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "image_sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of image sources to compare (min 2).",
            },
        },
        "required": ["image_sources"],
    },
)
async def vision_compare(image_sources: list) -> str:
    """Compare two or more images and describe similarities/differences."""
    # Accept either list[str] or a comma-separated string (fallback for simple paths/URLs)
    if isinstance(image_sources, str):
        sources = [s.strip() for s in image_sources.split("\n") if s.strip()]
        if len(sources) < 2:
            # Try comma split as last resort (won't work for data URIs)
            sources = [s.strip() for s in image_sources.split(",") if s.strip()]
    else:
        sources = list(image_sources)

    if len(sources) < 2:
        return "[Error] vision_compare requires at least two image sources."

    prompt = (
        f"I am showing you {len(sources)} images. "
        "Please compare them in detail: "
        "describe the similarities between them, then the differences. "
        "Be specific about colours, objects, composition, style, and any text."
    )
    return await _call_vision(prompt, sources)


# ── Tool: vision_analyze ───────────────────────────────────────────────────────


@tool(
    description=(
        "Analyze an image and answer a specific question about it. "
        "Accepts a file path, URL, or base64 data-URI as image_source. "
        "Use this for targeted questions like 'What is the error in this screenshot?' "
        "or 'How many people are in this photo?'"
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "image_source": {
                "type": "string",
                "description": "Image source: file path, URL, or base64 data-URI.",
            },
            "question": {
                "type": "string",
                "description": "Specific question to answer about the image.",
            },
        },
        "required": ["image_source", "question"],
    },
)
async def vision_analyze(image_source: str, question: str) -> str:
    """Answer *question* about the image at *image_source*."""
    prompt = f"Please answer the following question about this image:\n\n{question}"
    return await _call_vision(prompt, [image_source])
