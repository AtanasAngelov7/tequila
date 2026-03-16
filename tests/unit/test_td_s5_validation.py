"""TD-S5 regression tests — Validation & Data Integrity.

Covers all 14 items:
  T1  (TD-80)  MemoryCreateRequest validates memory_type/source_type/scope
  T2  (TD-81)  Invalid expires_at raises HTTPException 400
  T3  (TD-98)  AuditLog.log() rejects invalid event_type / actor
  T4  (TD-99)  GraphStore.add_edge() rejects invalid edge_type / node types
  T5  (TD-105) MemoryEvent.from_row corrupt timestamp logs warning, uses epoch
  T6  (TD-110) MemoryLifecycleManager constructor typed with Protocols
  T7  (TD-111) _parse_dt returns None for corrupt input (not now())
  T8  (TD-112) _sync_entity_ids_json rebuilds JSON from link table
  T9  (TD-114) KnowledgeSource._dt_required has no type: ignore
  T10 (TD-115) EntityCreateRequest entity_type is constrained
  T11 (TD-121) MEMORY_TYPES etc. are TypeAlias — no type: ignore[valid-type]
  T12 (TD-130) AddEdgeRequest.metadata uses Field(default_factory=dict)
  T13 (TD-85)  Migration 0012 exists and runs cleanly (golden DB covers this)
  T14 (TD-136) _parse_dt normalises naive datetimes to UTC
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── T1: MemoryCreateRequest Literal validation (TD-80) ───────────────────────

def test_memory_create_request_rejects_bad_memory_type():
    """Pydantic should raise ValidationError for an unknown memory_type."""
    from pydantic import ValidationError
    from app.api.routers.memory import MemoryCreateRequest

    with pytest.raises(ValidationError):
        MemoryCreateRequest(content="test", memory_type="invalid_type")


def test_memory_create_request_accepts_valid_memory_type():
    from app.api.routers.memory import MemoryCreateRequest

    req = MemoryCreateRequest(content="test", memory_type="fact")
    assert req.memory_type == "fact"


def test_memory_create_request_rejects_bad_source_type():
    from pydantic import ValidationError
    from app.api.routers.memory import MemoryCreateRequest

    with pytest.raises(ValidationError):
        MemoryCreateRequest(content="x", memory_type="fact", source_type="magic")


def test_memory_create_request_rejects_bad_scope():
    from pydantic import ValidationError
    from app.api.routers.memory import MemoryCreateRequest

    with pytest.raises(ValidationError):
        MemoryCreateRequest(content="x", memory_type="fact", scope="universe")


def test_memory_update_request_rejects_bad_status():
    from pydantic import ValidationError
    from app.api.routers.memory import MemoryUpdateRequest

    with pytest.raises(ValidationError):
        MemoryUpdateRequest(status="pending")


def test_memory_update_request_accepts_valid_status():
    from app.api.routers.memory import MemoryUpdateRequest

    req = MemoryUpdateRequest(status="archived")
    assert req.status == "archived"


# ── T2: expires_at raises 400 (TD-81) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_memory_raises_400_on_bad_expires_at(migrated_db):
    """create_memory endpoint must return 400 for an unparsable expires_at."""
    from fastapi import HTTPException
    from app.memory.store import MemoryStore, init_memory_store
    from app.api.routers.memory import MemoryCreateRequest, create_memory

    store = MemoryStore(migrated_db)
    with patch("app.api.routers.memory.get_memory_store", return_value=store):
        req = MemoryCreateRequest(content="x", memory_type="fact", expires_at="not-a-date")
        with pytest.raises(HTTPException) as exc_info:
            await create_memory(req)
        assert exc_info.value.status_code == 400
        assert "expires_at" in exc_info.value.detail.lower()


# ── T3: AuditLog validates event_type and actor (TD-98) ──────────────────────

@pytest.mark.asyncio
async def test_audit_log_rejects_invalid_event_type(migrated_db):
    """log() must raise ValueError for unknown event_type."""
    from app.memory.audit import MemoryAuditLog

    audit = MemoryAuditLog(migrated_db)
    with pytest.raises(ValueError, match="event_type"):
        await audit.log(
            event_type="exploded",
            memory_id="mem-1",
            actor="system",
        )


@pytest.mark.asyncio
async def test_audit_log_rejects_invalid_actor(migrated_db):
    """log() must raise ValueError for unknown actor."""
    from app.memory.audit import MemoryAuditLog

    audit = MemoryAuditLog(migrated_db)
    with pytest.raises(ValueError, match="actor"):
        await audit.log(
            event_type="created",
            memory_id="mem-1",
            actor="robot",
        )


@pytest.mark.asyncio
async def test_audit_log_accepts_valid_event(migrated_db):
    """log() must succeed with valid event_type and actor."""
    from app.memory.audit import MemoryAuditLog

    audit = MemoryAuditLog(migrated_db)
    event = await audit.log(
        event_type="created",
        memory_id="mem-valid",
        actor="system",
    )
    assert event.event_type == "created"
    assert event.actor == "system"


# ── T4: GraphStore validates node/edge types (TD-99) ─────────────────────────

@pytest.mark.asyncio
async def test_graph_add_edge_rejects_invalid_edge_type(migrated_db):
    """add_edge() must raise ValueError for unknown edge_type."""
    from app.knowledge.graph import GraphStore

    gs = GraphStore(migrated_db)
    with pytest.raises(ValueError, match="edge_type"):
        await gs.add_edge(
            source_id="a", source_type="memory",
            target_id="b", target_type="entity",
            edge_type="explodes_into",
        )


@pytest.mark.asyncio
async def test_graph_add_edge_rejects_invalid_source_type(migrated_db):
    """add_edge() must raise ValueError for unknown source_type."""
    from app.knowledge.graph import GraphStore

    gs = GraphStore(migrated_db)
    with pytest.raises(ValueError, match="source_type"):
        await gs.add_edge(
            source_id="a", source_type="spaceship",
            target_id="b", target_type="entity",
            edge_type="references",
        )


@pytest.mark.asyncio
async def test_graph_add_edge_accepts_valid_types(migrated_db):
    """add_edge() must succeed with valid types."""
    from app.knowledge.graph import GraphStore

    gs = GraphStore(migrated_db)
    edge = await gs.add_edge(
        source_id="note-001", source_type="note",
        target_id="mem-001", target_type="memory",
        edge_type="references",
    )
    assert edge.edge_type == "references"


# ── T5: from_row corrupt timestamp uses epoch, not now() (TD-105) ────────────

def test_memory_event_from_row_corrupt_timestamp_uses_epoch():
    """Corrupt timestamps should resolve to the sentinel 2000-01-01 epoch, not now()."""
    from app.memory.audit import MemoryEvent, _EPOCH

    row = {
        "id": "evt-1",
        "memory_id": "mem-1",
        "entity_id": None,
        "event_type": "created",
        "actor": "system",
        "actor_id": None,
        "old_content": None,
        "new_content": None,
        "reason": None,
        "metadata": "{}",
        "timestamp": "NOT_A_DATE",
    }
    event = MemoryEvent.from_row(row)
    assert event.timestamp == _EPOCH


def test_memory_event_from_row_corrupt_timestamp_logs_warning(caplog):
    from app.memory.audit import MemoryEvent

    row = {
        "id": "evt-2",
        "memory_id": None,
        "entity_id": None,
        "event_type": "updated",
        "actor": "agent",
        "actor_id": None,
        "old_content": None,
        "new_content": None,
        "reason": None,
        "metadata": "{}",
        "timestamp": "garbage-date",
    }
    with caplog.at_level(logging.WARNING, logger="app.memory.audit"):
        MemoryEvent.from_row(row)
    assert any("Corrupt timestamp" in r.message for r in caplog.records)


# ── T6: MemoryLifecycleManager uses Protocol types (TD-110) ──────────────────

def test_lifecycle_manager_accepts_protocol_conforming_stores():
    """MemoryLifecycleManager should accept objects that satisfy the Protocol."""
    from app.memory.lifecycle import (
        MemoryLifecycleManager,
        MemoryStoreProtocol,
        EntityStoreProtocol,
    )

    # Verify Protocols are exported
    assert MemoryStoreProtocol is not None
    assert EntityStoreProtocol is not None

    # Verify constructor accepts Any (runtime check)
    mem_mock = AsyncMock()
    ent_mock = AsyncMock()
    mgr = MemoryLifecycleManager(mem_mock, ent_mock)
    assert mgr is not None


# ── T7: _parse_dt returns None for corrupt input (TD-111) ────────────────────

def test_parse_dt_returns_none_for_corrupt_string():
    from app.memory.models import _parse_dt

    result = _parse_dt("not-a-date-at-all")
    assert result is None


def test_parse_dt_returns_none_for_none_input():
    from app.memory.models import _parse_dt

    assert _parse_dt(None) is None


def test_parse_dt_logs_warning_for_corrupt_value(caplog):
    from app.memory.models import _parse_dt

    with caplog.at_level(logging.WARNING, logger="app.memory.models"):
        _parse_dt("definitely-not-a-date")
    assert any("Corrupt datetime" in r.message for r in caplog.records)


def test_parse_dt_valid_iso_string():
    from app.memory.models import _parse_dt

    result = _parse_dt("2025-01-15T10:30:00+00:00")
    assert result is not None
    assert result.year == 2025
    assert result.tzinfo is not None


# ── T8: _sync_entity_ids_json rebuilds from link table (TD-112) ──────────────

@pytest.mark.asyncio
async def test_sync_entity_ids_json_rebuilds_from_link_table(migrated_db):
    """After link_entity, the JSON column must match the link table exactly."""
    from app.memory.store import MemoryStore
    from app.memory.entity_store import EntityStore

    mem_store = MemoryStore(migrated_db)
    ent_store = EntityStore(migrated_db)

    mem = await mem_store.create(
        content="test memory",
        memory_type="fact",
        source_type="user_created",
        scope="global",
    )
    entity = await ent_store.create(
        name="Alice",
        entity_type="person",
    )

    await mem_store.link_entity(mem.id, entity.id)

    # Reload from DB and verify JSON column matches
    refreshed = await mem_store.get(mem.id)
    assert entity.id in refreshed.entity_ids


@pytest.mark.asyncio
async def test_sync_entity_ids_json_cleans_up_on_unlink(migrated_db):
    """After unlink_entity, the JSON column must not contain the removed entity."""
    from app.memory.store import MemoryStore
    from app.memory.entity_store import EntityStore

    mem_store = MemoryStore(migrated_db)
    ent_store = EntityStore(migrated_db)

    mem = await mem_store.create(
        content="test memory for unlink",
        memory_type="fact",
        source_type="user_created",
        scope="global",
    )
    entity = await ent_store.create(
        name="Bob",
        entity_type="person",
    )

    await mem_store.link_entity(mem.id, entity.id)
    await mem_store.unlink_entity(mem.id, entity.id)

    refreshed = await mem_store.get(mem.id)
    assert entity.id not in refreshed.entity_ids


# ── T9: KnowledgeSource._dt_required has no type: ignore (TD-114) ────────────

def test_knowledge_source_dt_required_no_type_ignore():
    """_dt_required must not have a type: ignore comment."""
    import inspect
    from app.knowledge.sources import models as ks_models

    src = inspect.getsource(ks_models)
    assert "type: ignore[return-value]" not in src


def test_knowledge_source_from_row_handles_none_timestamps():
    """from_row should not crash when created_at/updated_at are None."""
    import json
    from app.knowledge.sources.models import KnowledgeSource

    row = {
        "id": "src-1",
        "name": "Test Source",
        "description": "",
        "backend": "chroma",
        "query_mode": "text",
        "embedding_provider": None,
        "auto_recall": 0,
        "priority": 100,
        "max_results": 5,
        "similarity_threshold": 0.6,
        "connection_json": "{}",
        "allowed_agents_json": None,
        "status": "disabled",
        "error_message": None,
        "consecutive_failures": 0,
        "last_health_check": None,
        "created_at": None,
        "updated_at": None,
    }
    ks = KnowledgeSource.from_row(row)
    assert ks.source_id == "src-1"
    assert ks.created_at is not None  # falls back to now()


# ── T10: EntityCreateRequest constrains entity_type (TD-115) ─────────────────

def test_entity_create_request_rejects_invalid_type():
    from pydantic import ValidationError
    from app.api.routers.entities import EntityCreateRequest

    with pytest.raises(ValidationError):
        EntityCreateRequest(name="Bob", entity_type="alien")


def test_entity_create_request_accepts_valid_type():
    from app.api.routers.entities import EntityCreateRequest

    req = EntityCreateRequest(name="Bob", entity_type="person")
    assert req.entity_type == "person"


# ── T11: TypeAlias declarations (TD-121) ─────────────────────────────────────

def test_memory_types_are_typealiases():
    """MEMORY_TYPES etc. must be TypeAlias, removing all type: ignore[valid-type]."""
    import inspect
    from app.memory import models as mem_models

    src = inspect.getsource(mem_models)
    assert "type: ignore[valid-type]" not in src
    # Verify TypeAlias keyword is present
    assert "TypeAlias" in src


# ── T12: AddEdgeRequest has no mutable default (TD-130) ──────────────────────

def test_add_edge_request_metadata_default_factory():
    """Two instances must not share the same metadata dict."""
    from app.api.routers.graph import AddEdgeRequest

    r1 = AddEdgeRequest(
        source_id="a", source_type="note",
        target_id="b", target_type="memory",
        edge_type="references",
    )
    r2 = AddEdgeRequest(
        source_id="c", source_type="note",
        target_id="d", target_type="memory",
        edge_type="references",
    )
    assert r1.metadata is not r2.metadata


# ── T14: _parse_dt normalises naive datetimes to UTC (TD-136) ────────────────

def test_parse_dt_normalises_naive_string_to_utc():
    from app.memory.models import _parse_dt

    result = _parse_dt("2025-06-01T12:00:00")  # no timezone
    assert result is not None
    assert result.tzinfo is not None
    assert result.tzinfo == timezone.utc


def test_parse_dt_normalises_naive_datetime_to_utc():
    from app.memory.models import _parse_dt

    naive = datetime(2025, 6, 1, 12, 0, 0)
    result = _parse_dt(naive)
    assert result is not None
    assert result.tzinfo is not None


def test_parse_dt_preserves_existing_tzinfo():
    from app.memory.models import _parse_dt

    aware = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    result = _parse_dt(aware)
    assert result == aware
