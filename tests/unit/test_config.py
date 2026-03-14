"""Tests for app/config.py — ConfigStore get/set/reload and ServerSettings."""
from __future__ import annotations

import pytest

from app.config import ConfigStore, get_settings
from app.exceptions import ConfigKeyNotFoundError


# ── ConfigStore.get ───────────────────────────────────────────────────────────


async def test_get_seeded_key(config_store: ConfigStore) -> None:
    """Default rows seeded by the migration should be readable."""
    host = config_store.get("server.host")
    assert isinstance(host, str)


async def test_get_missing_key_raises(config_store: ConfigStore) -> None:
    """Accessing a non-existent key without a default should raise."""
    with pytest.raises(ConfigKeyNotFoundError):
        config_store.get("definitely.not.a.key")


async def test_get_missing_key_with_default(config_store: ConfigStore) -> None:
    """Accessing a non-existent key with a default should return that default."""
    value = config_store.get("i.do.not.exist", default="fallback")
    assert value == "fallback"


# ── ConfigStore.set ───────────────────────────────────────────────────────────


async def test_set_updates_value(config_store: ConfigStore) -> None:
    """set() should update the in-memory cache and the DB row."""
    await config_store.set("logging.level", "DEBUG")
    assert config_store.get("logging.level") == "DEBUG"


async def test_set_missing_key_raises(config_store: ConfigStore) -> None:
    """set() on a key that doesn't exist should raise ConfigKeyNotFoundError."""
    with pytest.raises(ConfigKeyNotFoundError):
        await config_store.set("not.a.real.key", "value")


# ── ConfigStore.all ───────────────────────────────────────────────────────────


async def test_all_returns_all_rows(config_store: ConfigStore) -> None:
    """all() without arguments should return every seeded row."""
    rows = await config_store.all()
    assert len(rows) >= 7  # 7 rows seeded by baseline migration


async def test_all_filtered_by_category(config_store: ConfigStore) -> None:
    """all(category=...) should only return rows in that category."""
    rows = await config_store.all(category="server")
    assert all(r["category"] == "server" for r in rows)
    assert len(rows) > 0


# ── ConfigStore.reload ────────────────────────────────────────────────────────


async def test_reload_refreshes_cache(migrated_db, config_store: ConfigStore) -> None:
    """After modifying a value, reload() should pick it up from the DB."""
    # Directly update the DB row to bypass cache.
    await migrated_db.execute(
        "UPDATE config SET value = '\"CRITICAL\"' WHERE key = 'logging.level'"
    )
    await migrated_db.commit()

    await config_store.reload()
    assert config_store.get("logging.level") == "CRITICAL"


# ── ServerSettings ────────────────────────────────────────────────────────────


def test_get_settings_returns_singleton() -> None:
    """get_settings() should always return the same object."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_settings_default_host() -> None:
    """Default host should be 127.0.0.1."""
    settings = get_settings()
    assert settings.host == "127.0.0.1"


def test_settings_default_port() -> None:
    """Default port should be 8000."""
    settings = get_settings()
    assert settings.port == 8000
