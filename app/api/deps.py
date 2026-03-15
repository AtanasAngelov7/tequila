"""FastAPI dependency providers for Tequila v2 (§2.1, §13.1).

All injectable dependencies are declared here.  Route functions must use
``Depends(...)`` to obtain DB connections, config stores, and auth — never
instantiate them inline.

New dependencies should be added to this module, not defined ad-hoc inside
individual router files.
"""
from __future__ import annotations

import hmac
import logging
from typing import AsyncGenerator

import aiosqlite
from fastapi import Depends, Header, HTTPException, Query, status

from app.config import ConfigStore, get_settings
from app.constants import GATEWAY_TOKEN_HEADER
from app.db.connection import get_app_db
from app.exceptions import GatewayTokenRequired

logger = logging.getLogger(__name__)

# ── Database dependencies ─────────────────────────────────────────────────────

# Module-level config store singleton (set during app lifespan startup).
_config_store: ConfigStore | None = None


def set_config_store(store: ConfigStore) -> None:
    """Store the ``ConfigStore`` singleton (called during app lifespan startup)."""
    global _config_store  # noqa: PLW0603
    _config_store = store


async def get_db_dep() -> aiosqlite.Connection:
    """Yield the application-lifetime read-only DB connection.

    WAL mode allows multiple concurrent readers, so no lock is acquired.
    """
    return get_app_db()


async def get_write_db_dep() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Yield the application-lifetime DB connection wrapped in a write lock.

    The lock is acquired for the duration of the request handler and released
    automatically.  Only one write handler runs at a time per process.
    """
    from app.db.connection import get_write_db, _app_db_path  # local import

    if _app_db_path is None:
        raise RuntimeError("Database not initialised.")
    async with get_write_db() as conn:
        yield conn


# ── Config dependency ─────────────────────────────────────────────────────────


def get_config_dep() -> ConfigStore:
    """Return the app-lifetime ``ConfigStore`` singleton.

    Raises:
        RuntimeError: If the config store has not been initialised yet.
    """
    if _config_store is None:
        raise RuntimeError("ConfigStore not initialised.  Check app lifespan.")
    return _config_store


# ── Auth dependency ───────────────────────────────────────────────────────────


async def require_gateway_token(
    x_gateway_token: str | None = Header(default=None, alias=GATEWAY_TOKEN_HEADER),
) -> None:
    """Validate the ``X-Gateway-Token`` header.

    If ``ServerSettings.gateway_token`` is empty, authentication is disabled
    (local development mode) and this dependency is a no-op.

    Raises:
        GatewayTokenRequired: When a token is configured but missing/wrong.
    """
    settings = get_settings()
    expected = settings.gateway_token
    if not expected:
        # Token-less local dev mode — skip auth.
        return
    if not hmac.compare_digest(x_gateway_token or "", expected):
        raise GatewayTokenRequired()


async def require_ws_gateway_token(
    token: str | None = Query(default=None),
) -> None:
    """Validate the ``?token=`` query parameter for WebSocket connections.

    Browsers cannot set custom headers on WebSocket upgrade requests, so the
    gateway token must be passed as a query parameter instead.

    If ``ServerSettings.gateway_token`` is empty, authentication is disabled
    (local development mode) and this dependency is a no-op.

    Raises:
        GatewayTokenRequired: When a token is configured but missing/wrong.
    """
    settings = get_settings()
    expected = settings.gateway_token
    if not expected:
        # Token-less local dev mode — skip auth.
        return
    if not hmac.compare_digest(token or "", expected):
        raise GatewayTokenRequired()
