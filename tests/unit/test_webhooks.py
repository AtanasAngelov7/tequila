"""Unit tests for the Webhooks built-in plugin (Sprint 12)."""
from __future__ import annotations

import pytest

from app.auth.encryption import generate_key, init_encryption
from app.plugins.builtin.webhooks.plugin import (
    WebhooksPlugin,
    check_dedup,
    create_endpoint,
    delete_endpoint,
    get_endpoint,
    list_endpoints,
    validate_hmac_signature,
)


# ── Plugin lifecycle ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhooks_configure_and_activate():
    plugin = WebhooksPlugin()
    await plugin.configure({}, lambda *a: None)
    await plugin.activate()
    assert plugin._active is True
    await plugin.deactivate()
    assert plugin._active is False


@pytest.mark.asyncio
async def test_webhooks_get_tools_empty():
    plugin = WebhooksPlugin()
    await plugin.configure({}, lambda *a: None)
    tools = await plugin.get_tools()
    assert tools == []


@pytest.mark.asyncio
async def test_webhooks_health_inactive():
    plugin = WebhooksPlugin()
    await plugin.configure({}, lambda *a: None)
    result = await plugin.health_check()
    assert result.healthy is False


@pytest.mark.asyncio
async def test_webhooks_health_active():
    plugin = WebhooksPlugin()
    await plugin.configure({}, lambda *a: None)
    await plugin.activate()
    result = await plugin.health_check()
    assert result.healthy is True
    await plugin.deactivate()


@pytest.mark.asyncio
async def test_webhooks_test():
    plugin = WebhooksPlugin()
    await plugin.configure({}, lambda *a: None)
    result = await plugin.test()
    assert result.success is True


def test_webhooks_channel_adapter_spec():
    import asyncio
    plugin = WebhooksPlugin()
    spec = asyncio.get_event_loop().run_until_complete(plugin.get_channel_adapter())
    assert spec.channel_name == "webhooks"
    assert spec.supports_inbound is True
    assert spec.supports_outbound is False


# ── HMAC validation ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_hmac_valid():
    import hashlib, hmac as hmaclib
    payload = b'{"event": "test"}'
    secret = "my-secret"
    sig = "sha256=" + hmaclib.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    result = await validate_hmac_signature(payload, secret, sig)
    assert result is True


@pytest.mark.asyncio
async def test_validate_hmac_invalid():
    result = await validate_hmac_signature(b"payload", "secret", "sha256=badhash")
    assert result is False


# ── Dedup ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_dedup_first_time(migrated_db):
    init_encryption(generate_key())
    result = await check_dedup(migrated_db, "stripe", "evt_abc123")
    assert result is True


@pytest.mark.asyncio
async def test_check_dedup_duplicate(migrated_db):
    init_encryption(generate_key())
    await check_dedup(migrated_db, "stripe", "evt_dup")
    result = await check_dedup(migrated_db, "stripe", "evt_dup")
    assert result is False


@pytest.mark.asyncio
async def test_check_dedup_different_source(migrated_db):
    init_encryption(generate_key())
    await check_dedup(migrated_db, "source_a", "key1")
    # same key, different source — should NOT be flagged as duplicate
    result = await check_dedup(migrated_db, "source_b", "key1")
    assert result is True


# ── Endpoint CRUD ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_get_endpoint(migrated_db):
    init_encryption(generate_key())
    ep = await create_endpoint(migrated_db, "ep-001", "Test Endpoint", "session-xyz", secret="mypassword")
    assert ep["id"] == "ep-001"

    loaded = await get_endpoint(migrated_db, "ep-001")
    assert loaded is not None
    assert loaded["name"] == "Test Endpoint"
    assert loaded["session_key"] == "session-xyz"
    # Secret must not be stored in plaintext
    assert "mypassword" not in str(loaded.get("secret_hash", ""))


@pytest.mark.asyncio
async def test_list_endpoints(migrated_db):
    init_encryption(generate_key())
    await create_endpoint(migrated_db, "ep-a", "A", "sess-a")
    await create_endpoint(migrated_db, "ep-b", "B", "sess-b")
    endpoints = await list_endpoints(migrated_db)
    ids = {e["id"] for e in endpoints}
    assert {"ep-a", "ep-b"}.issubset(ids)


@pytest.mark.asyncio
async def test_delete_endpoint(migrated_db):
    init_encryption(generate_key())
    await create_endpoint(migrated_db, "ep-del", "Del", "sess-del")
    deleted = await delete_endpoint(migrated_db, "ep-del")
    assert deleted is True
    assert await get_endpoint(migrated_db, "ep-del") is None


@pytest.mark.asyncio
async def test_get_nonexistent_endpoint(migrated_db):
    result = await get_endpoint(migrated_db, "no-such-endpoint")
    assert result is None
