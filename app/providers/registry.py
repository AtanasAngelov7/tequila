"""Sprint 04 — Provider registry (§4.6b).

Singleton ``ProviderRegistry`` that:
- holds registered ``LLMProvider`` instances keyed by ``provider_id``
- caches ``ModelCapabilities`` per ``provider:model`` pair
- exposes ``list_all_providers()`` / ``list_all_model_infos()``
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from app.providers.base import LLMProvider, ModelCapabilities, ModelInfo

logger = logging.getLogger(__name__)

# TD-281: Module-level lock for thread-safe singleton creation
_registry_lock = threading.Lock()


class ProviderRegistry:
    """Central registry for LLM provider instances.

    Usage::

        registry = ProviderRegistry()
        registry.register(AnthropicProvider())
        registry.register(OpenAIProvider())

        provider = registry.get("anthropic")
        costs = provider.cost_per_token("claude-sonnet-4-6")
    """

    _instance: "ProviderRegistry | None" = None

    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}
        self._caps_cache: dict[str, ModelCapabilities] = {}
        self._caps_cache_max = 200  # TD-284: Bound capability cache size
        # TD-363: removed dead self._lock (asyncio.Lock) — never acquired

    # ── Singleton helpers ─────────────────────────────────────────────────────

    @classmethod
    def global_registry(cls) -> "ProviderRegistry":
        """Return (creating if necessary) the application-level singleton.

        TD-264: Uses a lock to prevent duplicate creation in concurrent contexts.
        In practice, asyncio is single-threaded so the lock is a safety net.
        """
        if cls._instance is None:
            with _registry_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, provider: LLMProvider) -> None:
        """Register *provider*; overwrites any existing registration for the same id."""
        if not provider.provider_id:
            raise ValueError("LLMProvider must have a non-empty provider_id")
        self._providers[provider.provider_id] = provider
        logger.info("ProviderRegistry: registered provider '%s'", provider.provider_id)

    def unregister(self, provider_id: str) -> None:
        """Remove a provider from the registry."""
        self._providers.pop(provider_id, None)
        # Purge capability cache entries for this provider
        stale = [k for k in self._caps_cache if k.startswith(f"{provider_id}:")]
        for k in stale:
            del self._caps_cache[k]
        # TD-289: Also remove the circuit breaker for this provider
        try:
            from app.providers.circuit_breaker import remove_circuit_breaker
            remove_circuit_breaker(provider_id)
        except Exception:
            pass

    # ── Lookup ────────────────────────────────────────────────────────────────

    def get(self, provider_id: str) -> LLMProvider:
        """Return the provider for *provider_id*.

        Raises ``KeyError`` if not registered.
        """
        if provider_id not in self._providers:
            raise KeyError(
                f"Provider '{provider_id}' is not registered. "
                f"Available: {list(self._providers)}"
            )
        return self._providers[provider_id]

    def get_optional(self, provider_id: str) -> LLMProvider | None:
        """Like ``get()`` but returns ``None`` when not found."""
        return self._providers.get(provider_id)

    def list_providers(self) -> list[LLMProvider]:
        """Return all registered provider instances."""
        return list(self._providers.values())

    def provider_ids(self) -> list[str]:
        """Return all registered provider IDs."""
        return list(self._providers.keys())

    # ── Capability cache ──────────────────────────────────────────────────────

    def cache_capabilities(self, provider_id: str, model: str, caps: ModelCapabilities) -> None:
        key = f"{provider_id}:{model}"
        # TD-284: Evict oldest if at capacity
        if key not in self._caps_cache and len(self._caps_cache) >= self._caps_cache_max:
            oldest = next(iter(self._caps_cache))
            del self._caps_cache[oldest]
        self._caps_cache[key] = caps

    def get_cached_capabilities(self, provider_id: str, model: str) -> ModelCapabilities | None:
        return self._caps_cache.get(f"{provider_id}:{model}")

    def get_capabilities(self, provider_id: str, model: str) -> ModelCapabilities:
        """Return capabilities — from cache if available, else from provider."""
        cached = self.get_cached_capabilities(provider_id, model)
        if cached:
            return cached
        provider = self.get(provider_id)
        caps = provider.get_model_capabilities(model)
        self.cache_capabilities(provider_id, model, caps)
        return caps

    # ── Aggregate model listing ───────────────────────────────────────────────

    async def list_all_models(self) -> list[ModelInfo]:
        """Gather models from all registered providers concurrently."""

        async def _fetch(provider: LLMProvider) -> list[ModelInfo]:
            try:
                return await provider.list_models()
            except Exception as exc:
                logger.warning(
                    "ProviderRegistry: could not list models for '%s': %s",
                    provider.provider_id,
                    exc,
                )
                return []

        per_provider = await asyncio.gather(  # TD-390
            *[_fetch(p) for p in self.list_providers()],
            return_exceptions=True,
        )
        results: list[ModelInfo] = []
        for item in per_provider:
            if isinstance(item, BaseException):
                logger.warning(
                    "ProviderRegistry: unexpected error in model listing: %s", item
                )
            else:
                results.extend(item)
        return results

    async def health_check_all(self) -> dict[str, bool]:
        """Run health checks on all providers and return a status dict."""
        status: dict[str, bool] = {}

        async def _check(provider: LLMProvider) -> None:
            try:
                status[provider.provider_id] = await provider.health_check()
            except Exception:
                status[provider.provider_id] = False

        await asyncio.gather(*[_check(p) for p in self.list_providers()])
        return status

    # ── Parse qualified model strings ──────────────────────────────────────────

    @staticmethod
    def split_model_id(qualified: str) -> tuple[str, str]:
        """Split ``"provider:model_id"`` → ``("provider", "model_id")``.

        Raises ``ValueError`` if the format is wrong.
        """
        parts = qualified.split(":", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError(
                f"Invalid qualified model id '{qualified}'. "
                "Expected format: '<provider>:<model_id>'"
            )
        return parts[0], parts[1]

    def get_provider_for_model(self, qualified_model: str) -> tuple[LLMProvider, str]:
        """Lookup provider and bare model ID from a qualified model string."""
        provider_id, model_id = self.split_model_id(qualified_model)
        provider = self.get(provider_id)
        return provider, model_id

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"ProviderRegistry(providers={list(self._providers)}, "
            f"cached_caps={len(self._caps_cache)})"
        )


# Module-level convenience accessor
def get_registry() -> ProviderRegistry:
    """Return the application-level ``ProviderRegistry`` singleton."""
    return ProviderRegistry.global_registry()
