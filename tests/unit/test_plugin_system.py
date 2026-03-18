"""Unit tests for the plugin system core — models, store, registry (Sprint 12)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.auth.encryption import generate_key, init_encryption
from app.plugins.models import (
    ChannelAdapterSpec,
    PluginAuth,
    PluginDependencies,
    PluginHealthResult,
    PluginRecord,
    PluginTestResult,
)


# ── Model tests ───────────────────────────────────────────────────────────────


def test_plugin_record_defaults():
    now = datetime.now(timezone.utc)
    rec = PluginRecord(
        plugin_id="test",
        name="Test Plugin",
        plugin_type="connector",
        created_at=now,
        updated_at=now,
    )
    assert rec.status == "installed"
    assert rec.config == {}
    assert rec.version == "1.0.0"
    assert rec.error_message is None


def test_plugin_health_result_defaults():
    result = PluginHealthResult(healthy=True)
    assert result.message == ""
    assert result.details == {}
    assert result.checked_at is not None


def test_plugin_test_result_defaults():
    result = PluginTestResult(success=False, message="error")
    assert result.latency_ms is None
    assert result.details == {}


def test_channel_adapter_spec_defaults():
    spec = ChannelAdapterSpec(channel_name="email")
    assert spec.supports_inbound is True
    assert spec.supports_outbound is True
    assert spec.supports_voice is False
    assert spec.polling_mode is False


def test_plugin_dependencies_defaults():
    deps = PluginDependencies()
    assert deps.python_packages == []
    assert deps.system_commands == []
    assert deps.optional is False


# ── Store tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_and_load_plugin(migrated_db):
    init_encryption(generate_key())
    from app.plugins.store import save_plugin, load_plugin

    now = datetime.now(timezone.utc)
    rec = PluginRecord(
        plugin_id="testplugin",
        name="Test",
        plugin_type="connector",
        connector_type="builtin",
        created_at=now,
        updated_at=now,
    )
    await save_plugin(migrated_db, rec)
    loaded = await load_plugin(migrated_db, "testplugin")
    assert loaded is not None
    assert loaded.plugin_id == "testplugin"
    assert loaded.status == "installed"


@pytest.mark.asyncio
async def test_load_all_plugins(migrated_db):
    init_encryption(generate_key())
    from app.plugins.store import save_plugin, load_all_plugins

    now = datetime.now(timezone.utc)
    for i in range(3):
        await save_plugin(
            migrated_db,
            PluginRecord(plugin_id=f"p{i}", name=f"P{i}", plugin_type="connector", created_at=now, updated_at=now),
        )
    records = await load_all_plugins(migrated_db)
    ids = {r.plugin_id for r in records}
    assert {"p0", "p1", "p2"}.issubset(ids)


@pytest.mark.asyncio
async def test_update_plugin_status(migrated_db):
    init_encryption(generate_key())
    from app.plugins.store import save_plugin, update_plugin_status, load_plugin

    now = datetime.now(timezone.utc)
    rec = PluginRecord(plugin_id="sp1", name="SP1", plugin_type="connector", created_at=now, updated_at=now)
    await save_plugin(migrated_db, rec)
    await update_plugin_status(migrated_db, "sp1", "error", "test error")
    loaded = await load_plugin(migrated_db, "sp1")
    assert loaded.status == "error"
    assert loaded.error_message == "test error"


@pytest.mark.asyncio
async def test_delete_plugin(migrated_db):
    init_encryption(generate_key())
    from app.plugins.store import save_plugin, delete_plugin, load_plugin

    now = datetime.now(timezone.utc)
    rec = PluginRecord(plugin_id="dp1", name="DP1", plugin_type="connector", created_at=now, updated_at=now)
    await save_plugin(migrated_db, rec)
    deleted = await delete_plugin(migrated_db, "dp1")
    assert deleted is True
    assert await load_plugin(migrated_db, "dp1") is None


@pytest.mark.asyncio
async def test_save_and_get_credential(migrated_db):
    init_encryption(generate_key())
    from app.plugins.store import save_credential, get_credential

    await save_credential(migrated_db, "myplugin", "api_token", "tok-abc")
    result = await get_credential(migrated_db, "myplugin", "api_token")
    assert result == "tok-abc"


@pytest.mark.asyncio
async def test_get_missing_credential_returns_none(migrated_db):
    init_encryption(generate_key())
    from app.plugins.store import get_credential

    result = await get_credential(migrated_db, "noplugin", "nokey")
    assert result is None


@pytest.mark.asyncio
async def test_delete_credential(migrated_db):
    init_encryption(generate_key())
    from app.plugins.store import save_credential, get_credential, delete_credential

    await save_credential(migrated_db, "myplugin", "tok", "secret")
    await delete_credential(migrated_db, "myplugin", "tok")
    assert await get_credential(migrated_db, "myplugin", "tok") is None


# ── Registry tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_registry_install_and_get_record(migrated_db):
    init_encryption(generate_key())
    from app.plugins.registry import PluginRegistry
    from app.plugins.builtin.webhooks.plugin import WebhooksPlugin

    registry = PluginRegistry(migrated_db)
    registry.register_class(WebhooksPlugin)
    record = await registry.install(WebhooksPlugin)

    assert record.plugin_id == "webhooks"
    assert record.status == "installed"
    assert registry.get_record("webhooks") is not None


@pytest.mark.asyncio
async def test_registry_list_records(migrated_db):
    init_encryption(generate_key())
    from app.plugins.registry import PluginRegistry
    from app.plugins.builtin.webhooks.plugin import WebhooksPlugin

    registry = PluginRegistry(migrated_db)
    registry.register_class(WebhooksPlugin)
    await registry.install(WebhooksPlugin)

    records = registry.list_records()
    assert any(r.plugin_id == "webhooks" for r in records)


@pytest.mark.asyncio
async def test_registry_uninstall(migrated_db):
    init_encryption(generate_key())
    from app.plugins.registry import PluginRegistry
    from app.plugins.builtin.webhooks.plugin import WebhooksPlugin

    registry = PluginRegistry(migrated_db)
    registry.register_class(WebhooksPlugin)
    await registry.install(WebhooksPlugin)
    await registry.uninstall("webhooks")
    assert registry.get_record("webhooks") is None
