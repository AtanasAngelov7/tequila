"""Unit tests for the ImageGenPlugin (Sprint 16 §29.1 D1).

Tests cover:
  - Tool list structure validation
  - configure() with valid/missing credentials
  - activate() / deactivate()
  - health_check() and test() logic
  - Plugin metadata (plugin_id, name, plugin_type)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.plugins.builtin.image_gen.plugin import ImageGenPlugin
from app.plugins.builtin.image_gen.tools import IMAGE_GEN_TOOLS


# ── Tool list sanity checks ───────────────────────────────────────────────────

class TestImageGenTools:
    def test_three_tools_defined(self):
        assert len(IMAGE_GEN_TOOLS) == 3

    def test_tool_names(self):
        names = {t["name"] for t in IMAGE_GEN_TOOLS}
        assert names == {"image_generate", "image_edit", "image_variations"}

    def test_each_tool_has_parameters(self):
        for tool in IMAGE_GEN_TOOLS:
            assert "parameters" in tool
            assert tool["parameters"]["type"] == "object"
            assert "required" in tool["parameters"]

    def test_generate_requires_prompt(self):
        gen = next(t for t in IMAGE_GEN_TOOLS if t["name"] == "image_generate")
        assert "prompt" in gen["parameters"]["required"]

    def test_edit_requires_image_path_and_prompt(self):
        edit = next(t for t in IMAGE_GEN_TOOLS if t["name"] == "image_edit")
        assert "image_path" in edit["parameters"]["required"]
        assert "prompt" in edit["parameters"]["required"]

    def test_variations_requires_image_path(self):
        var = next(t for t in IMAGE_GEN_TOOLS if t["name"] == "image_variations")
        assert "image_path" in var["parameters"]["required"]


# ── Plugin metadata ───────────────────────────────────────────────────────────

class TestImageGenPluginMetadata:
    def test_plugin_id(self):
        assert ImageGenPlugin.plugin_id == "image_gen"

    def test_plugin_type(self):
        assert ImageGenPlugin.plugin_type == "tool"

    def test_name(self):
        assert "Image Generation" in ImageGenPlugin.name


# ── configure / activate / deactivate ────────────────────────────────────────

class TestImageGenPluginLifecycle:
    @pytest.fixture
    def plugin(self) -> ImageGenPlugin:
        return ImageGenPlugin()

    async def _auth_store_with(self, key: str, value: str | None):
        """Return an auth_store callable that resolves one key."""
        async def auth_store(plugin_id: str, credential_key: str) -> str | None:
            if credential_key == key:
                return value
            return None
        return auth_store

    @pytest.mark.asyncio
    async def test_configure_with_openai_key(self, plugin: ImageGenPlugin):
        store = await self._auth_store_with("api_key", "sk-test123")
        await plugin.configure({}, store)
        assert plugin._api_key == "sk-test123"

    @pytest.mark.asyncio
    async def test_configure_with_sd_url(self, plugin: ImageGenPlugin):
        async def store(plugin_id, key):
            return "http://localhost:7860" if key == "sd_url" else None
        await plugin.configure({}, store)
        assert plugin._sd_url == "http://localhost:7860"

    @pytest.mark.asyncio
    async def test_configure_missing_credentials_raises(self, plugin: ImageGenPlugin):
        async def empty_store(plugin_id, key):
            return None
        with pytest.raises(ValueError, match="api_key"):
            await plugin.configure({}, empty_store)

    @pytest.mark.asyncio
    async def test_activate_after_configure(self, plugin: ImageGenPlugin):
        store = await self._auth_store_with("api_key", "sk-test123")
        await plugin.configure({}, store)
        await plugin.activate()
        assert plugin._active is True

    @pytest.mark.asyncio
    async def test_activate_without_configure_raises(self, plugin: ImageGenPlugin):
        with pytest.raises(RuntimeError, match="not configured"):
            await plugin.activate()

    @pytest.mark.asyncio
    async def test_deactivate(self, plugin: ImageGenPlugin):
        store = await self._auth_store_with("api_key", "sk-test123")
        await plugin.configure({}, store)
        await plugin.activate()
        await plugin.deactivate()
        assert plugin._active is False

    @pytest.mark.asyncio
    async def test_get_tools_returns_list(self, plugin: ImageGenPlugin):
        tools = await plugin.get_tools()
        assert len(tools) == 3


# ── Health check ──────────────────────────────────────────────────────────────

class TestImageGenPluginHealth:
    @pytest.fixture
    async def configured_plugin(self) -> ImageGenPlugin:
        plugin = ImageGenPlugin()
        async def store(pid, key):
            return "sk-test" if key == "api_key" else None
        await plugin.configure({}, store)
        return plugin

    @pytest.mark.asyncio
    async def test_health_not_configured(self):
        plugin = ImageGenPlugin()
        result = await plugin.health_check()
        assert result.healthy is False

    @pytest.mark.asyncio
    async def test_health_configured(self, configured_plugin: ImageGenPlugin):
        result = await configured_plugin.health_check()
        assert result.healthy is True
        assert "OpenAI DALL-E" in result.message

    @pytest.mark.asyncio
    async def test_test_valid_key(self, configured_plugin: ImageGenPlugin):
        result = await configured_plugin.test()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_test_invalid_key(self):
        plugin = ImageGenPlugin()
        plugin._api_key = "badkey"
        result = await plugin.test()
        assert result.success is False
        assert "does not look like" in result.message


# ── Auth spec / config schema ─────────────────────────────────────────────────

class TestImageGenPluginSchema:
    def test_auth_spec_kind(self):
        plugin = ImageGenPlugin()
        spec = plugin.get_auth_spec()
        assert spec.kind == "api_key"

    def test_config_schema_properties(self):
        plugin = ImageGenPlugin()
        schema = plugin.get_config_schema()
        assert "default_model" in schema["properties"]
        assert "default_size" in schema["properties"]

    def test_dependencies(self):
        plugin = ImageGenPlugin()
        deps = plugin.get_dependencies()
        assert any("openai" in p for p in deps.python_packages)
