"""System-level API endpoints — health, status, and configuration (§13.2, §13.3, §14.4).

### Routes

| Method | Path          | Auth          | Response            |
|--------|---------------|---------------|---------------------|
| GET    | /api/health   | None          | HealthResponse      |
| GET    | /api/status   | Gateway token | SystemStatus        |
| GET    | /api/config   | Gateway token | list[ConfigRow]     |
| PATCH  | /api/config   | Gateway token | ConfigPatchResult   |
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import get_config_dep, require_gateway_token
from app.config import ConfigStore
from app.constants import APP_NAME, APP_VERSION
from app.exceptions import ConfigKeyNotFoundError, ConfigValidationError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])

# ── startup time (set by create_app lifespan) ─────────────────────────────────

_startup_time: float = time.monotonic()
_started_at: datetime = datetime.now(timezone.utc)


def record_startup_time() -> None:
    """Call once at application startup to anchor the uptime counter."""
    global _startup_time, _started_at  # noqa: PLW0603
    _startup_time = time.monotonic()
    _started_at = datetime.now(timezone.utc)


# ── Response models ───────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    """Response for ``GET /api/health``."""

    status: str
    """Always ``"ok"`` when the server is reachable."""

    app: str
    """Application name."""

    version: str
    """Application semantic version."""

    uptime_s: float
    """Seconds the process has been running."""


class ProviderStatus(BaseModel):
    """Status for a single LLM provider (§13.3)."""

    provider_id: str
    available: bool
    circuit_state: str = "closed"
    model_count: int = 0
    last_error: str | None = None


class PluginStatus(BaseModel):
    """Status for a single plugin (§13.3)."""

    plugin_id: str
    status: str
    healthy: bool | None = None
    last_error: str | None = None


class SystemStatus(BaseModel):
    """Extended status returned by ``GET /api/status`` (§13.3)."""

    status: str
    """``"ok"`` or ``"degraded"``."""

    app: str
    version: str
    uptime_s: float
    started_at: str
    """ISO-8601 UTC datetime when the process started."""

    # ── Providers ─────────────────────────────────────────────────────────
    providers: list[ProviderStatus]

    # ── Plugins ───────────────────────────────────────────────────────────
    plugins: list[PluginStatus]

    # ── Database ──────────────────────────────────────────────────────────
    db_ok: bool
    db_size_mb: float
    db_wal_size_mb: float

    # ── Sessions ──────────────────────────────────────────────────────────
    active_session_count: int
    active_turn_count: int

    # ── Memory (stub) ─────────────────────────────────────────────────────
    memory_extract_count: int
    entity_count: int
    embedding_index_status: str

    # ── Scheduler (stub) ──────────────────────────────────────────────────
    scheduler_status: str
    pending_jobs: int

    # ── Config ────────────────────────────────────────────────────────────
    config_keys: int
    """Number of config rows loaded in the in-memory cache."""


class ConfigRow(BaseModel):
    """One row from the ``config`` table."""

    key: str
    value: str
    """Raw JSON-encoded value as stored in the database."""

    value_type: str
    category: str
    description: str | None
    default_val: str | None
    requires_restart: bool


class ConfigPatchBody(BaseModel):
    """Body for ``PATCH /api/config``."""

    updates: dict[str, Any]
    """Dict of ``{key: new_value}`` pairs to apply."""


class ConfigPatchResult(BaseModel):
    """Result of a ``PATCH /api/config`` request."""

    applied: list[str]
    """Keys that were successfully updated and took effect immediately."""

    restart_required: list[str]
    """Keys that were updated but require a process restart to take effect."""

    errors: dict[str, str]
    """Keys that failed validation — maps key → error message."""


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return a lightweight health-check response (no auth required)."""
    return HealthResponse(
        status="ok",
        app=APP_NAME,
        version=APP_VERSION,
        uptime_s=round(time.monotonic() - _startup_time, 2),
    )


@router.get(
    "/api/status",
    response_model=SystemStatus,
    dependencies=[Depends(require_gateway_token)],
)
async def system_status(
    config: ConfigStore = Depends(get_config_dep),
) -> SystemStatus:
    """Return extended system status (requires gateway token, §13.3)."""
    from app.db.connection import get_app_db
    from app.paths import db_path

    db_ok = True
    db_size_mb = 0.0
    db_wal_size_mb = 0.0
    active_session_count = 0
    active_turn_count = 0

    # ── DB health + sizes ─────────────────────────────────────────────────
    try:
        db = get_app_db()
        await db.execute("SELECT 1")
        db_file = db_path()
        db_wal_file = db_file.with_suffix(".db-wal")
        if db_file.exists():
            db_size_mb = round(os.path.getsize(db_file) / (1024 * 1024), 3)
        if db_wal_file.exists():
            db_wal_size_mb = round(os.path.getsize(db_wal_file) / (1024 * 1024), 3)
    except Exception:
        db_ok = False

    # ── Active session count ──────────────────────────────────────────────
    try:
        db = get_app_db()
        async with db.execute(
            "SELECT COUNT(*) FROM sessions WHERE status = 'active'"
        ) as cur:
            row = await cur.fetchone()
            if row:
                active_session_count = row[0]
    except Exception:
        pass

    # ── Active turn count (in-memory turn queues) ─────────────────────────
    try:
        from app.sessions.store import active_turn_count
        active_turn_count = active_turn_count()
    except Exception:
        pass

    overall_status = "ok" if db_ok else "degraded"

    # ── Provider health + circuit breaker states (Sprint 07) ──────────────
    provider_statuses: list[ProviderStatus] = []
    try:
        from app.providers.circuit_breaker import get_all_circuit_breakers
        from app.providers.registry import get_registry as get_provider_registry

        registry = get_provider_registry()
        all_cbs = get_all_circuit_breakers()
        all_providers = registry.list_providers()

        for provider in all_providers:
            provider_id = provider.provider_id
            cb = all_cbs.get(provider_id)
            circuit_state = cb.state.value if cb else "closed"
            try:
                models = await provider.list_models()
                model_count = len(models)
                available = True
            except Exception as provider_exc:
                model_count = 0
                available = False
                if circuit_state == "closed" and cb:
                    circuit_state = cb.state.value

            if circuit_state in ("open",):
                overall_status = "degraded"

            provider_statuses.append(ProviderStatus(
                provider_id=provider_id,
                available=available,
                circuit_state=circuit_state,
                model_count=model_count,
            ))
    except Exception:
        logger.warning("Failed to load provider registry for status", exc_info=True)

    return SystemStatus(
        status=overall_status,
        app=APP_NAME,
        version=APP_VERSION,
        uptime_s=round(time.monotonic() - _startup_time, 2),
        started_at=_started_at.isoformat(),
        providers=provider_statuses,
        plugins=[],            # stub — implemented in Sprint 06
        db_ok=db_ok,
        db_size_mb=db_size_mb,
        db_wal_size_mb=db_wal_size_mb,
        active_session_count=active_session_count,
        active_turn_count=active_turn_count,
        memory_extract_count=0,    # stub — Sprint 05
        entity_count=0,            # stub — Sprint 05
        embedding_index_status="ready",  # stub
        scheduler_status="stopped",      # stub — Sprint 07
        pending_jobs=0,
        config_keys=config.key_count(),
    )


@router.get(
    "/api/config",
    response_model=list[ConfigRow],
    dependencies=[Depends(require_gateway_token)],
)
async def get_config(
    category: str | None = None,
    config: ConfigStore = Depends(get_config_dep),
) -> list[dict[str, Any]]:
    """Return all config rows, optionally filtered by ``category``."""
    return await config.all(category=category)


@router.patch(
    "/api/config",
    response_model=ConfigPatchResult,
    dependencies=[Depends(require_gateway_token)],
)
async def patch_config(
    body: ConfigPatchBody,
    config: ConfigStore = Depends(get_config_dep),
) -> ConfigPatchResult:
    """Apply partial config updates.

    Returns lists of applied keys, restart-required keys, and any errors.
    """
    applied: list[str] = []
    restart_required: list[str] = []
    errors: dict[str, str] = {}

    for key, value in body.updates.items():
        try:
            hot = await config.set(key, value)
            if hot:
                applied.append(key)
            else:
                restart_required.append(key)
        except ConfigKeyNotFoundError as exc:
            errors[key] = str(exc)
        except ConfigValidationError as exc:
            errors[key] = str(exc)
        except Exception as exc:
            errors[key] = f"Unexpected error: {exc}"

    return ConfigPatchResult(
        applied=applied,
        restart_required=restart_required,
        errors=errors,
    )
