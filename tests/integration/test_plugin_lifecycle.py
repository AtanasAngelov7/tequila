"""Integration tests — plugin lifecycle via the full FastAPI application (Sprint 12)."""
from __future__ import annotations

import pytest


# ── Plugin API ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_plugins_empty(test_app):
    """GET /api/plugins returns empty list on fresh DB."""
    resp = await test_app.get("/api/plugins")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_install_webhooks_plugin(test_app):
    """POST /api/plugins installs the webhooks built-in."""
    resp = await test_app.post("/api/plugins", json={"plugin_id": "webhooks"})
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["plugin_id"] == "webhooks"
    assert data["status"] == "installed"


@pytest.mark.asyncio
async def test_get_plugin_after_install(test_app):
    """GET /api/plugins/{id} returns the installed plugin."""
    await test_app.post("/api/plugins", json={"plugin_id": "webhooks"})
    resp = await test_app.get("/api/plugins/webhooks")
    assert resp.status_code == 200
    data = resp.json()
    assert data["plugin_id"] == "webhooks"


@pytest.mark.asyncio
async def test_get_nonexistent_plugin_returns_404(test_app):
    resp = await test_app.get("/api/plugins/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_plugins_contains_installed(test_app):
    await test_app.post("/api/plugins", json={"plugin_id": "webhooks"})
    resp = await test_app.get("/api/plugins")
    assert resp.status_code == 200
    ids = [p["plugin_id"] for p in resp.json()]
    assert "webhooks" in ids


@pytest.mark.asyncio
async def test_plugin_health_endpoint(test_app):
    """GET /api/plugins/{id}/health returns health result."""
    resp = await test_app.get("/api/plugins/webhooks/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "healthy" in data


@pytest.mark.asyncio
async def test_plugin_test_endpoint(test_app):
    """POST /api/plugins/{id}/test returns test result."""
    resp = await test_app.post("/api/plugins/webhooks/test")
    assert resp.status_code == 200
    data = resp.json()
    assert "success" in data


@pytest.mark.asyncio
async def test_plugin_tools_endpoint(test_app):
    """GET /api/plugins/{id}/tools returns tools list."""
    resp = await test_app.get("/api/plugins/webhooks/tools")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_plugin_dependencies_endpoint(test_app):
    """GET /api/plugins/{id}/dependencies returns deps."""
    resp = await test_app.get("/api/plugins/webhooks/dependencies")
    assert resp.status_code == 200
    data = resp.json()
    assert "python_packages" in data


@pytest.mark.asyncio
async def test_delete_plugin(test_app):
    await test_app.post("/api/plugins", json={"plugin_id": "webhooks"})
    resp = await test_app.delete("/api/plugins/webhooks")
    assert resp.status_code == 204
    get_resp = await test_app.get("/api/plugins/webhooks")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_refresh_plugins(test_app):
    resp = await test_app.get("/api/plugins/refresh")
    assert resp.status_code == 200
    data = resp.json()
    assert "reloaded" in data


# ── Auth API ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_auth_providers(test_app):
    resp = await test_app.get("/api/auth/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    providers = {p["provider"] for p in data}
    assert {"openai", "anthropic", "ollama"}.issubset(providers)


@pytest.mark.asyncio
async def test_save_provider_key(test_app):
    resp = await test_app.post(
        "/api/auth/providers/openai/key",
        json={"key": "sk-test-12345", "validate_on_save": False},
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_list_providers_shows_configured_after_save(test_app):
    await test_app.post(
        "/api/auth/providers/openai/key",
        json={"key": "sk-test-123", "validate_on_save": False},
    )
    resp = await test_app.get("/api/auth/providers")
    data = resp.json()
    openai_info = next(p for p in data if p["provider"] == "openai")
    assert openai_info["configured"] is True


@pytest.mark.asyncio
async def test_delete_provider_key(test_app):
    await test_app.post(
        "/api/auth/providers/openai/key",
        json={"key": "sk-test", "validate_on_save": False},
    )
    resp = await test_app.delete("/api/auth/providers/openai/key")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_save_key_for_invalid_provider_returns_422(test_app):
    resp = await test_app.post(
        "/api/auth/providers/invalid_llm/key",
        json={"key": "somkey", "validate_on_save": False},
    )
    assert resp.status_code in (422, 400, 404)
