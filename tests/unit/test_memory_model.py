"""Sprint 09 — Unit tests for the memory data model and store (§5.3)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError


# ── MemoryExtract model ───────────────────────────────────────────────────────


def test_memory_extract_identity_defaults():
    """identity type gets always_recall=True and recall_weight=1.5."""
    from app.memory.models import MemoryExtract
    mem = MemoryExtract.with_type_defaults(
        id="m1", content="User is Alice", memory_type="identity"
    )
    assert mem.always_recall is True
    assert mem.recall_weight == 1.5


def test_memory_extract_preference_defaults():
    """preference type gets always_recall=True and recall_weight=1.2."""
    from app.memory.models import MemoryExtract
    mem = MemoryExtract.with_type_defaults(
        id="m2", content="User prefers dark mode", memory_type="preference"
    )
    assert mem.always_recall is True
    assert mem.recall_weight == 1.2


def test_memory_extract_task_recall_weight():
    """task type gets recall_weight=1.3."""
    from app.memory.models import MemoryExtract
    mem = MemoryExtract.with_type_defaults(
        id="m3", content="Submit report by Friday", memory_type="task"
    )
    assert mem.recall_weight == 1.3


def test_memory_extract_skill_recall_weight():
    """skill type gets recall_weight=0.9."""
    from app.memory.models import MemoryExtract
    mem = MemoryExtract.with_type_defaults(
        id="m4", content="Use pytest for testing", memory_type="skill"
    )
    assert mem.recall_weight == 0.9


def test_memory_extract_fact_not_always_recall():
    """fact type does NOT set always_recall=True by default."""
    from app.memory.models import MemoryExtract
    mem = MemoryExtract.with_type_defaults(
        id="m5", content="Python is a programming language", memory_type="fact"
    )
    assert mem.always_recall is False


def test_memory_extract_confidence_clamped_high():
    """confidence values above 1.0 are clamped to 1.0."""
    from app.memory.models import MemoryExtract
    mem = MemoryExtract(id="m6", content="test", memory_type="fact", confidence=2.5)
    assert mem.confidence == 1.0


def test_memory_extract_confidence_clamped_low():
    """confidence values below 0.0 are clamped to 0.0."""
    from app.memory.models import MemoryExtract
    mem = MemoryExtract(id="m7", content="test", memory_type="fact", confidence=-1.0)
    assert mem.confidence == 0.0


def test_memory_extract_invalid_type_raises():
    """Invalid memory_type raises ValidationError."""
    from app.memory.models import MemoryExtract
    with pytest.raises(ValidationError):
        MemoryExtract(id="m8", content="test", memory_type="unknown_type")


def test_memory_extract_caller_overrides_defaults():
    """Explicit caller-supplied values override per-type defaults."""
    from app.memory.models import MemoryExtract
    mem = MemoryExtract.with_type_defaults(
        id="m9", content="test", memory_type="identity",
        always_recall=False, recall_weight=0.5
    )
    assert mem.always_recall is False
    assert mem.recall_weight == 0.5


def test_memory_extract_entity_ids_default_empty():
    """entity_ids defaults to an empty list."""
    from app.memory.models import MemoryExtract
    mem = MemoryExtract(id="m10", content="test", memory_type="fact")
    assert mem.entity_ids == []


def test_memory_extract_version_default_one():
    """version defaults to 1."""
    from app.memory.models import MemoryExtract
    mem = MemoryExtract(id="m11", content="test", memory_type="fact")
    assert mem.version == 1


# ── MemoryStore CRUD ──────────────────────────────────────────────────────────


@pytest.fixture
async def memory_store(migrated_db):
    from app.memory.store import init_memory_store, get_memory_store
    init_memory_store(migrated_db)
    return get_memory_store()


async def test_memory_store_create_and_get(memory_store):
    """create() persists a memory that can be retrieved by ID."""
    mem = await memory_store.create(
        content="Alice enjoys hiking",
        memory_type="preference",
    )
    assert mem.id is not None
    fetched = await memory_store.get(mem.id)
    assert fetched.content == "Alice enjoys hiking"
    assert fetched.memory_type == "preference"


async def test_memory_store_applies_type_defaults(memory_store):
    """create() applies per-type defaults (identity → always_recall=True)."""
    mem = await memory_store.create(
        content="User's name is Bob", memory_type="identity"
    )
    assert mem.always_recall is True


async def test_memory_store_list_filter_by_type(memory_store):
    """list() filters by memory_type."""
    await memory_store.create(content="Python tip", memory_type="skill")
    await memory_store.create(content="User birthday", memory_type="identity")
    skills = await memory_store.list(memory_type="skill")
    assert all(m.memory_type == "skill" for m in skills)
    assert len(skills) == 1


async def test_memory_store_update(memory_store):
    """update() changes content and bumps version."""
    mem = await memory_store.create(content="old content", memory_type="fact")
    updated = await memory_store.update(mem.id, content="new content")
    assert updated.content == "new content"
    assert updated.version == mem.version + 1


async def test_memory_store_soft_delete(memory_store):
    """soft_delete() sets status to 'deleted' without removing the row."""
    mem = await memory_store.create(content="temporary", memory_type="task")
    deleted = await memory_store.soft_delete(mem.id)
    assert deleted.status == "deleted"
    # Should still be retrievable by direct get
    fetched = await memory_store.get(mem.id)
    assert fetched.status == "deleted"


async def test_memory_store_hard_delete(memory_store):
    """delete() removes the memory from the DB."""
    from app.exceptions import NotFoundError
    mem = await memory_store.create(content="remove me", memory_type="fact")
    await memory_store.delete(mem.id)
    with pytest.raises(NotFoundError):
        await memory_store.get(mem.id)


async def test_memory_store_list_always_recall_only(memory_store):
    """list(always_recall_only=True) returns only always_recall memories."""
    await memory_store.create(content="identity mem", memory_type="identity")
    await memory_store.create(content="fact mem", memory_type="fact")
    results = await memory_store.list(always_recall_only=True)
    assert all(m.always_recall for m in results)


async def test_memory_store_all_seven_types(memory_store):
    """All seven memory types can be created without error."""
    types = ["identity", "preference", "fact", "experience", "task", "relationship", "skill"]
    for mtype in types:
        mem = await memory_store.create(content=f"Test {mtype}", memory_type=mtype)
        assert mem.memory_type == mtype
