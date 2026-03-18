"""Pydantic models for the plugin system (Sprint 12, §8.0–8.1, §8.7).

These are the data-transfer and persistence models used throughout the
plugin system.  Runtime plugin instances subclass ``PluginBase`` (see
``app/plugins/base.py``); these models represent the persisted record.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Auth & channel specs ──────────────────────────────────────────────────────


class OAuth2Config(BaseModel):
    """OAuth2 provider configuration."""

    provider: str
    """Short provider name, e.g. ``"google"``, ``"telegram"``."""

    scopes: list[str] = []
    """OAuth2 scopes required by the plugin."""

    auth_url: str = ""
    """Authorization endpoint URL."""

    token_url: str = ""
    """Token exchange endpoint URL."""

    redirect_uri: str = ""
    """OAuth2 redirect URI (for callback)."""


class PluginAuth(BaseModel):
    """Auth requirements declared by a plugin (§8.1)."""

    kind: Literal["oauth2", "api_key", "token", "none"] = "none"
    """Authentication mechanism required by the plugin."""

    oauth2_config: OAuth2Config | None = None
    """OAuth2 configuration — only when ``kind == "oauth2"``."""

    key_label: str = "API Key"
    """Human-readable label for the credential input in the config UI."""


class ChannelAdapterSpec(BaseModel):
    """Channel capabilities declared by a connector plugin (§8.1)."""

    channel_name: str
    """Logical channel name, e.g. ``"telegram"``, ``"email"``."""

    supports_inbound: bool = True
    """Plugin can receive messages from the external service."""

    supports_outbound: bool = True
    """Plugin can send messages to the external service."""

    supports_voice: bool = False
    """Plugin handles voice/audio messages."""

    polling_mode: bool = False
    """Plugin uses polling to retrieve messages (vs push/webhook)."""


class PipelineHookSpec(BaseModel):
    """Pipeline hook registration spec (§8.0)."""

    hook_point: Literal[
        "pre_prompt_assembly",
        "post_prompt_assembly",
        "pre_tool_execution",
        "post_tool_execution",
        "pre_response",
        "post_response",
    ]
    """Where in the turn pipeline this hook fires."""

    priority: int = 100
    """Execution priority — lower number runs first when multiple hooks target the same point."""


# ── Plugin health & test results ──────────────────────────────────────────────


class PluginHealthResult(BaseModel):
    """Result of a plugin health check (§8.7)."""

    healthy: bool
    """Whether the plugin considers itself healthy."""

    message: str = ""
    """Optional human-readable detail."""

    details: dict[str, Any] = {}
    """Provider-specific diagnostics — never contains credentials."""

    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    """Timestamp when the check was performed."""


class PluginTestResult(BaseModel):
    """Result of a plugin connectivity test (§8.7)."""

    success: bool
    """Whether the one-shot test succeeded."""

    message: str = ""
    """Optional human-readable detail."""

    latency_ms: int | None = None
    """Round-trip latency of the test request in milliseconds."""

    details: dict[str, Any] = {}
    """Provider-specific test output — never contains credentials."""


# ── Dependency spec ───────────────────────────────────────────────────────────


class PluginDependencies(BaseModel):
    """Python / system dependencies required by the plugin (§8.9)."""

    python_packages: list[str] = []
    """pip install specs, e.g. ``["google-auth>=2.0", "google-api-python-client>=2.0"]``."""

    system_commands: list[str] = []
    """Commands to run after pip install, e.g. ``["playwright install chromium"]``."""

    optional: bool = False
    """If ``True``, the plugin activates in degraded mode when deps are missing."""


# ── Persisted plugin record ───────────────────────────────────────────────────


class PluginRecord(BaseModel):
    """Persisted plugin state — one row in the ``plugins`` table."""

    plugin_id: str
    """Unique plugin identifier, e.g. ``"telegram"``, ``"webhooks"``."""

    name: str
    """Human-readable display name."""

    description: str = ""
    """Short description of what the plugin does."""

    version: str = "1.0.0"
    """Plugin version string."""

    plugin_type: Literal["connector", "pipeline_hook", "audit_sink"]
    """Plugin category — determines which capabilities it can register."""

    connector_type: Literal["builtin", "mcp", "custom"] | None = None
    """Sub-type for connector plugins.  ``None`` for non-connector plugins."""

    config: dict[str, Any] = {}
    """Persisted plugin configuration (plugin-specific)."""

    status: Literal["installed", "configured", "active", "error", "disabled"] = "installed"
    """Current lifecycle state of the plugin."""

    error_message: str | None = None
    """Last error message if ``status == "error"``."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
