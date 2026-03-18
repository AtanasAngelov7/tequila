"""LLM provider authentication — API key management (Sprint 12, §6.1).

Credential lifecycle:
  1. UI calls ``POST /api/auth/providers/{provider}/key`` with raw key.
  2. ``save_provider_key()`` encrypts it using Fernet and stores it in
     ``plugin_credentials`` under ``plugin_id = "__auth__"``.
  3. At provider initialisation time, ``get_provider_key()`` retrieves and
     decrypts the key.  The raw key is never stored unencrypted.
  4. ``DELETE /api/auth/providers/{provider}/key`` clears the stored token.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.auth.encryption import decrypt_credential, encrypt_credential
from app.db.connection import write_transaction

logger = logging.getLogger(__name__)

# Auth credentials are stored in plugin_credentials under this plugin_id.
_AUTH_PLUGIN_ID = "__auth__"

# Known LLM provider IDs.
KNOWN_PROVIDERS = {"openai", "anthropic", "ollama"}


# ── Internal helpers ──────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _get_row(db: aiosqlite.Connection, credential_key: str) -> dict[str, Any] | None:
    async with db.execute(
        "SELECT plugin_id, credential_key, encrypted_value, created_at, updated_at "
        "FROM plugin_credentials WHERE plugin_id = ? AND credential_key = ?",
        (_AUTH_PLUGIN_ID, credential_key),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return dict(row)


# ── Public API ────────────────────────────────────────────────────────────────


async def save_provider_key(
    db: aiosqlite.Connection,
    provider: str,
    raw_key: str,
) -> None:
    """Encrypt and persist *raw_key* for *provider*.

    Overwrites any previously stored key for this provider.
    Raises ``ValueError`` if *provider* is not in ``KNOWN_PROVIDERS``.
    """
    if provider not in KNOWN_PROVIDERS:
        raise ValueError(f"Unknown provider {provider!r}. Valid: {sorted(KNOWN_PROVIDERS)}")
    if not raw_key or not raw_key.strip():
        raise ValueError("API key must not be empty.")

    encrypted = encrypt_credential(raw_key.strip())
    now = _now()
    credential_key = f"api_key:{provider}"

    async with write_transaction(db):
        await db.execute(
            """
            INSERT INTO plugin_credentials (plugin_id, credential_key, encrypted_value, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (plugin_id, credential_key) DO UPDATE
              SET encrypted_value = excluded.encrypted_value,
                  updated_at      = excluded.updated_at
            """,
            (_AUTH_PLUGIN_ID, credential_key, encrypted, now, now),
        )
    logger.info("Saved API key for provider %r.", provider)


async def get_provider_key(
    db: aiosqlite.Connection,
    provider: str,
) -> str | None:
    """Return the decrypted API key for *provider*, or ``None`` if not set."""
    credential_key = f"api_key:{provider}"
    row = await _get_row(db, credential_key)
    if row is None:
        return None
    try:
        return decrypt_credential(row["encrypted_value"])
    except ValueError:
        logger.warning("Stored API key for %r could not be decrypted — clearing it.", provider)
        await revoke_provider_key(db, provider)
        return None


async def revoke_provider_key(db: aiosqlite.Connection, provider: str) -> None:
    """Delete the stored API key for *provider*."""
    credential_key = f"api_key:{provider}"
    async with write_transaction(db):
        await db.execute(
            "DELETE FROM plugin_credentials WHERE plugin_id = ? AND credential_key = ?",
            (_AUTH_PLUGIN_ID, credential_key),
        )
    logger.info("Revoked API key for provider %r.", provider)


async def list_configured_providers(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    """Return all providers and whether they have a stored key.

    The key value is never returned — only its existence is reported.
    """
    # Build the full provider list with configured flag.
    async with db.execute(
        "SELECT credential_key FROM plugin_credentials WHERE plugin_id = ?",
        (_AUTH_PLUGIN_ID,),
    ) as cur:
        rows = await cur.fetchall()

    configured: set[str] = set()
    for row in rows:
        ck = row["credential_key"]
        if ck.startswith("api_key:"):
            configured.add(ck[len("api_key:"):])

    return [
        {
            "provider": p,
            "configured": p in configured,
            "key_type": "api_key",
        }
        for p in sorted(KNOWN_PROVIDERS)
    ]
