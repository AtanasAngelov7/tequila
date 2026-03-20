"""Integration tests for the Setup Wizard endpoints (Sprint 03, D1).

Covers:
- GET /api/setup/status — initial state (setup_complete = false)
- POST /api/setup — complete the wizard, creates agent
- POST /api/setup — guard: second call returns 404 after completion
- GET /api/setup/models/{provider} — lists current models per provider
- POST /api/setup — api_key validation errors
"""
from __future__ import annotations

import pytest


# ── GET /api/setup/status ─────────────────────────────────────────────────────


async def test_setup_status_initial(test_app):
    """Fresh database: setup is not complete."""
    resp = await test_app.get("/api/setup/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["setup_complete"] is False
    assert data["user_name"] == ""
    assert data["provider"] == ""


# ── GET /api/setup/models ─────────────────────────────────────────────────────


async def test_models_anthropic(test_app):
    """Anthropic model list returns current-gen models from the registry."""
    resp = await test_app.get("/api/setup/models/anthropic")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "anthropic"
    model_ids = [m["id"] for m in data["models"]]
    assert "claude-sonnet-4-6" in model_ids
    assert "claude-opus-4-6" in model_ids
    assert "claude-haiku-4-5" in model_ids
    # Legacy IDs must NOT be in the list (only in _LEGACY_ dict)
    assert "claude-sonnet-4-5" not in model_ids


async def test_models_openai(test_app):
    """OpenAI model list returns current-gen models from the registry."""
    resp = await test_app.get("/api/setup/models/openai")
    assert resp.status_code == 200
    model_ids = [m["id"] for m in resp.json()["models"]]
    assert "gpt-5.4" in model_ids
    assert "gpt-5.4-mini" in model_ids
    assert "gpt-4o" not in model_ids


async def test_models_gemini(test_app):
    """Gemini model list is now supported (was missing before Sprint 19)."""
    resp = await test_app.get("/api/setup/models/gemini")
    assert resp.status_code == 200
    model_ids = [m["id"] for m in resp.json()["models"]]
    assert "gemini-2.5-pro" in model_ids
    assert "gemini-2.5-flash" in model_ids


async def test_models_ollama(test_app):
    """Ollama suggestion list returns at least one model."""
    resp = await test_app.get("/api/setup/models/ollama")
    assert resp.status_code == 200
    assert len(resp.json()["models"]) > 0


async def test_models_unknown_provider(test_app):
    """Unknown provider returns 404."""
    resp = await test_app.get("/api/setup/models/nonexistent")
    assert resp.status_code == 404


# ── POST /api/setup ───────────────────────────────────────────────────────────


async def test_setup_wizard_anthropic_success(test_app):
    """Complete setup with Anthropic — agent created and config written."""
    resp = await test_app.post(
        "/api/setup",
        json={
            "user_name": "Alice",
            "provider": "anthropic",
            "api_key": "sk-ant-test-key",
            "default_model": "claude-sonnet-4-6",
            "agent_name": "Tequila",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["success"] is True
    assert data["main_agent_id"].startswith("agent:")


async def test_setup_wizard_updates_status(test_app):
    """After setup completes, GET /api/setup/status reports complete."""
    await test_app.post(
        "/api/setup",
        json={
            "user_name": "Bob",
            "provider": "anthropic",
            "api_key": "sk-ant-validkey",
            "default_model": "claude-haiku-4-5",
            "agent_name": "Helper",
        },
    )
    resp = await test_app.get("/api/setup/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["setup_complete"] is True
    assert data["user_name"] == "Bob"
    assert data["provider"] == "anthropic"
    assert data["main_agent_id"].startswith("agent:")


async def test_setup_wizard_with_ollama_no_key(test_app):
    """Ollama provider doesn't require an API key."""
    resp = await test_app.post(
        "/api/setup",
        json={
            "user_name": "Charlie",
            "provider": "ollama",
            "api_key": None,
            "default_model": "llama3.3",
            "agent_name": "Llama Helper",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["success"] is True


async def test_setup_wizard_with_openai(test_app):
    """OpenAI setup works with valid key format."""
    resp = await test_app.post(
        "/api/setup",
        json={
            "user_name": "Dave",
            "provider": "openai",
            "api_key": "sk-test-validkey",
            "default_model": "gpt-5.4",
            "agent_name": "GPT Assistant",
        },
    )
    assert resp.status_code == 201


async def test_setup_wizard_model_qualified(test_app):
    """default_model is qualified with provider prefix when not already qualified."""
    resp = await test_app.post(
        "/api/setup",
        json={
            "user_name": "Eve",
            "provider": "anthropic",
            "api_key": "sk-ant-test",
            "default_model": "claude-sonnet-4-6",  # not yet prefixed
            "agent_name": "Tequila",
        },
    )
    assert resp.status_code == 201
    # Status should show qualified model
    status = await test_app.get("/api/setup/status")
    assert status.json()["default_model"] == "anthropic:claude-sonnet-4-6"


async def test_setup_wizard_model_already_qualified(test_app):
    """If default_model already contains provider prefix, it's kept as-is."""
    resp = await test_app.post(
        "/api/setup",
        json={
            "user_name": "Frank",
            "provider": "anthropic",
            "api_key": "sk-ant-test",
            "default_model": "anthropic:claude-opus-4-6",
            "agent_name": "Tequila",
        },
    )
    assert resp.status_code == 201
    status = await test_app.get("/api/setup/status")
    assert status.json()["default_model"] == "anthropic:claude-opus-4-6"


# ── Guard: second POST /api/setup returns 404 ─────────────────────────────────


async def test_setup_wizard_blocked_after_completion(test_app):
    """Once setup is complete, POST /api/setup returns 404."""
    await test_app.post(
        "/api/setup",
        json={
            "user_name": "Grace",
            "provider": "ollama",
            "api_key": None,
            "default_model": "llama3.2",
            "agent_name": "Tequila",
        },
    )
    # Second call should be blocked
    resp = await test_app.post(
        "/api/setup",
        json={
            "user_name": "Grace2",
            "provider": "ollama",
            "api_key": None,
            "default_model": "llama3.2",
            "agent_name": "Tequila",
        },
    )
    assert resp.status_code == 404


# ── Bad API key validation ─────────────────────────────────────────────────────


async def test_setup_wizard_anthropic_bad_key(test_app):
    """Bad Anthropic key format returns 422."""
    resp = await test_app.post(
        "/api/setup",
        json={
            "user_name": "Alice",
            "provider": "anthropic",
            "api_key": "not-an-anthropic-key",
            "default_model": "claude-sonnet-4-6",
            "agent_name": "Tequila",
        },
    )
    assert resp.status_code == 422


async def test_setup_wizard_openai_bad_key(test_app):
    """Bad OpenAI key format returns 422."""
    resp = await test_app.post(
        "/api/setup",
        json={
            "user_name": "Alice",
            "provider": "openai",
            "api_key": "not-an-openai-key",
            "default_model": "gpt-5.4",
            "agent_name": "Tequila",
        },
    )
    assert resp.status_code == 422


async def test_setup_wizard_missing_key(test_app):
    """Missing API key for non-Ollama provider returns 422 when using api_key auth mode."""
    resp = await test_app.post(
        "/api/setup",
        json={
            "user_name": "Alice",
            "provider": "anthropic",
            "api_key": None,
            "auth_mode": "api_key",
            "default_model": "claude-sonnet-4-6",
            "agent_name": "Tequila",
        },
    )
    assert resp.status_code == 422


async def test_setup_wizard_web_session_no_key_required(test_app):
    """web_session auth mode succeeds without an API key (browser session captured separately)."""
    resp = await test_app.post(
        "/api/setup",
        json={
            "user_name": "Heidi",
            "provider": "anthropic",
            "api_key": None,
            "auth_mode": "web_session",
            "default_model": "claude-sonnet-4-6",
            "agent_name": "Tequila",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["success"] is True
