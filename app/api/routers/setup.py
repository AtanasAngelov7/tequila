"""First-run setup wizard endpoints (§15.1).

Exposes two endpoints that are only meaningful before the initial setup is
completed.  After the wizard writes ``setup.complete = true`` to the config
table the ``POST /api/setup`` route returns HTTP **404** and
``GET /api/setup/status`` reports ``setup_complete=true``.

No gateway-token auth is required on either endpoint — the user has not yet
configured one (and may not even know what value to use before setup).

### Routes

| Method | Path                  | Auth | Description                    |
|--------|-----------------------|------|--------------------------------|
| GET    | /api/setup/status     | None | Is setup complete?             |
| POST   | /api/setup            | None | Execute the setup wizard       |
| GET    | /api/setup/models     | None | List stub models per provider  |
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import get_config_dep
from app.config import ConfigStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/setup", tags=["setup"])

# ── Provider → model catalogue ────────────────────────────────────────────────
# Derives model lists from the live provider registries so choices are always
# up-to-date.  Only Ollama uses a static suggestion list (models are dynamic).

_OLLAMA_SUGGESTIONS: list[dict[str, str]] = [
    {"id": "llama3.3", "name": "Llama 3.3 (70B)"},
    {"id": "llama3.2", "name": "Llama 3.2 (3B)"},
    {"id": "mistral", "name": "Mistral 7B"},
    {"id": "gemma3", "name": "Gemma 3 (27B)"},
]


def _get_setup_models(provider: str) -> list[dict[str, str]] | None:
    """Return ``[{"id": ..., "name": ...}]`` entries for *provider*.

    Pulls from the live provider registries so model names stay current.
    Returns ``None`` for unrecognised providers.
    """
    if provider == "anthropic":
        from app.providers.anthropic import _ANTHROPIC_MODELS
        return [{"id": m.model_id, "name": m.display_name} for m in _ANTHROPIC_MODELS.values()]
    if provider == "openai":
        from app.providers.openai import _OPENAI_MODELS
        return [{"id": m.model_id, "name": m.display_name} for m in _OPENAI_MODELS.values()]
    if provider == "gemini":
        from app.providers.gemini import _GEMINI_MODELS
        return [{"id": m.model_id, "name": m.display_name} for m in _GEMINI_MODELS.values()]
    if provider == "ollama":
        return _OLLAMA_SUGGESTIONS
    return None


# ── Request / response models ─────────────────────────────────────────────────


class SetupStatusResponse(BaseModel):
    """Response for ``GET /api/setup/status``."""

    setup_complete: bool
    user_name: str
    provider: str
    default_model: str
    main_agent_id: str


class SetupRequest(BaseModel):
    """Body for ``POST /api/setup`` (§15.1)."""

    user_name: str
    provider: Literal["anthropic", "openai", "gemini", "ollama"]
    api_key: str | None = None
    """API key.  Required for ``anthropic``, ``openai``, and ``gemini`` when
    ``auth_mode`` is ``"api_key"``; omit for ``ollama`` or ``"web_session"``."""
    auth_mode: Literal["api_key", "web_session"] = "api_key"
    """How the user authenticated.  ``"web_session"`` skips the API-key
    requirement because a browser session was captured via
    ``SessionCaptureFlow`` instead."""
    oauth_code: str | None = None
    """Reserved for future OAuth providers — not used in Sprint 03."""
    default_model: str
    """Provider-qualified model ID, e.g. ``"anthropic:claude-sonnet-4-6"``."""
    agent_name: str = "Tequila"
    agent_persona: str | None = None
    """Optional free-text persona description stored for Sprint 04 soul generation."""


class SetupResponse(BaseModel):
    """Body returned by a successful ``POST /api/setup``."""

    success: bool
    main_agent_id: str
    message: str


class ModelListItem(BaseModel):
    id: str
    name: str


class ModelListResponse(BaseModel):
    provider: str
    models: list[ModelListItem]


class ValidationResult(BaseModel):
    valid: bool
    message: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _reload_provider(provider_id: str, api_key: str) -> None:
    """Instantiate and re-register *provider_id* with *api_key* in the live registry.

    Called after the setup wizard saves a key so turns work immediately without
    a server restart.  Failures are logged and swallowed — a restart will always
    fix the state.
    """
    try:
        from app.providers.registry import get_registry
        registry = get_registry()
        if provider_id == "anthropic":
            from app.providers.anthropic import AnthropicProvider
            registry.register(AnthropicProvider(api_key=api_key))
        elif provider_id == "openai":
            from app.providers.openai import OpenAIProvider
            registry.register(OpenAIProvider(api_key=api_key))
        elif provider_id == "gemini":
            from app.providers.gemini import GeminiProvider
            registry.register(GeminiProvider(api_key=api_key))
        # ollama never needs a key — nothing to do
    except Exception:
        logger.warning("_reload_provider: failed to re-register '%s' — restart may be required", provider_id, exc_info=True)


def _validate_api_key(
    provider: str,
    api_key: str | None,
    auth_mode: str = "api_key",
) -> ValidationResult:
    """Stub API-key validation.

    In Sprint 04 this will make a real provider call (e.g. list models).
    For now it applies minimal structural checks so the wizard returns
    meaningful error messages for obviously-wrong inputs.
    """
    if provider == "ollama" or auth_mode == "web_session":
        return ValidationResult(valid=True, message="No API key required.")

    if not api_key:
        return ValidationResult(valid=False, message="API key is required for this provider.")

    if provider == "anthropic" and not api_key.startswith("sk-ant-"):
        return ValidationResult(
            valid=False,
            message="Anthropic API keys start with 'sk-ant-'. Verify your key.",
        )

    if provider == "openai" and not api_key.startswith("sk-"):
        return ValidationResult(
            valid=False,
            message="OpenAI API keys start with 'sk-'. Verify your key.",
        )

    if provider == "gemini" and not api_key.startswith("AI"):
        return ValidationResult(
            valid=False,
            message="Google API keys typically start with 'AI'. Verify your key.",
        )

    return ValidationResult(valid=True, message="API key accepted.")


async def _create_agent(
    db: Any,
    agent_id: str,
    name: str,
    provider: str,
    default_model: str,
    persona: str | None,
) -> None:
    """Insert a minimal agent row into the ``agents`` table."""
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """
        INSERT INTO agents (agent_id, name, provider, default_model, persona, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
        """,
        (agent_id, name, provider, default_model, persona, now, now),
    )
    await db.commit()


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/status", response_model=SetupStatusResponse)
async def setup_status(
    config: ConfigStore = Depends(get_config_dep),
) -> SetupStatusResponse:
    """Return whether the setup wizard has been completed.

    The frontend checks this on every load to decide between the chart
    interface and the setup wizard.
    """
    return SetupStatusResponse(
        setup_complete=config.get("setup.complete", False),
        user_name=config.get("setup.user_name", ""),
        provider=config.get("setup.provider", ""),
        default_model=config.get("setup.default_model", ""),
        main_agent_id=config.get("setup.main_agent_id", ""),
    )


@router.get("/models/{provider}", response_model=ModelListResponse)
async def list_models(provider: str) -> ModelListResponse:
    """Return available models for *provider* from the live provider registries.

    Called from the model-selection step of the setup wizard to populate
    the dropdown without the user having to know exact model IDs.
    """
    models = _get_setup_models(provider)
    if models is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown provider '{provider}'. Choose from: anthropic, openai, gemini, ollama.",
        )
    return ModelListResponse(
        provider=provider,
        models=[ModelListItem(**m) for m in models],
    )


@router.post("", response_model=SetupResponse, status_code=201)
async def run_setup(
    body: SetupRequest,
    config: ConfigStore = Depends(get_config_dep),
) -> SetupResponse:
    """Execute the first-run setup wizard.

    Steps (§15.1):
    1. Guard — return 404 if setup is already complete.
    2. Validate API key (structural check; full validation in Sprint 04).
    3. Create main agent row in the ``agents`` table.
    4. Write setup config keys.

    After this call, ``GET /api/setup/status`` reports ``setup_complete=true``
    and subsequent calls here return 404.
    """
    # 1. Guard: setup already done → 404 the endpoint.
    if config.get("setup.complete", False):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Setup has already been completed.",
        )

    # 2. Validate API key.
    validation = _validate_api_key(body.provider, body.api_key, body.auth_mode)
    if not validation.valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=validation.message,
        )

    # 3. Create main agent.
    from app.db.connection import get_app_db
    db = get_app_db()

    agent_id = f"agent:{uuid.uuid4().hex[:12]}"
    default_model = body.default_model

    # Qualify model with provider prefix if not already qualified.
    if ":" not in default_model:
        default_model = f"{body.provider}:{default_model}"

    await _create_agent(
        db=db,
        agent_id=agent_id,
        name=body.agent_name,
        provider=body.provider,
        default_model=default_model,
        persona=body.agent_persona,
    )

    # 4. Write setup config keys (ConfigStore.set requires keys to already exist;
    #    they are seeded by migration 0003 so this call always succeeds).
    await config.set("setup.user_name", body.user_name)
    await config.set("setup.provider", body.provider)
    await config.set("setup.default_model", default_model)
    await config.set("setup.main_agent_id", agent_id)
    # Persist the API key through the encrypted credential store (not config table,
    # which has no provider key rows).
    if body.api_key and body.auth_mode == "api_key":
        from app.auth.providers import save_provider_key
        await save_provider_key(db, body.provider, body.api_key)
        # Re-register the provider in the live ProviderRegistry so it is
        # immediately usable without requiring a server restart.
        _reload_provider(body.provider, body.api_key)
    await config.set("setup.complete", True)

    logger.info(
        "Setup wizard completed",
        extra={
            "user_name": body.user_name,
            "provider": body.provider,
            "agent_id": agent_id,
        },
    )

    return SetupResponse(
        success=True,
        main_agent_id=agent_id,
        message=(
            f"Setup complete! Main agent '{body.agent_name}' created. "
            "Redirecting to chat..."
        ),
    )
