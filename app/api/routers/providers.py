"""Sprint 04 — Provider listing API (§4.6b).

Endpoints
---------
GET  /api/providers           — list registered providers + health status
GET  /api/providers/{id}      — provider detail + model list
GET  /api/providers/{id}/models  — list models for a specific provider
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.providers.registry import get_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("", summary="List all registered providers")
async def list_providers() -> dict[str, Any]:
    """Return all registered providers with health and available model counts."""
    registry = get_registry()
    providers = registry.list_providers()
    health = await registry.health_check_all()

    result = []
    for p in providers:
        try:
            models = await p.list_models()
            model_count = len(models)
        except Exception:
            model_count = 0
        result.append(
            {
                "provider_id": p.provider_id,
                "healthy": health.get(p.provider_id, False),
                "model_count": model_count,
            }
        )
    return {"providers": result, "count": len(result)}


@router.get("/{provider_id}", summary="Provider detail with models")
async def get_provider(provider_id: str) -> dict[str, Any]:
    """Return a provider's models and capabilities."""
    registry = get_registry()
    provider = registry.get_optional(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")

    try:
        models = await provider.list_models()
        healthy = await provider.health_check()
    except Exception as exc:
        logger.warning("Provider '%s' error during detail fetch: %s", provider_id, exc)
        models = []
        healthy = False

    return {
        "provider_id": provider_id,
        "healthy": healthy,
        "models": [
            {
                "id": m.id,
                "name": m.name,
                "capabilities": m.capabilities.model_dump(mode="json") if m.capabilities else None,
            }
            for m in models
        ],
    }


@router.get("/{provider_id}/models", summary="List models for provider")
async def list_provider_models(provider_id: str) -> dict[str, Any]:
    """Return available models for a single provider."""
    registry = get_registry()
    provider = registry.get_optional(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")

    try:
        models = await provider.list_models()
    except Exception as exc:
        logger.warning("Could not list models for '%s': %s", provider_id, exc)
        models = []

    return {
        "provider_id": provider_id,
        "models": [m.model_dump(mode="json") for m in models],
        "count": len(models),
    }
