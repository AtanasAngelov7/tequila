"""Auth API — LLM provider key management (Sprint 12, §6.1).

Endpoints:
    GET    /api/auth/providers                   — list providers (key status)
    POST   /api/auth/providers/{provider}/key    — save API key
    DELETE /api/auth/providers/{provider}/key    — revoke API key
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.deps import require_gateway_token
from app.auth.providers import (
    KNOWN_PROVIDERS,
    get_provider_key,
    list_configured_providers,
    revoke_provider_key,
    save_provider_key,
)
from app.db.connection import get_app_db
from app.exceptions import NotFoundError, ValidationError

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/auth",
    tags=["auth"],
    dependencies=[Depends(require_gateway_token)],
)


class SaveKeyRequest(BaseModel):
    """Request body for saving an API key."""

    key: str = Field(..., min_length=1, description="The raw API key to store encrypted.")
    validate_on_save: bool = Field(
        default=False,
        description="If true, test the key against the provider before saving.",
    )


@router.get("/providers", response_model=list[dict])
async def list_providers() -> list[dict]:
    """List all supported LLM providers and whether a key is configured."""
    db = get_app_db()
    return await list_configured_providers(db)


@router.post("/providers/{provider}/key", status_code=204)
async def save_key(provider: str, body: SaveKeyRequest) -> None:
    """Encrypt and persist an API key for *provider*.

    The raw key is never stored — only the encrypted token is persisted.
    """
    if provider not in KNOWN_PROVIDERS:
        raise NotFoundError("Provider", provider)

    db = get_app_db()
    try:
        await save_provider_key(db, provider, body.key)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    logger.info("API key saved for provider %r.", provider)


@router.delete("/providers/{provider}/key", status_code=204)
async def revoke_key(provider: str) -> None:
    """Revoke and delete the stored API key for *provider*."""
    if provider not in KNOWN_PROVIDERS:
        raise NotFoundError("Provider", provider)

    db = get_app_db()
    await revoke_provider_key(db, provider)
    logger.info("API key revoked for provider %r.", provider)
