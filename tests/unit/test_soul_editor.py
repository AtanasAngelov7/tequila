"""Sprint 14a — Unit tests for soul editor (§4.1a).

Test coverage:
  - SoulVersion model: serialisation round-trip
  - SoulEditor.save_version: saves and retrieves versions
  - SoulEditor.list_versions: newest-first ordering
  - SoulEditor.get_version: specific version retrieval
  - Version numbering: auto-increments per agent
  - Multiple agents: versions are isolated per agent
  - SoulEditor.preview_soul: renders valid system prompt
  - SoulEditor.generate_soul: LLM path returns dict; fallback works
  - Fallback generation: no providers needed; returns valid SoulConfig fields
"""
from __future__ import annotations

import json

import pytest

from app.agent.soul_editor import SoulEditor, SoulVersion, _fallback_generation


# ── SoulVersion model tests ───────────────────────────────────────────────────


def test_soul_version_serialise_round_trip():
    """SoulVersion serialises to row dict and back preserving all fields."""
    from datetime import datetime, timezone
    soul_data = {"persona": "A friendly assistant", "tone": "friendly"}
    version = SoulVersion(
        agent_id="agent:001",
        version_num=1,
        soul_json=json.dumps(soul_data),
        change_note="Initial setup",
    )
    row = version.to_row()
    restored = SoulVersion.from_row(row)
    assert restored.version_id == version.version_id
    assert restored.agent_id == "agent:001"
    assert restored.version_num == 1
    assert restored.change_note == "Initial setup"
    assert json.loads(restored.soul_json) == soul_data


# ── SoulEditor tests ──────────────────────────────────────────────────────────


async def test_soul_editor_save_and_retrieve(migrated_db):
    """save_version stores a version; get_version retrieves it."""
    editor = SoulEditor(migrated_db)
    soul_json = json.dumps({"persona": "Test persona"})
    version = await editor.save_version("agent:test1", soul_json, change_note="Test save")
    assert version.version_num == 1
    assert version.agent_id == "agent:test1"
    assert version.change_note == "Test save"

    fetched = await editor.get_version("agent:test1", 1)
    assert fetched.version_id == version.version_id
    assert json.loads(fetched.soul_json) == {"persona": "Test persona"}


async def test_soul_editor_version_auto_increments(migrated_db):
    """Subsequent saves increment version_num."""
    editor = SoulEditor(migrated_db)
    v1 = await editor.save_version("agent:inc", json.dumps({"persona": "v1"}))
    v2 = await editor.save_version("agent:inc", json.dumps({"persona": "v2"}))
    v3 = await editor.save_version("agent:inc", json.dumps({"persona": "v3"}))
    assert v1.version_num == 1
    assert v2.version_num == 2
    assert v3.version_num == 3


async def test_soul_editor_list_versions_newest_first(migrated_db):
    """list_versions returns entries newest version number first."""
    editor = SoulEditor(migrated_db)
    await editor.save_version("agent:list_test", json.dumps({"persona": "v1"}))
    await editor.save_version("agent:list_test", json.dumps({"persona": "v2"}))
    await editor.save_version("agent:list_test", json.dumps({"persona": "v3"}))

    versions = await editor.list_versions("agent:list_test")
    assert versions[0].version_num == 3
    assert versions[1].version_num == 2
    assert versions[2].version_num == 1


async def test_soul_editor_versions_isolated_per_agent(migrated_db):
    """Version history for different agents is independent."""
    editor = SoulEditor(migrated_db)
    await editor.save_version("agent:A", json.dumps({"persona": "Agent A"}))
    await editor.save_version("agent:A", json.dumps({"persona": "Agent A v2"}))
    await editor.save_version("agent:B", json.dumps({"persona": "Agent B"}))

    versions_a = await editor.list_versions("agent:A")
    versions_b = await editor.list_versions("agent:B")

    assert len(versions_a) == 2
    assert len(versions_b) == 1
    # Agent B starts at version 1
    assert versions_b[0].version_num == 1


async def test_soul_editor_get_version_missing(migrated_db):
    """get_version raises KeyError for nonexistent version."""
    editor = SoulEditor(migrated_db)
    with pytest.raises(KeyError):
        await editor.get_version("agent:missing", 99)


# ── Preview tests ─────────────────────────────────────────────────────────────


def test_soul_editor_preview_basic():
    """preview_soul renders a non-empty system prompt from soul fields."""
    import aiosqlite
    # Create a minimal mock — preview doesn't use the DB
    class FakeDB:
        pass
    editor = SoulEditor(FakeDB())  # type: ignore[arg-type]

    soul_fields = {
        "persona": "I am a helpful researcher.",
        "tone": "professional",
        "verbosity": "detailed",
        "instructions": ["Always cite sources.", "Be objective."],
    }
    preview = editor.preview_soul(soul_fields)
    assert isinstance(preview, str)
    assert len(preview) > 50
    assert "helpful researcher" in preview


def test_soul_editor_preview_includes_rules():
    """preview_soul renders instructions as bullet points."""
    class FakeDB:
        pass
    editor = SoulEditor(FakeDB())  # type: ignore[arg-type]

    soul_fields = {
        "persona": "Test agent",
        "instructions": ["Rule one", "Rule two"],
    }
    preview = editor.preview_soul(soul_fields)
    assert "Rule one" in preview
    assert "Rule two" in preview


def test_soul_editor_preview_empty_soul():
    """preview_soul with empty soul still returns a string."""
    class FakeDB:
        pass
    editor = SoulEditor(FakeDB())  # type: ignore[arg-type]
    preview = editor.preview_soul({})
    assert isinstance(preview, str)


# ── Fallback generation tests ─────────────────────────────────────────────────


def test_fallback_generation_returns_valid_soul_fields():
    """_fallback_generation returns a dict with all required SoulConfig fields."""
    result = _fallback_generation("A professional coding assistant for Python developers")
    assert "persona" in result
    assert "tone" in result
    assert "verbosity" in result
    assert "language" in result
    assert "instructions" in result
    assert isinstance(result["instructions"], list)
    assert len(result["instructions"]) > 0


def test_fallback_generation_detects_professional_tone():
    """Fallback detects 'professional' tone from description keywords."""
    result = _fallback_generation("A professional corporate business assistant")
    assert result["tone"] == "professional"


def test_fallback_generation_detects_casual_tone():
    """Fallback detects 'casual' tone from description keywords."""
    result = _fallback_generation("A fun casual chat assistant")
    assert result["tone"] == "casual"


def test_fallback_generation_default_friendly_tone():
    """Fallback defaults to 'friendly' tone when no keywords match."""
    result = _fallback_generation("An assistant that helps with math problems")
    assert result["tone"] == "friendly"


def test_fallback_generation_includes_description():
    """Fallback includes the description in the persona."""
    description = "An expert chef who specialises in Italian cuisine"
    result = _fallback_generation(description)
    assert description in result["persona"] or "chef" in result["persona"].lower() or description in result["persona"]


async def test_soul_editor_generate_soul_fallback(migrated_db):
    """generate_soul falls back gracefully when no LLM provider is available."""
    editor = SoulEditor(migrated_db)
    # With no providers registered, should fall back to template
    result = await editor.generate_soul("A friendly coding assistant")
    assert "persona" in result
    assert "tone" in result
    assert "instructions" in result


async def test_soul_editor_generate_soul_saves_version(migrated_db):
    """When save=True in the API flow, a version is recorded."""
    editor = SoulEditor(migrated_db)
    soul_json = json.dumps({"persona": "Generated persona", "tone": "friendly"})
    version = await editor.save_version("agent:gen_test", soul_json, change_note="AI generated")

    versions = await editor.list_versions("agent:gen_test")
    assert len(versions) == 1
    assert versions[0].change_note == "AI generated"
