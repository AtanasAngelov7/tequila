"""Image Generation plugin — DALL-E 3 / Stable Diffusion support (Sprint 16 §29.1).

Required credentials:
  - ``api_key``  — OpenAI API key (for DALL-E models)
  - ``sd_url``   — Stable Diffusion API endpoint (optional, for SD model)
"""
from __future__ import annotations

import logging
from typing import Any

from app.plugins.base import PluginBase
from app.plugins.builtin.image_gen.tools import IMAGE_GEN_TOOLS
from app.plugins.models import (
    ChannelAdapterSpec,
    PluginAuth,
    PluginDependencies,
    PluginHealthResult,
    PluginTestResult,
)

logger = logging.getLogger(__name__)


class ImageGenPlugin(PluginBase):
    """AI image generation via DALL-E 3 (OpenAI) or Stable Diffusion."""

    plugin_id = "image_gen"
    name = "Image Generation"
    description = "Generate, edit, and create variations of images using AI models."
    version = "1.0.0"
    plugin_type = "tool"
    connector_type = "builtin"

    def __init__(self) -> None:
        self._api_key: str | None = None
        self._sd_url: str | None = None
        self._active = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def configure(self, config: dict[str, Any], auth_store: Any) -> None:
        self._api_key = await auth_store("image_gen", "api_key")
        self._sd_url = await auth_store("image_gen", "sd_url")
        if not self._api_key and not self._sd_url:
            raise ValueError(
                "Image Generation requires either an OpenAI API key (api_key) "
                "or a Stable Diffusion endpoint URL (sd_url)."
            )

    async def activate(self) -> None:
        if not self._api_key and not self._sd_url:
            raise RuntimeError("Plugin not configured. Call configure() first.")
        self._active = True
        logger.info("ImageGenPlugin activated.")

    async def deactivate(self) -> None:
        self._active = False
        logger.info("ImageGenPlugin deactivated.")

    # ── Tools ─────────────────────────────────────────────────────────────────

    async def get_tools(self) -> list[Any]:
        return IMAGE_GEN_TOOLS

    # ── Channel adapter ───────────────────────────────────────────────────────

    async def get_channel_adapter(self) -> ChannelAdapterSpec:
        return ChannelAdapterSpec(
            channel_name="image_gen",
            supports_inbound=False,
            supports_outbound=True,
            polling_mode=False,
        )

    # ── Auth & schema ─────────────────────────────────────────────────────────

    def get_auth_spec(self) -> PluginAuth:
        return PluginAuth(kind="api_key", key_label="OpenAI API Key")

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "default_model": {
                    "type": "string",
                    "enum": ["dall-e-3", "dall-e-2", "stable-diffusion"],
                    "description": "Default image generation model.",
                    "default": "dall-e-3",
                },
                "default_size": {
                    "type": "string",
                    "description": "Default image size.",
                    "default": "1024x1024",
                },
            },
        }

    def get_dependencies(self) -> PluginDependencies:
        return PluginDependencies(python_packages=["openai>=1.0", "httpx>=0.25"])

    # ── Health & test ─────────────────────────────────────────────────────────

    async def health_check(self) -> PluginHealthResult:
        if not self._api_key and not self._sd_url:
            return PluginHealthResult(healthy=False, message="Not configured.")
        backend = "OpenAI DALL-E" if self._api_key else "Stable Diffusion"
        return PluginHealthResult(
            healthy=True,
            message=f"Configured — backend: {backend}",
        )

    async def test(self) -> PluginTestResult:
        if not self._api_key and not self._sd_url:
            return PluginTestResult(success=False, message="Not configured.")
        # Lightweight validation: check key format rather than spending API credits.
        if self._api_key and not self._api_key.startswith("sk-"):
            return PluginTestResult(
                success=False,
                message="api_key does not look like a valid OpenAI key (expected sk-...).",
            )
        return PluginTestResult(success=True, message="Credentials look valid.")

    # ── Image operations ──────────────────────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        *,
        model: str = "dall-e-3",
        size: str = "1024x1024",
        style: str = "vivid",
        quality: str = "standard",
    ) -> dict[str, Any]:
        """Generate an image and return ``{"url": "...", "revised_prompt": "..."}``.

        Falls back to Stable Diffusion if ``model == "stable-diffusion"``.
        """
        if model == "stable-diffusion":
            return await self._sd_generate(prompt, size=size)
        return await self._dalle_generate(
            prompt, model=model, size=size, style=style, quality=quality
        )

    async def _dalle_generate(
        self,
        prompt: str,
        *,
        model: str = "dall-e-3",
        size: str = "1024x1024",
        style: str = "vivid",
        quality: str = "standard",
    ) -> dict[str, Any]:
        import httpx

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": size,
        }
        if model == "dall-e-3":
            payload["style"] = style
            payload["quality"] = quality

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        item = data["data"][0]
        return {
            "url": item.get("url"),
            "revised_prompt": item.get("revised_prompt", prompt),
            "model": model,
        }

    async def _sd_generate(
        self, prompt: str, *, size: str = "512x512"
    ) -> dict[str, Any]:
        import httpx

        width, height = (int(d) for d in size.split("x"))
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self._sd_url}/sdapi/v1/txt2img",
                json={"prompt": prompt, "width": width, "height": height, "steps": 20},
            )
            resp.raise_for_status()
            data = resp.json()

        image_b64 = data["images"][0]
        return {"b64": image_b64, "model": "stable-diffusion"}
