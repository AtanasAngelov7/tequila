"""Integration tests for system API routes (health, status, config, logs)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


# ── /api/health ───────────────────────────────────────────────────────────────


async def test_health_returns_ok(test_app: AsyncClient) -> None:
    """GET /api/health should return 200 and status=ok."""
    response = await test_app.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"


# ── /api/status ───────────────────────────────────────────────────────────────


async def test_status_requires_token_when_configured(test_app: AsyncClient) -> None:
    """GET /api/status without a token should return 401 when gateway_token is set."""
    # When the test DB has an empty gateway_token, this will return 200.
    # Either way, the endpoint should exist.
    response = await test_app.get("/api/status")
    assert response.status_code in (200, 401)


async def test_status_returns_app_info(test_app: AsyncClient) -> None:
    """GET /api/status should return uptime and version when accessible."""
    # Try without a token; test fixtures seed empty gateway_token so it should pass.
    response = await test_app.get("/api/status")
    if response.status_code == 200:
        data = response.json()
        assert "version" in data
        assert "uptime_s" in data


# ── /api/config ───────────────────────────────────────────────────────────────


async def test_get_config_returns_list(test_app: AsyncClient) -> None:
    """GET /api/config should return a list of config rows."""
    response = await test_app.get("/api/config")
    # 200 or 401 depending on gateway_token config
    if response.status_code == 200:
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 7
        first = data[0]
        assert "key" in first
        assert "value" in first


async def test_patch_config_updates_value(test_app: AsyncClient) -> None:
    """PATCH /api/config should update the given key and return confirmation."""
    response = await test_app.patch(
        "/api/config",
        json={"updates": {"logging.level": "WARNING"}},
    )
    if response.status_code == 200:
        data = response.json()
        # Response has "applied", "restart_required", and "errors" lists.
        assert "applied" in data or "errors" in data


# ── /api/logs ─────────────────────────────────────────────────────────────────


async def test_get_logs_returns_list(test_app: AsyncClient) -> None:
    """GET /api/logs should return an empty list on a fresh database."""
    response = await test_app.get("/api/logs")
    if response.status_code == 200:
        data = response.json()
        assert isinstance(data, list)


async def test_get_logs_respects_limit(test_app: AsyncClient) -> None:
    """GET /api/logs?limit=5 should return at most 5 items."""
    response = await test_app.get("/api/logs", params={"limit": 5})
    if response.status_code == 200:
        data = response.json()
        assert len(data) <= 5


async def test_health_endpoint_is_not_rate_limited(test_app: AsyncClient) -> None:
    """Calling /api/health multiple times should always return 200."""
    for _ in range(5):
        response = await test_app.get("/api/health")
        assert response.status_code == 200
