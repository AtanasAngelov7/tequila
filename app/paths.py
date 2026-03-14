"""Canonical filesystem Path objects for Tequila v2 (§14.2, §28.4).

All code that needs a filesystem path must import from here.  Never hardcode a
directory string anywhere else — ``paths`` is the single point of truth.

Supports two runtime modes:
- **Dev mode**: source checkout.  Paths are resolved relative to the repo root
  (the directory that contains ``main.py``).
- **Frozen mode**: PyInstaller executable.  App code lives in the read-only
  ``_MEIPASS`` temp dir; user data lives in ``%LOCALAPPDATA%/Tequila/``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ── Mode detection ────────────────────────────────────────────────────────────


def is_frozen() -> bool:
    """Return ``True`` when running as a PyInstaller-bundled executable."""
    return getattr(sys, "frozen", False)


# ── Root directories ──────────────────────────────────────────────────────────


def app_dir() -> Path:
    """Root of the application code.

    - Dev: repository root (the directory that contains ``main.py``).
    - Frozen: the PyInstaller ``_MEIPASS`` temp directory (read-only; contains
      bundled app code + compiled frontend).
    """
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    # __file__ → app/paths.py → parent → app/ → parent → repo root
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Root of user-writable runtime data (database, uploads, vault, etc.).

    - Dev: ``./data/`` relative to the repository root (or ``$TEQUILA_DATA_DIR``).
    - Frozen: ``%LOCALAPPDATA%/Tequila/`` (persists across app updates).
    """
    env_override = os.environ.get("TEQUILA_DATA_DIR")
    if env_override:
        return Path(env_override).resolve()
    if is_frozen():
        local = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(local) / "Tequila"
    return app_dir() / "data"


# ── Data sub-directories ──────────────────────────────────────────────────────


def db_path() -> Path:
    """Absolute path to the SQLite database file (``data/tequila.db``)."""
    from app.constants import DB_FILENAME  # local import to avoid circular

    return data_dir() / DB_FILENAME


def vault_dir() -> Path:
    """Vault directory for user knowledge-base markdown notes (``data/vault/``)."""
    return data_dir() / "vault"


def uploads_dir() -> Path:
    """Uploaded-file storage root (``data/uploads/``)."""
    return data_dir() / "uploads"


def auth_dir() -> Path:
    """OAuth token persistence directory (``data/auth/``)."""
    return data_dir() / "auth"


def backups_dir() -> Path:
    """Backup archive directory (``data/backups/``)."""
    return data_dir() / "backups"


def browser_profiles_dir() -> Path:
    """Playwright persistent browser profiles (``data/browser_profiles/``)."""
    return data_dir() / "browser_profiles"


def logs_dir() -> Path:
    """Structured application log directory (``data/logs/``)."""
    return data_dir() / "logs"


def embeddings_dir() -> Path:
    """Embedding index cache directory (``data/embeddings/``)."""
    return data_dir() / "embeddings"


# ── App sub-directories ───────────────────────────────────────────────────────


def frontend_dir() -> Path:
    """Built React frontend static files directory.

    - Dev: ``./frontend/dist/`` (produced by ``npm run build``).
    - Frozen: bundled inside ``_MEIPASS/frontend/dist/``.
    """
    return app_dir() / "frontend" / "dist"


def plugins_dir() -> Path:
    """User-written custom plugin modules.

    - Dev: ``./app/plugins/custom/``.
    - Frozen: ``%LOCALAPPDATA%/Tequila/plugins/`` (user-writable).
    """
    if is_frozen():
        return data_dir() / "plugins"
    return app_dir() / "app" / "plugins" / "custom"


def alembic_dir() -> Path:
    """Alembic migration scripts directory.

    - Dev: ``./alembic/``.
    - Frozen: bundled inside ``_MEIPASS/alembic/``.
    """
    return app_dir() / "alembic"


# ── Directory creation ────────────────────────────────────────────────────────


def ensure_dirs() -> None:
    """Create all required runtime directories if they do not already exist.

    Called once during application startup before the database is opened.
    Safe to call multiple times (``exist_ok=True``).
    """
    dirs: list[Path] = [
        data_dir(),
        vault_dir(),
        uploads_dir(),
        auth_dir(),
        backups_dir(),
        browser_profiles_dir(),
        logs_dir(),
        embeddings_dir(),
    ]
    for directory in dirs:
        directory.mkdir(parents=True, exist_ok=True)
