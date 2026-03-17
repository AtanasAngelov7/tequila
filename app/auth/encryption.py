"""Credential encryption at rest using Fernet symmetric encryption (Sprint 12, §6.1).

The encryption key is a Fernet key (32 random bytes, URL-safe base64-encoded).
It is auto-generated on first use and stored in the ConfigStore under the key
``auth.encryption_key``.  The key is never logged or returned over the API.

Usage::

    from app.auth.encryption import encrypt_credential, decrypt_credential
    token = encrypt_credential(raw_key)    # → opaque base64 str
    raw   = decrypt_credential(token)      # → original value or raises
"""
from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# Module-level cipher instance — initialised by init_encryption().
_fernet: Fernet | None = None


def init_encryption(b64_key: str) -> None:
    """Initialise the module-level Fernet cipher from a stored base64 key.

    Called once during app startup after the ConfigStore is ready.
    """
    global _fernet  # noqa: PLW0603
    _fernet = Fernet(b64_key.encode())


def generate_key() -> str:
    """Generate a new Fernet key and return it as a string.

    Store the returned value in ConfigStore under ``auth.encryption_key``.
    """
    return Fernet.generate_key().decode()


def get_fernet() -> Fernet:
    """Return the active Fernet cipher.  Raises ``RuntimeError`` if not initialised."""
    if _fernet is None:
        raise RuntimeError("Encryption not initialised — call init_encryption() at startup.")
    return _fernet


def encrypt_credential(plaintext: str) -> str:
    """Encrypt *plaintext* and return an opaque base64 token.

    The token can be stored in the database and later decrypted by
    ``decrypt_credential()``.
    """
    return get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_credential(token: str) -> str:
    """Decrypt a token previously produced by ``encrypt_credential()``.

    Raises ``ValueError`` if the token is invalid or was encrypted with a
    different key.
    """
    try:
        return get_fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        # TD-241: Narrow exception to only expected crypto errors
        logger.warning("Credential decryption failed: %s", exc)
        raise ValueError("Invalid or tampered credential token.") from exc
    except (UnicodeDecodeError, ValueError) as exc:
        logger.warning("Credential decryption failed: %s", exc)
        raise ValueError("Invalid or tampered credential token.") from exc
