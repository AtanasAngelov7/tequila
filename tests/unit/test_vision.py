"""Unit tests for app/tools/builtin/vision.py"""
import base64
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.builtin.vision import (
    VisionConfig,
    _load_image_as_base64,
    _maybe_resize,
    get_vision_config,
    set_vision_config,
    vision_describe,
    vision_extract_text,
    vision_compare,
    vision_analyze,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_tiny_png() -> bytes:
    """Return a minimal valid 1x1 white PNG image."""
    import struct
    import zlib

    def make_chunk(type_: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(type_ + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + type_ + data + struct.pack(">I", crc)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = make_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    # 1x1 RGB pixel = white
    raw_data = b"\x00\xFF\xFF\xFF"
    compressed = zlib.compress(raw_data)
    idat = make_chunk(b"IDAT", compressed)
    iend = make_chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


def _png_as_data_uri() -> str:
    png = _make_tiny_png()
    b64 = base64.standard_b64encode(png).decode()
    return f"data:image/png;base64,{b64}"


# ── VisionConfig ──────────────────────────────────────────────────────────────


def test_vision_config_defaults() -> None:
    cfg = VisionConfig()
    assert cfg.preferred_model == ""
    assert cfg.max_image_size_px == 1568
    assert cfg.default_max_tokens == 1024


def test_set_vision_config() -> None:
    original = get_vision_config()
    custom = VisionConfig(preferred_model="anthropic:claude-opus-4-5")
    set_vision_config(custom)
    assert get_vision_config().preferred_model == "anthropic:claude-opus-4-5"
    set_vision_config(original)


# ── _load_image_as_base64 ─────────────────────────────────────────────────────


def test_load_image_data_uri() -> None:
    data_uri = _png_as_data_uri()
    b64, media_type = _load_image_as_base64(data_uri)
    assert media_type == "image/png"
    # Should be valid base64
    decoded = base64.b64decode(b64)
    assert len(decoded) > 0


def test_load_image_from_file(tmp_path) -> None:
    png_bytes = _make_tiny_png()
    p = tmp_path / "test.png"
    p.write_bytes(png_bytes)

    b64, media_type = _load_image_as_base64(str(p))
    assert "image" in media_type
    decoded = base64.b64decode(b64)
    assert decoded == png_bytes


def test_load_image_from_url() -> None:
    png_bytes = _make_tiny_png()

    mock_response = MagicMock()
    mock_response.content = png_bytes
    mock_response.headers = {"content-type": "image/png"}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=mock_response):
        b64, media_type = _load_image_as_base64("https://example.com/img.png")

    assert media_type == "image/png"
    assert base64.b64decode(b64) == png_bytes


# ── _maybe_resize ──────────────────────────────────────────────────────────────


def test_maybe_resize_no_change_when_small() -> None:
    """Images smaller than max_image_size_px are returned unchanged."""
    set_vision_config(VisionConfig(max_image_size_px=2000))
    png_bytes = _make_tiny_png()  # 1x1, definitely under 2000px
    b64 = base64.standard_b64encode(png_bytes).decode()

    result = _maybe_resize(b64, "image/png")
    assert result == b64


def test_maybe_resize_disabled_when_none() -> None:
    set_vision_config(VisionConfig(max_image_size_px=None))
    large_b64 = base64.standard_b64encode(b"fake data").decode()
    result = _maybe_resize(large_b64, "image/jpeg")
    assert result == large_b64


# ── Vision tools (mocked _call_vision) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_vision_describe() -> None:
    data_uri = _png_as_data_uri()

    with patch("app.tools.builtin.vision._call_vision", new=AsyncMock(return_value="A white pixel.")) as mock_call:
        result = await vision_describe(data_uri)

    assert result == "A white pixel."
    assert mock_call.called
    call_args = mock_call.call_args
    assert "describe" in call_args[0][0].lower() or "describe" in str(call_args).lower()


@pytest.mark.asyncio
async def test_vision_extract_text() -> None:
    data_uri = _png_as_data_uri()

    with patch("app.tools.builtin.vision._call_vision", new=AsyncMock(return_value="Hello World")) as mock_call:
        result = await vision_extract_text(data_uri)

    assert result == "Hello World"


@pytest.mark.asyncio
async def test_vision_analyze() -> None:
    data_uri = _png_as_data_uri()

    with patch("app.tools.builtin.vision._call_vision", new=AsyncMock(return_value="It is white.")) as mock_call:
        result = await vision_analyze(data_uri, "What colour is it?")

    assert result == "It is white."
    prompt_arg = mock_call.call_args[0][0]
    assert "What colour is it?" in prompt_arg


@pytest.mark.asyncio
async def test_vision_compare_two_images() -> None:
    data_uri = _png_as_data_uri()
    sources_list = [data_uri, data_uri]

    with patch("app.tools.builtin.vision._call_vision", new=AsyncMock(return_value="They look the same.")) as mock_call:
        result = await vision_compare(sources_list)

    assert result == "They look the same."
    images_arg = mock_call.call_args[0][1]
    assert len(images_arg) == 2


@pytest.mark.asyncio
async def test_vision_compare_single_image_error() -> None:
    data_uri = _png_as_data_uri()
    # Only one source — should fail gracefully
    result = await vision_compare([data_uri])
    assert "[Error]" in result


@pytest.mark.asyncio
async def test_vision_no_capable_model_raises() -> None:
    """If no vision-capable model, _get_vision_provider_and_model raises RuntimeError."""
    from app.tools.builtin.vision import _get_vision_provider_and_model
    from app.providers.registry import ProviderRegistry

    # Use a new registry with no providers
    original = ProviderRegistry._instance
    ProviderRegistry._instance = ProviderRegistry()

    try:
        with pytest.raises(RuntimeError, match="No vision-capable model"):
            await _get_vision_provider_and_model()
    finally:
        ProviderRegistry._instance = original


def test_vision_tools_registered() -> None:
    from app.tools.registry import get_tool_registry
    from app.tools.builtin import register_all_builtin_tools
    register_all_builtin_tools()
    reg = get_tool_registry()
    for name in ("vision_describe", "vision_extract_text", "vision_compare", "vision_analyze"):
        entry = reg.get(name)
        assert entry is not None, f"{name} not registered"
        td, _ = entry
        assert td.safety == "read_only"
