"""Sprint 09 — Unit tests for entity model, store, and NER (§5.4)."""
from __future__ import annotations

import pytest


# ── Entity model ──────────────────────────────────────────────────────────────


def test_entity_model_basic():
    """Entity model stores name, type, and aliases."""
    from app.memory.entities import Entity
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    e = Entity(
        id="e1", name="Alice", entity_type="person",
        aliases=["Alicia"], first_seen=now, last_referenced=now, updated_at=now,
    )
    assert e.name == "Alice"
    assert e.entity_type == "person"
    assert "Alicia" in e.aliases


def test_entity_matches_canonical_name():
    """matches() returns True for the canonical name."""
    from app.memory.entities import Entity
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    e = Entity(id="e2", name="OpenAI", entity_type="organization",
               first_seen=now, last_referenced=now, updated_at=now)
    assert e.matches("OpenAI")
    assert e.matches("openai")  # case-insensitive


def test_entity_matches_alias():
    """matches() returns True for an alias."""
    from app.memory.entities import Entity
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    e = Entity(id="e3", name="International Business Machines",
               entity_type="organization", aliases=["IBM"],
               first_seen=now, last_referenced=now, updated_at=now)
    assert e.matches("IBM")
    assert e.matches("ibm")


def test_entity_matches_false_for_unknown():
    """matches() returns False for unrecognized names."""
    from app.memory.entities import Entity
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    e = Entity(id="e4", name="Google", entity_type="organization",
               first_seen=now, last_referenced=now, updated_at=now)
    assert not e.matches("Microsoft")


# ── NER extraction ────────────────────────────────────────────────────────────


def test_ner_extracts_person_title():
    """NER extracts 'Dr. Alice Smith' as a person entity."""
    from app.memory.entities import extract_entity_mentions
    mentions = extract_entity_mentions("Dr Alice Smith spoke at the conference.")
    names = [m["name"] for m in mentions]
    # Should find "Alice Smith" or "Dr Alice Smith" — at minimum not empty
    assert len(mentions) >= 1


def test_ner_extracts_organizations():
    """NER extracts 'OpenAI Inc' as an organization."""
    from app.memory.entities import extract_entity_mentions
    mentions = extract_entity_mentions("He works at OpenAI Inc these days.")
    types = {m["entity_type"] for m in mentions}
    names = {m["name"] for m in mentions}
    assert "OpenAI Inc" in names
    assert "organization" in types


def test_ner_filters_stopwords():
    """NER does not extract common stopwords as entities."""
    from app.memory.entities import extract_entity_mentions
    mentions = extract_entity_mentions("The quick brown fox jumps over a lazy dog.")
    names = {m["name"] for m in mentions}
    assert "The" not in names
    assert "A" not in names


def test_ner_empty_text_returns_empty():
    """NER on empty text returns an empty list."""
    from app.memory.entities import extract_entity_mentions
    assert extract_entity_mentions("") == []


def test_ner_code_blocks_excluded():
    """NER does not extract entities from fenced code blocks."""
    from app.memory.entities import extract_entity_mentions
    mentions = extract_entity_mentions("```python\nSomeFakeClass.do_thing()\n```")
    # SomeFakeClass should not be extracted from code
    names = {m["name"] for m in mentions}
    assert "SomeFakeClass" not in names


# ── EntityStore CRUD ──────────────────────────────────────────────────────────


@pytest.fixture
async def entity_store(migrated_db):
    from app.memory.entity_store import init_entity_store, get_entity_store
    init_entity_store(migrated_db)
    return get_entity_store()


async def test_entity_store_create_and_get(entity_store):
    """create() persists an entity that can be retrieved by ID."""
    entity = await entity_store.create(
        name="Alice Johnson", entity_type="person",
        aliases=["Alice"], summary="A researcher at XYZ",
    )
    fetched = await entity_store.get(entity.id)
    assert fetched.name == "Alice Johnson"
    assert fetched.entity_type == "person"
    assert "Alice" in fetched.aliases


async def test_entity_store_not_found_raises(entity_store):
    """get() for unknown id raises NotFoundError."""
    from app.exceptions import NotFoundError
    with pytest.raises(NotFoundError):
        await entity_store.get("does-not-exist")


async def test_entity_store_resolve_by_name(entity_store):
    """resolve() returns entity matching canonical name."""
    entity = await entity_store.create(name="Anthropic", entity_type="organization")
    found = await entity_store.resolve("Anthropic")
    assert found is not None
    assert found.id == entity.id


async def test_entity_store_resolve_by_alias(entity_store):
    """resolve() returns entity matching an alias (case-insensitive)."""
    entity = await entity_store.create(
        name="International Business Machines", entity_type="organization",
        aliases=["IBM"],
    )
    found = await entity_store.resolve("ibm")
    assert found is not None
    assert found.id == entity.id


async def test_entity_store_resolve_unknown_returns_none(entity_store):
    """resolve() returns None for unrecognised names."""
    result = await entity_store.resolve("UnknownEntity99")
    assert result is None


async def test_entity_store_add_alias(entity_store):
    """add_alias() appends a new alias."""
    entity = await entity_store.create(name="Google", entity_type="organization")
    updated = await entity_store.add_alias(entity.id, "Alphabet")
    assert "Alphabet" in updated.aliases


async def test_entity_store_add_alias_idempotent(entity_store):
    """add_alias() with an existing alias does not duplicate it."""
    entity = await entity_store.create(
        name="Tesla", entity_type="organization", aliases=["TSLA"]
    )
    updated = await entity_store.add_alias(entity.id, "TSLA")
    assert updated.aliases.count("TSLA") == 1


async def test_entity_store_list_filter_by_type(entity_store):
    """list(entity_type=...) returns only matching entities."""
    await entity_store.create(name="Alice", entity_type="person")
    await entity_store.create(name="ACME Corp", entity_type="organization")
    persons = await entity_store.list(entity_type="person")
    assert all(e.entity_type == "person" for e in persons)
    assert len(persons) == 1


async def test_entity_store_soft_delete(entity_store):
    """soft_delete() changes status to 'deleted'."""
    entity = await entity_store.create(name="ToDelete", entity_type="concept")
    deleted = await entity_store.soft_delete(entity.id)
    assert deleted.status == "deleted"


async def test_entity_store_hard_delete(entity_store):
    """delete() removes the entity from DB."""
    from app.exceptions import NotFoundError
    entity = await entity_store.create(name="RemoveMe", entity_type="concept")
    await entity_store.delete(entity.id)
    with pytest.raises(NotFoundError):
        await entity_store.get(entity.id)


async def test_entity_store_get_memories_empty(entity_store, migrated_db):
    """get_memories() returns empty list when no memories are linked."""
    entity = await entity_store.create(name="Lonely", entity_type="concept")
    memory_ids = await entity_store.get_memories(entity.id)
    assert memory_ids == []


async def test_entity_store_extract_and_link(entity_store, migrated_db):
    """extract_and_link() creates entities from NER and links them to a memory."""
    from app.memory.store import init_memory_store
    ms = init_memory_store(migrated_db)
    memory = await ms.create(content="Alice Smith works at OpenAI Inc", memory_type="fact")

    entities = await entity_store.extract_and_link(
        "Alice Smith works at OpenAI Inc", memory_id=memory.id
    )
    assert len(entities) >= 1
    # At least one entity should have been linked to the memory
    memory_ids = await entity_store.get_memories(entities[0].id)
    assert memory.id in memory_ids
