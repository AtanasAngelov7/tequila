"""Tests for app/paths.py — dev-mode path resolution (§28.4)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app import paths


def test_is_frozen_returns_false_in_dev() -> None:
    """Running in pytest means we're in dev mode (not frozen)."""
    assert paths.is_frozen() is False


def test_app_dir_is_project_root() -> None:
    """In dev mode, app_dir() should be the directory containing main.py."""
    app_dir = paths.app_dir()
    assert (app_dir / "main.py").exists(), f"main.py not found in app_dir={app_dir}"


def test_data_dir_default() -> None:
    """Default data_dir() is ./data/ relative to repo root."""
    # Remove any override env var.
    env_backup = os.environ.pop("TEQUILA_DATA_DIR", None)
    try:
        data = paths.data_dir()
        assert data == paths.app_dir() / "data"
    finally:
        if env_backup is not None:
            os.environ["TEQUILA_DATA_DIR"] = env_backup


def test_data_dir_env_override(tmp_path: Path) -> None:
    """TEQUILA_DATA_DIR env var overrides the default data directory."""
    override = str(tmp_path / "custom_data")
    os.environ["TEQUILA_DATA_DIR"] = override
    try:
        data = paths.data_dir()
        assert data == Path(override).resolve()
    finally:
        del os.environ["TEQUILA_DATA_DIR"]


def test_db_path_inside_data_dir() -> None:
    """db_path() is data_dir() / tequila.db."""
    from app.constants import DB_FILENAME

    assert paths.db_path() == paths.data_dir() / DB_FILENAME


def test_frontend_dir() -> None:
    """frontend_dir() resolves to the frontend/dist sub-directory."""
    assert paths.frontend_dir() == paths.app_dir() / "frontend" / "dist"


def test_alembic_dir() -> None:
    """alembic_dir() should point to the alembic/ directory that exists."""
    alembic = paths.alembic_dir()
    assert alembic.name == "alembic", f"Expected 'alembic', got '{alembic.name}'"


def test_sub_dirs() -> None:
    """All sub-directory helpers return paths inside data_dir()."""
    data = paths.data_dir()
    assert paths.vault_dir() == data / "vault"
    assert paths.uploads_dir() == data / "uploads"
    assert paths.auth_dir() == data / "auth"
    assert paths.backups_dir() == data / "backups"
    assert paths.browser_profiles_dir() == data / "browser_profiles"
    assert paths.logs_dir() == data / "logs"
    assert paths.embeddings_dir() == data / "embeddings"


def test_ensure_dirs_creates_directories(tmp_path: Path) -> None:
    """ensure_dirs() creates all required directories."""
    os.environ["TEQUILA_DATA_DIR"] = str(tmp_path / "ensure_test")
    try:
        paths.ensure_dirs()
        assert paths.data_dir().exists()
        assert paths.vault_dir().exists()
        assert paths.uploads_dir().exists()
    finally:
        del os.environ["TEQUILA_DATA_DIR"]
