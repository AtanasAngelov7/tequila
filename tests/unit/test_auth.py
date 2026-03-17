"""Unit tests for auth encryption and provider key management (Sprint 12)."""
from __future__ import annotations

import pytest

from app.auth.encryption import decrypt_credential, encrypt_credential, generate_key, init_encryption


# ── Encryption tests ──────────────────────────────────────────────────────────


def test_generate_key_returns_base64_string() -> None:
    key = generate_key()
    assert isinstance(key, str)
    assert len(key) > 20


def test_init_and_roundtrip():
    key = generate_key()
    init_encryption(key)
    plain = "super-secret-api-key-12345"
    token = encrypt_credential(plain)
    assert token != plain
    assert decrypt_credential(token) == plain


def test_encrypt_different_each_time():
    key = generate_key()
    init_encryption(key)
    t1 = encrypt_credential("hello")
    t2 = encrypt_credential("hello")
    assert t1 != t2  # Fernet includes timestamp nonce


def test_decrypt_wrong_key_raises():
    init_encryption(generate_key())
    token = encrypt_credential("secret")

    # Re-init with a different key
    init_encryption(generate_key())
    with pytest.raises((ValueError, Exception)):
        decrypt_credential(token)


# ── Provider key tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_and_get_provider_key(migrated_db):
    key = generate_key()
    init_encryption(key)

    from app.auth.providers import save_provider_key, get_provider_key

    await save_provider_key(migrated_db, "openai", "sk-test-123")
    retrieved = await get_provider_key(migrated_db, "openai")
    assert retrieved == "sk-test-123"


@pytest.mark.asyncio
async def test_get_unconfigured_provider_returns_none(migrated_db):
    init_encryption(generate_key())
    from app.auth.providers import get_provider_key

    result = await get_provider_key(migrated_db, "openai")
    assert result is None


@pytest.mark.asyncio
async def test_revoke_provider_key(migrated_db):
    init_encryption(generate_key())
    from app.auth.providers import save_provider_key, get_provider_key, revoke_provider_key

    await save_provider_key(migrated_db, "anthropic", "sk-ant-xyz")
    await revoke_provider_key(migrated_db, "anthropic")
    assert await get_provider_key(migrated_db, "anthropic") is None


@pytest.mark.asyncio
async def test_list_configured_providers(migrated_db):
    init_encryption(generate_key())
    from app.auth.providers import save_provider_key, list_configured_providers

    await save_provider_key(migrated_db, "openai", "sk-test")
    providers = await list_configured_providers(migrated_db)
    configured = {p["provider"]: p["configured"] for p in providers}
    assert configured["openai"] is True
    assert configured["anthropic"] is False


@pytest.mark.asyncio
async def test_save_provider_key_invalid_provider(migrated_db):
    init_encryption(generate_key())
    from app.auth.providers import save_provider_key

    with pytest.raises(ValueError, match="Unknown provider"):
        await save_provider_key(migrated_db, "invalid_llm", "key")


@pytest.mark.asyncio
async def test_save_provider_key_empty_raises(migrated_db):
    init_encryption(generate_key())
    from app.auth.providers import save_provider_key

    with pytest.raises(ValueError):
        await save_provider_key(migrated_db, "openai", "")


@pytest.mark.asyncio
async def test_overwrite_provider_key(migrated_db):
    init_encryption(generate_key())
    from app.auth.providers import save_provider_key, get_provider_key

    await save_provider_key(migrated_db, "openai", "key-v1")
    await save_provider_key(migrated_db, "openai", "key-v2")
    assert await get_provider_key(migrated_db, "openai") == "key-v2"
