"""LLM provider authentication — API key and session token management (Sprint 12 + 17 + 18, §6.1).

Credential lifecycle (API keys):
  1. UI calls ``POST /api/auth/providers/{provider}/key`` with raw key.
  2. ``save_provider_key()`` encrypts it using Fernet and stores it in
     ``plugin_credentials`` under ``plugin_id = "__auth__"``.
  3. At provider initialisation time, ``get_provider_key()`` retrieves and
     decrypts the key.  The raw key is never stored unencrypted.
  4. ``DELETE /api/auth/providers/{provider}/key`` clears the stored token.

Session token lifecycle (Sprint 17):
  - Mirrors the API key lifecycle but uses credential_key = ``session_token:{provider}``
    and credential_type = ``session_token``.
  - The three web providers (``openai_web``, ``anthropic_web``, ``gemini_web``) use
    session tokens captured from the provider's consumer web app.

OAuth token lifecycle (Sprint 18):
  - OpenAI and Anthropic web sessions now use proper OAuth 2.0 PKCE flows.
  - Tokens stored under credential_key = ``oauth_tokens:{provider}`` as encrypted JSON.
  - JSON schema: ``{access, refresh, expires, account_id?}``.
  - ``get_session_status()`` prefers OAuth tokens over legacy session tokens.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal

import aiosqlite

from app.auth.encryption import decrypt_credential, encrypt_credential
from app.db.connection import write_transaction

logger = logging.getLogger(__name__)

# Auth credentials are stored in plugin_credentials under this plugin_id.
_AUTH_PLUGIN_ID = "__auth__"

# Known LLM provider IDs (API-key based).
KNOWN_PROVIDERS = {"openai", "anthropic", "ollama", "gemini",
                   "openai_web", "anthropic_web", "gemini_web"}

# Subset of KNOWN_PROVIDERS that use web session tokens instead of API keys.
_SESSION_PROVIDERS = {"openai_web", "anthropic_web", "gemini_web"}


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
        logger.warning(
            "Stored API key for %r could not be decrypted "
            "(encryption key mismatch). Key retained in DB — "
            "re-enter the key or fix TEQUILA_SECRET_KEY.",
            provider,
        )
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
    """Return all providers and whether they have a stored credential.

    For API-key providers: reports ``configured`` if a key exists.
    For web-session providers: reports ``configured`` if a session token exists.
    The actual credential value is never returned — only its existence.
    """
    async with db.execute(
        "SELECT credential_key FROM plugin_credentials WHERE plugin_id = ?",
        (_AUTH_PLUGIN_ID,),
    ) as cur:
        rows = await cur.fetchall()

    configured_api_keys: set[str] = set()
    configured_sessions: set[str] = set()
    for row in rows:
        ck = row["credential_key"]
        if ck.startswith("api_key:"):
            configured_api_keys.add(ck[len("api_key:"):])
        elif ck.startswith("session_token:"):
            configured_sessions.add(ck[len("session_token:"):])
        elif ck.startswith("oauth_tokens:"):
            configured_sessions.add(ck[len("oauth_tokens:"):])

    result = []
    for p in sorted(KNOWN_PROVIDERS):
        if p in _SESSION_PROVIDERS:
            result.append(
                {
                    "provider": p,
                    "configured": p in configured_sessions,
                    "credential_type": "session_token" if p in configured_sessions else None,
                }
            )
        else:
            result.append(
                {
                    "provider": p,
                    "configured": p in configured_api_keys,
                    "credential_type": "api_key" if p in configured_api_keys else None,
                }
            )
    return result


# ── Session token functions (Sprint 17) ───────────────────────────────────────


async def save_session_token(
    db: aiosqlite.Connection,
    provider: str,
    raw_token: str,
    *,
    method: str = "manual_paste",
) -> None:
    """Encrypt and persist a web session token for *provider*.

    *method* is one of ``"browser_capture"`` or ``"manual_paste"`` and is
    stored as JSON metadata in a sibling row.

    Raises ``ValueError`` if *provider* is not in ``_SESSION_PROVIDERS`` or
    if *raw_token* is empty.
    """
    if provider not in _SESSION_PROVIDERS:
        raise ValueError(
            f"Unknown session provider {provider!r}. "
            f"Valid: {sorted(_SESSION_PROVIDERS)}"
        )
    if not raw_token or not raw_token.strip():
        raise ValueError("Session token must not be empty.")

    encrypted = encrypt_credential(raw_token.strip())
    now = _now()
    credential_key = f"session_token:{provider}"
    meta_key = f"session_meta:{provider}"
    meta_value = json.dumps({"method": method, "captured_at": now})

    async with write_transaction(db):
        await db.execute(
            """
            INSERT INTO plugin_credentials
                (plugin_id, credential_key, encrypted_value, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (plugin_id, credential_key) DO UPDATE
              SET encrypted_value = excluded.encrypted_value,
                  updated_at      = excluded.updated_at
            """,
            (_AUTH_PLUGIN_ID, credential_key, encrypted, now, now),
        )
        # Store capture metadata as plain (non-secret) JSON in a sibling row.
        await db.execute(
            """
            INSERT INTO plugin_credentials
                (plugin_id, credential_key, encrypted_value, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (plugin_id, credential_key) DO UPDATE
              SET encrypted_value = excluded.encrypted_value,
                  updated_at      = excluded.updated_at
            """,
            (_AUTH_PLUGIN_ID, meta_key, meta_value, now, now),
        )
    logger.info("Saved session token for provider %r (method=%r).", provider, method)


async def get_session_token(
    db: aiosqlite.Connection,
    provider: str,
) -> str | None:
    """Return the decrypted session token for *provider*, or ``None`` if not set."""
    credential_key = f"session_token:{provider}"
    row = await _get_row(db, credential_key)
    if row is None:
        return None
    try:
        return decrypt_credential(row["encrypted_value"])
    except ValueError:
        logger.warning(
            "Stored session token for %r could not be decrypted — clearing it.", provider
        )
        await revoke_session_token(db, provider)
        return None


async def revoke_session_token(db: aiosqlite.Connection, provider: str) -> None:
    """Delete the stored session token and metadata for *provider*."""
    credential_key = f"session_token:{provider}"
    meta_key = f"session_meta:{provider}"
    async with write_transaction(db):
        await db.execute(
            "DELETE FROM plugin_credentials WHERE plugin_id = ? AND credential_key IN (?, ?)",
            (_AUTH_PLUGIN_ID, credential_key, meta_key),
        )
    logger.info("Revoked session token for provider %r.", provider)


async def get_session_status(
    db: aiosqlite.Connection,
    provider: str,
) -> dict[str, Any]:
    """Return ``{connected, method, captured_at, account_id}`` for *provider*.

    Prefers OAuth tokens (Sprint 18) over legacy session tokens (Sprint 17).
    ``connected`` is ``True`` if either is present.
    """
    # Check OAuth tokens first (Sprint 18)
    oauth_row = await _get_row(db, f"oauth_tokens:{provider}")
    if oauth_row is not None:
        try:
            tokens = json.loads(decrypt_credential(oauth_row["encrypted_value"]))
            return {
                "connected": True,
                "method": "oauth",
                "captured_at": oauth_row.get("updated_at"),
                "account_id": tokens.get("account_id"),
            }
        except Exception:
            pass

    # Fall back to legacy session tokens (Sprint 17)
    credential_key = f"session_token:{provider}"
    token_row = await _get_row(db, credential_key)
    if token_row is None:
        return {"connected": False, "method": None, "captured_at": None, "account_id": None}

    # Read metadata (best-effort — non-critical)
    meta_key = f"session_meta:{provider}"
    meta_row = await _get_row(db, meta_key)
    method: str | None = None
    captured_at: str | None = None
    if meta_row:
        try:
            meta = json.loads(meta_row["encrypted_value"])
            method = meta.get("method")
            captured_at = meta.get("captured_at")
        except Exception:
            pass

    return {"connected": True, "method": method, "captured_at": captured_at, "account_id": None}


async def get_credential_type(
    db: aiosqlite.Connection,
    provider: str,
) -> Literal["api_key", "session_token", "oauth"] | None:
    """Return the credential type stored for *provider*, or ``None`` if not configured."""
    # Check API key first
    if await _get_row(db, f"api_key:{provider}") is not None:
        return "api_key"
    # Check OAuth tokens (Sprint 18)
    if await _get_row(db, f"oauth_tokens:{provider}") is not None:
        return "oauth"
    # Check legacy session token
    if await _get_row(db, f"session_token:{provider}") is not None:
        return "session_token"
    return None


# ── OAuth token functions (Sprint 18) ─────────────────────────────────────────


async def save_oauth_tokens(
    db: aiosqlite.Connection,
    provider: str,
    tokens: dict,
) -> None:
    """Encrypt and persist OAuth tokens for *provider*.

    *tokens* must contain ``access``, ``refresh``, and ``expires``.  An
    optional ``account_id`` field is preserved if present.

    Raises ``ValueError`` if *provider* is not in ``_SESSION_PROVIDERS``.
    """
    if provider not in _SESSION_PROVIDERS:
        raise ValueError(
            f"Unknown session provider {provider!r}. "
            f"Valid: {sorted(_SESSION_PROVIDERS)}"
        )
    now = _now()
    credential_key = f"oauth_tokens:{provider}"
    encrypted = encrypt_credential(json.dumps(tokens))

    async with write_transaction(db):
        await db.execute(
            """
            INSERT INTO plugin_credentials
                (plugin_id, credential_key, encrypted_value, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (plugin_id, credential_key) DO UPDATE
              SET encrypted_value = excluded.encrypted_value,
                  updated_at      = excluded.updated_at
            """,
            (_AUTH_PLUGIN_ID, credential_key, encrypted, now, now),
        )
    logger.info("Saved OAuth tokens for provider %r.", provider)


async def get_oauth_tokens(
    db: aiosqlite.Connection,
    provider: str,
) -> dict | None:
    """Return the decrypted OAuth tokens dict for *provider*, or ``None`` if not set."""
    credential_key = f"oauth_tokens:{provider}"
    row = await _get_row(db, credential_key)
    if row is None:
        return None
    try:
        return json.loads(decrypt_credential(row["encrypted_value"]))
    except ValueError:
        logger.warning(
            "Stored OAuth tokens for %r could not be decrypted — clearing them.", provider
        )
        await revoke_oauth_tokens(db, provider)
        return None


async def revoke_oauth_tokens(db: aiosqlite.Connection, provider: str) -> None:
    """Delete stored OAuth tokens for *provider*."""
    credential_key = f"oauth_tokens:{provider}"
    async with write_transaction(db):
        await db.execute(
            "DELETE FROM plugin_credentials WHERE plugin_id = ? AND credential_key = ?",
            (_AUTH_PLUGIN_ID, credential_key),
        )
    logger.info("Revoked OAuth tokens for provider %r.", provider)
