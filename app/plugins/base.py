"""Abstract base class for all Tequila plugins (Sprint 12, §8.0–8.1).

Every built-in and third-party plugin MUST subclass ``PluginBase`` and
implement all ``@abstractmethod`` members.  Optional capabilities (channel
adapters, pipeline hooks, health checks, etc.) have working default
implementations that return harmless no-op results.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from app.plugins.models import (
    ChannelAdapterSpec,
    PluginAuth,
    PluginDependencies,
    PluginHealthResult,
    PluginTestResult,
)

if TYPE_CHECKING:
    from app.tools.registry import ToolDefinition  # type: ignore[attr-defined]


class PluginBase(ABC):
    """Base class for all Tequila plugins.

    Concrete plugins must define the following class-level attributes::

        plugin_id:   str  — unique, lower-snake-case, e.g. ``"telegram"``
        name:        str  — human-readable display name
        description: str  — one-line description shown in the UI
        version:     str  — semantic version string (default ``"1.0.0"``)
        plugin_type: str  — one of ``"connector"``, ``"pipeline_hook"``, ``"audit_sink"``
    """

    # ── Class-level metadata (must be overridden in each subclass) ────────────

    plugin_id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    plugin_type: str  # "connector" | "pipeline_hook" | "audit_sink"

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self, gateway: Any) -> None:  # noqa: ANN401
        """Called once during registry startup, before ``configure()``.

        Subclasses may override to store the gateway reference or perform
        one-time initialisation that does **not** require credentials.
        """
        self._gateway = gateway

    @abstractmethod
    async def configure(self, config: dict[str, Any], auth_store: Any) -> None:
        """Apply persisted configuration and fetch/validate credentials.

        Args:
            config:     Plugin-specific config dict stored in ``plugins.config``.
            auth_store: Callable (or store object) for retrieving persisted
                        credentials — signature:
                        ``await auth_store(plugin_id, credential_key) -> str | None``.

        Raises:
            ValueError: if a required config value is missing.
            RuntimeError: if credential lookup fails.
        """

    @abstractmethod
    async def activate(self) -> None:
        """Start any background tasks, open connections, begin polling, etc."""

    @abstractmethod
    async def deactivate(self) -> None:
        """Gracefully stop all background tasks and release resources."""

    # ── Tool registration ─────────────────────────────────────────────────────

    @abstractmethod
    async def get_tools(self) -> list[Any]:
        """Return the list of ``ToolDefinition`` objects this plugin exposes.

        Return an empty list if the plugin has no tools.
        """

    # ── Optional capabilities ─────────────────────────────────────────────────

    async def get_channel_adapter(self) -> ChannelAdapterSpec | None:
        """Return channel capabilities, or ``None`` if not a channel plugin."""
        return None

    async def get_hooks(self) -> list[Any] | None:
        """Return pipeline hooks, or ``None`` if this plugin has no hooks."""
        return None

    # ── Health & test ─────────────────────────────────────────────────────────

    async def health_check(self) -> PluginHealthResult:
        """Perform a lightweight liveness check.

        Override to add real connectivity checks.  The default always
        returns ``healthy=True``.
        """
        from datetime import datetime, timezone

        return PluginHealthResult(healthy=True, checked_at=datetime.now(timezone.utc))

    async def test(self) -> PluginTestResult:
        """Run a one-shot connectivity / integration test.

        Override to add a real end-to-end test.  The default always
        returns ``success=True``.
        """
        return PluginTestResult(success=True)

    # ── Schema & auth introspection ───────────────────────────────────────────

    def get_config_schema(self) -> dict[str, Any]:
        """Return a JSON-Schema dict describing the plugin's config fields.

        Used by the frontend to render a dynamic config form.
        Return ``{}`` to show a plain JSON textarea instead.
        """
        return {}

    def get_auth_spec(self) -> PluginAuth | None:
        """Return the authentication requirements for this plugin, or ``None``."""
        return None

    def get_dependencies(self) -> PluginDependencies:
        """Return the Python / system dependencies required by this plugin."""
        return PluginDependencies()

    # ── Dunder helpers ────────────────────────────────────────────────────────

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Plugin {self.plugin_id!r} status=attached>"
