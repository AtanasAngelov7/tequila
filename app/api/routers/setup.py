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

# ── Provider→model stub catalogue ────────────────────────────────────────────
# Full provider integration (circuit breaker, live model listing, credential
# validation) is implemented in Sprint 04.  For now we return a static list
# so the wizard can be exercised end-to-end with stub responses.

_STUB_MODELS: dict[str, list[dict[str, str]]] = {
    "anthropic": [
        {"id": "claude-opus-4-5", "name": "Claude Opus 4.5 (most capable)"},
        {"id": "claude-sonnet-4-5", "name": "Claude Sonnet 4.5 (balanced)"},
        {"id": "claude-haiku-3-5", "name": "Claude Haiku 3.5 (fastest)"},
    ],
    "openai": [
        {"id": "gpt-4o", "name": "GPT-4o (most capable)"},
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini (fast & cheap)"},
        {"id": "o3-mini", "name": "o3-mini (reasoning)"},
    ],
    "ollama": [
        {"id": "llama3.3", "name": "Llama 3.3 (70B)"},
        {"id": "llama3.2", "name": "Llama 3.2 (3B)"},
        {"id": "mistral", "name": "Mistral 7B"},
        {"id": "gemma3", "name": "Gemma 3 (27B)"},
    ],
}


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
    provider: Literal["anthropic", "openai", "ollama"]
    api_key: str | None = None
    """API key.  Required for ``anthropic`` and ``openai``; omit for ``ollama``."""
    oauth_code: str | None = None
    """Reserved for future OAuth providers — not used in Sprint 03."""
    default_model: str
    """Provider-qualified model ID, e.g. ``"anthropic:claude-sonnet-4-5"``."""
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


def _validate_api_key(provider: str, api_key: str | None) -> ValidationResult:
    """Stub API-key validation.

    In Sprint 04 this will make a real provider call (e.g. list models).
    For now it applies minimal structural checks so the wizard returns
    meaningful error messages for obviously-wrong inputs.
    """
    if provider == "ollama":
        return ValidationResult(valid=True, message="Ollama runs locally — no key required.")

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
    """Return available models for a provider (stub — replaced in Sprint 04).

    Called from the model-selection step of the setup wizard to populate
    the dropdown without the user having to know exact model IDs.
    """
    if provider not in _STUB_MODELS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown provider '{provider}'. Choose from: {list(_STUB_MODELS)}",
        )
    return ModelListResponse(
        provider=provider,
        models=[ModelListItem(**m) for m in _STUB_MODELS[provider]],
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
    validation = _validate_api_key(body.provider, body.api_key)
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
    # TD-324: Persist the API key so the provider can use it.
    if body.api_key:
        await config.set(f"provider.{body.provider}.api_key", body.api_key)
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
