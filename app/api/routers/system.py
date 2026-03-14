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

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import get_config_dep, require_gateway_token
from app.config import ConfigStore
from app.constants import APP_NAME, APP_VERSION
from app.exceptions import ConfigKeyNotFoundError, ConfigValidationError

router = APIRouter(tags=["system"])

# ── startup time (set by create_app lifespan) ─────────────────────────────────

_startup_time: float = time.monotonic()


def record_startup_time() -> None:
    """Call once at application startup to anchor the uptime counter."""
    global _startup_time  # noqa: PLW0603
    _startup_time = time.monotonic()


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


class SystemStatus(BaseModel):
    """Extended status returned by ``GET /api/status`` (§13.3)."""

    status: str
    """``"ok"`` or ``"degraded"``."""

    app: str
    version: str
    uptime_s: float

    db_ok: bool
    """Whether the database connection is healthy."""

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
    """Return extended system status (requires gateway token)."""
    from app.db.connection import get_app_db

    db_ok = True
    try:
        db = get_app_db()
        await db.execute("SELECT 1")
    except Exception:
        db_ok = False

    return SystemStatus(
        status="ok" if db_ok else "degraded",
        app=APP_NAME,
        version=APP_VERSION,
        uptime_s=round(time.monotonic() - _startup_time, 2),
        db_ok=db_ok,
        config_keys=len(config._cache),
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
