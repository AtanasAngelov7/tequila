"""Sprint 14a — Unit tests for skills system (§4.5).

Test coverage:
  - SkillDef model: serialisation round-trip
  - SkillStore CRUD: create, read, update, delete skills and resources
  - SkillEngine Level 1 index: all assigned skills rendered, budget honoured
  - SkillEngine Level 2 instructions: trigger matching (3 modes), manual activate/deactivate
  - Budget fitting: skills dropped when budget exceeded
  - Required tools check: skills with missing tools skipped
  - Import/export v1.1 round-trip (including resources)
  - Import v1.0 backward compat (prompt_fragment → instructions + summary)
  - Agent tool tools: skill_list, skill_search, skill_get_instructions, skill_list_resources, skill_read_resource
  - seed_builtins: all 7 built-in skills present after seeding
"""
from __future__ import annotations

import pytest

from app.agent.skills import (
    BUILTIN_RESOURCES,
    BUILTIN_SKILLS,
    SessionSkillState,
    SkillDef,
    SkillEngine,
    SkillResource,
    SkillStore,
    init_skill_store,
    skill_from_import_dict,
    skill_to_export_dict,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_skill(**kwargs) -> SkillDef:
    from datetime import datetime, timezone
    defaults = {
        "name": "Test Skill",
        "description": "A test skill",
        "summary": "Test skill summary",
        "instructions": "Do this specific thing when asked.",
        "activation_mode": "trigger",
        "trigger_patterns": [r"test.*skill"],
        "priority": 50,
    }
    defaults.update(kwargs)
    now = datetime.now(timezone.utc)
    defaults.setdefault("created_at", now)
    defaults.setdefault("updated_at", now)
    return SkillDef(**defaults)


def _make_resource(skill_id: str, **kwargs) -> SkillResource:
    from datetime import datetime, timezone
    defaults = {
        "skill_id": skill_id,
        "name": "Test Resource",
        "description": "A test resource",
        "content": "# Test\nThis is reference material.",
    }
    defaults.update(kwargs)
    now = datetime.now(timezone.utc)
    defaults.setdefault("created_at", now)
    defaults.setdefault("updated_at", now)
    return SkillResource(**defaults)


# ── SkillDef model tests ──────────────────────────────────────────────────────


def test_skill_def_serialise_round_trip():
    """SkillDef serialises to row dict and back preserving all fields."""
    skill = _make_skill(
        required_tools=["fs_read_file"],
        tags=["dev", "quality"],
        trigger_patterns=[r"review.*code"],
        is_builtin=False,
    )
    row = skill.to_row()
    restored = SkillDef.from_row(row)
    assert restored.skill_id == skill.skill_id
    assert restored.name == skill.name
    assert restored.required_tools == ["fs_read_file"]
    assert restored.tags == ["dev", "quality"]
    assert restored.trigger_patterns == [r"review.*code"]
    assert restored.is_builtin is False


def test_skill_resource_serialise_round_trip():
    """SkillResource serialises to row dict and back."""
    skill = _make_skill()
    res = _make_resource(skill.skill_id, name="Checklist", content="# Checklist\n- item 1")
    row = res.to_row()
    restored = SkillResource.from_row(row)
    assert restored.resource_id == res.resource_id
    assert restored.name == "Checklist"
    assert restored.content == "# Checklist\n- item 1"


# ── SkillStore CRUD tests ─────────────────────────────────────────────────────


async def test_skill_store_create_and_get(migrated_db):
    """Can create a skill and retrieve it by ID."""
    store = SkillStore(migrated_db)
    skill = _make_skill(name="My Skill", priority=10)
    created = await store.create_skill(skill)
    assert created.skill_id == skill.skill_id
    assert created.name == "My Skill"
    fetched = await store.get_skill(skill.skill_id)
    assert fetched.name == "My Skill"


async def test_skill_store_get_missing(migrated_db):
    """Getting a nonexistent skill raises KeyError."""
    store = SkillStore(migrated_db)
    with pytest.raises(KeyError):
        await store.get_skill("skill:doesnotexist")


async def test_skill_store_list(migrated_db):
    """list_skills returns skills matching optional filters."""
    store = SkillStore(migrated_db)
    s1 = _make_skill(name="Alpha", tags=["code"], priority=1)
    s2 = _make_skill(name="Beta", tags=["data"], priority=2)
    await store.create_skill(s1)
    await store.create_skill(s2)
    all_skills = await store.list_skills()
    names = [s.name for s in all_skills]
    assert "Alpha" in names
    assert "Beta" in names


async def test_skill_store_list_filter_by_tags(migrated_db):
    """list_skills filters by tag correctly."""
    store = SkillStore(migrated_db)
    s1 = _make_skill(name="CodeSkill", tags=["code"], priority=1)
    s2 = _make_skill(name="DataSkill", tags=["data"], priority=2)
    await store.create_skill(s1)
    await store.create_skill(s2)
    code_skills = await store.list_skills(tags=["code"])
    assert any(s.name == "CodeSkill" for s in code_skills)
    assert not any(s.name == "DataSkill" for s in code_skills)


async def test_skill_store_update(migrated_db):
    """Updating a skill changes the specified fields."""
    store = SkillStore(migrated_db)
    skill = _make_skill(name="Old Name")
    await store.create_skill(skill)
    updated = await store.update_skill(skill.skill_id, {"name": "New Name", "priority": 5})
    assert updated.name == "New Name"
    assert updated.priority == 5


async def test_skill_store_delete(migrated_db):
    """Deleting a skill removes it from the store."""
    store = SkillStore(migrated_db)
    skill = _make_skill()
    await store.create_skill(skill)
    await store.delete_skill(skill.skill_id)
    with pytest.raises(KeyError):
        await store.get_skill(skill.skill_id)


async def test_skill_store_resource_crud(migrated_db):
    """Can create, retrieve, update, and delete resources."""
    store = SkillStore(migrated_db)
    skill = _make_skill()
    await store.create_skill(skill)

    res = _make_resource(skill.skill_id, name="Guide", content="Step 1. Do this.")
    created = await store.create_resource(res)
    assert created.name == "Guide"

    resources = await store.list_resources(skill.skill_id)
    assert len(resources) == 1
    assert resources[0].name == "Guide"

    updated = await store.update_resource(created.resource_id, {"name": "Updated Guide"})
    assert updated.name == "Updated Guide"

    await store.delete_resource(created.resource_id)
    after_delete = await store.list_resources(skill.skill_id)
    assert len(after_delete) == 0


async def test_skill_store_get_skills_for_agent(migrated_db):
    """get_skills_for_agent preserves the requested order."""
    store = SkillStore(migrated_db)
    s1 = _make_skill(name="First", priority=2)
    s2 = _make_skill(name="Second", priority=1)
    await store.create_skill(s1)
    await store.create_skill(s2)
    result = await store.get_skills_for_agent([s1.skill_id, s2.skill_id])
    assert result[0].skill_id == s1.skill_id
    assert result[1].skill_id == s2.skill_id


async def test_skill_store_seed_builtins(migrated_db):
    """seed_builtins inserts all 7 built-in skills and their resources."""
    store = SkillStore(migrated_db)
    await store.seed_builtins()
    skills = await store.list_skills(is_builtin=True)
    skill_ids = {s.skill_id for s in skills}
    for builtin in BUILTIN_SKILLS:
        assert builtin.skill_id in skill_ids, f"Built-in skill missing: {builtin.skill_id}"

    # Check resources were seeded
    for res in BUILTIN_RESOURCES:
        try:
            fetched = await store.get_resource(res.resource_id)
            assert fetched.skill_id == res.skill_id
        except KeyError:
            pytest.fail(f"Built-in resource missing: {res.resource_id}")


async def test_skill_store_seed_builtins_idempotent(migrated_db):
    """Calling seed_builtins twice does not raise or duplicate."""
    store = SkillStore(migrated_db)
    await store.seed_builtins()
    await store.seed_builtins()  # Should be idempotent
    skills = await store.list_skills(is_builtin=True)
    builtin_ids = [s.skill_id for s in skills if s.is_builtin]
    # No duplicates
    assert len(builtin_ids) == len(set(builtin_ids))


# ── SkillEngine Level 1 tests ─────────────────────────────────────────────────


def test_engine_render_skill_index_basic():
    """Level 1 index contains all skill summaries."""
    engine = SkillEngine()
    skills = [
        _make_skill(name="Skill A", summary="Does thing A", priority=10),
        _make_skill(name="Skill B", summary="Does thing B", priority=20),
    ]
    result = engine.render_skill_index(skills)
    assert "## Available Skills" in result
    assert "Skill A" in result
    assert "Skill B" in result
    assert "Does thing A" in result


def test_engine_render_skill_index_budget_drops_low_priority():
    """Skills over index budget are silently dropped (lowest priority first)."""
    engine = SkillEngine()
    # Create skills with progressively lower priority (higher number = lower priority)
    skills = []
    for i in range(20):
        skills.append(_make_skill(
            name=f"Skill{i:02d}",
            summary="word " * 30,  # ~30 tokens per skill
            priority=i,
        ))
    # Budget: only ~3 skills should fit in 200 tokens
    result = engine.render_skill_index(skills, budget=200)
    # High-priority skills (low number) should appear
    assert "Skill00" in result
    # Not all 20 skills should fit
    assert result.count("Skill") < 20


def test_engine_render_skill_index_empty():
    """Empty skill list returns empty string."""
    engine = SkillEngine()
    result = engine.render_skill_index([])
    assert result == ""


# ── SkillEngine Level 2 tests ─────────────────────────────────────────────────


def test_engine_always_mode_always_active():
    """Skills with activation_mode='always' are always included."""
    engine = SkillEngine()
    skill = _make_skill(activation_mode="always", instructions="Always-on instructions.")
    state = SessionSkillState()
    result, ids = engine.resolve_active_skills([skill], "unrelated message", state, [])
    assert skill.skill_id in ids
    assert "Always-on instructions" in result


def test_engine_trigger_match_regex():
    """Trigger-mode skills activate when regex matches user message."""
    engine = SkillEngine()
    skill = _make_skill(
        activation_mode="trigger",
        trigger_patterns=[r"review.*code", r"code.*review"],
        instructions="Review the code carefully.",
    )
    state = SessionSkillState()
    # Matching message
    result, ids = engine.resolve_active_skills([skill], "Please review my code", state, [])
    assert skill.skill_id in ids
    assert "Review the code" in result
    # Non-matching message
    result2, ids2 = engine.resolve_active_skills([skill], "Tell me a joke", state, [])
    assert skill.skill_id not in ids2


def test_engine_trigger_match_case_insensitive():
    """Trigger regex matching is case-insensitive."""
    engine = SkillEngine()
    skill = _make_skill(
        activation_mode="trigger",
        trigger_patterns=[r"ANALYZE.*data"],
        instructions="Analyze the data.",
    )
    state = SessionSkillState()
    result, ids = engine.resolve_active_skills([skill], "analyze this data", state, [])
    assert skill.skill_id in ids


def test_engine_manual_mode_not_auto_activated():
    """Manual-mode skills are not activated by trigger matching."""
    engine = SkillEngine()
    skill = _make_skill(
        activation_mode="manual",
        trigger_patterns=[r"email"],
        instructions="Email instructions.",
    )
    state = SessionSkillState()
    result, ids = engine.resolve_active_skills([skill], "send an email", state, [])
    assert skill.skill_id not in ids


def test_engine_manual_mode_session_activation():
    """Manually activated skills are included."""
    engine = SkillEngine()
    skill = _make_skill(activation_mode="manual", instructions="Manual instructions.")
    state = SessionSkillState(manually_activated=[skill.skill_id])
    result, ids = engine.resolve_active_skills([skill], "hello", state, [])
    assert skill.skill_id in ids


def test_engine_manual_deactivation_overrides():
    """Manually deactivated skills are excluded even if trigger matches."""
    engine = SkillEngine()
    skill = _make_skill(
        activation_mode="always",
        instructions="Always-on skill.",
    )
    state = SessionSkillState(manually_deactivated=[skill.skill_id])
    result, ids = engine.resolve_active_skills([skill], "any message", state, [])
    assert skill.skill_id not in ids


def test_engine_required_tools_check():
    """Skills with required tools absent from agent tools are excluded."""
    engine = SkillEngine()
    skill = _make_skill(
        activation_mode="always",
        required_tools=["special_tool_xyz"],
        instructions="Requires special tool.",
    )
    state = SessionSkillState()
    # Agent has no tools
    result, ids = engine.resolve_active_skills([skill], "hello", state, agent_tools=[])
    assert skill.skill_id not in ids
    # Agent has the required tool
    result2, ids2 = engine.resolve_active_skills([skill], "hello", state, agent_tools=["special_tool_xyz"])
    assert skill.skill_id in ids2


def test_engine_instruction_budget_fitting():
    """Skills are dropped when instruction budget is exhausted."""
    engine = SkillEngine()
    # Create many always-on skills with long instructions
    skills = [
        _make_skill(
            name=f"Skill{i}",
            activation_mode="always",
            instructions="word " * 200,  # ~200 tokens each
            priority=i,
        )
        for i in range(10)
    ]
    state = SessionSkillState()
    result, ids = engine.resolve_active_skills(skills, "hello", state, [], budget=600)
    # Should include at most ~3 skills (600 tokens / ~200 each)
    assert len(ids) <= 4


def test_engine_priority_ordering():
    """Lower priority number = higher priority = first to be included."""
    engine = SkillEngine()
    high_prio = _make_skill(
        name="HighPrio",
        activation_mode="always",
        instructions="High priority instructions.",
        priority=1,
    )
    low_prio = _make_skill(
        name="LowPrio",
        activation_mode="always",
        instructions="word " * 400,  # very long, should push out others
        priority=99,
    )
    state = SessionSkillState()
    # Budget: only one can fit
    result, ids = engine.resolve_active_skills([high_prio, low_prio], "hello", state, [], budget=200)
    assert high_prio.skill_id in ids


def test_engine_trigger_tool_presence():
    """Skills auto-suggest via trigger_tool_presence when tool enabled."""
    engine = SkillEngine()
    skill = _make_skill(
        activation_mode="trigger",
        trigger_tool_presence=["fs_read_file"],
        trigger_patterns=[],
        instructions="File tool instructions.",
    )
    state = SessionSkillState()
    # Agent has the triggering tool
    result, ids = engine.resolve_active_skills([skill], "hello", state, agent_tools=["fs_read_file"])
    assert skill.skill_id in ids
    # Agent does not have the tool
    result2, ids2 = engine.resolve_active_skills([skill], "hello", state, agent_tools=[])
    assert skill.skill_id not in ids2


# ── Import/Export tests ───────────────────────────────────────────────────────


def test_skill_export_v11_round_trip():
    """v1.1 export includes all fields and resources; import restores correctly."""
    skill = _make_skill(
        name="Export Test",
        summary="A summary",
        instructions="Detailed instructions.",
        tags=["export", "test"],
    )
    resource = _make_resource(skill.skill_id, name="Guide", content="# Guide\nstep 1")
    export = skill_to_export_dict(skill, [resource])
    assert export["version"] == "1.1"
    assert export["name"] == "Export Test"
    assert export["summary"] == "A summary"
    assert len(export["resources"]) == 1
    assert export["resources"][0]["name"] == "Guide"

    # Import round-trip
    imported_skill, imported_resources = skill_from_import_dict(export)
    assert imported_skill.name == "Export Test"
    assert imported_skill.summary == "A summary"
    assert imported_skill.instructions == "Detailed instructions."
    assert imported_skill.tags == ["export", "test"]
    assert len(imported_resources) == 1
    assert imported_resources[0].content == "# Guide\nstep 1"


def test_skill_import_v10_backward_compat():
    """v1.0 format with prompt_fragment → instructions + summary."""
    v10_payload = {
        "version": "1.0",
        "name": "Old Skill",
        "prompt_fragment": "Use this old skill for specific tasks. " * 5,
    }
    skill, resources = skill_from_import_dict(v10_payload)
    assert skill.name == "Old Skill"
    assert len(skill.instructions) > 0
    assert "old skill" in skill.instructions.lower()
    assert len(resources) == 0


def test_skill_import_v11_with_fresh_ids():
    """Imported skill fields match payload; IDs are assigned during import."""
    payload = {
        "version": "1.1",
        "name": "Fresh Import",
        "description": "Some skill",
        "summary": "Short summary",
        "instructions": "Do the thing.",
        "activation_mode": "always",
        "priority": 42,
        "tags": ["imported"],
        "resources": [
            {"name": "Template", "content": "# Template\nContent here"},
        ],
    }
    skill, resources = skill_from_import_dict(payload)
    assert skill.name == "Fresh Import"
    assert skill.activation_mode == "always"
    assert skill.priority == 42
    assert skill.tags == ["imported"]
    assert skill.is_builtin is False
    assert len(resources) == 1
    assert resources[0].skill_id == skill.skill_id


# ── Agent tool function tests ─────────────────────────────────────────────────


async def test_skill_get_instructions_tool(migrated_db):
    """skill_get_instructions returns Level 2 instructions for a skill."""
    from app.agent.skills import init_skill_store
    store = init_skill_store(migrated_db)

    skill = _make_skill(name="Instructed", instructions="Do this specific thing carefully.")
    await store.create_skill(skill)

    from app.tools.builtin.skill_tools import skill_get_instructions
    result = await skill_get_instructions(skill_id=skill.skill_id)
    assert "Instructed" in result
    assert "Do this specific thing carefully." in result


async def test_skill_get_instructions_missing(migrated_db):
    """skill_get_instructions with unknown ID returns NOT-found message."""
    from app.agent.skills import init_skill_store
    init_skill_store(migrated_db)

    from app.tools.builtin.skill_tools import skill_get_instructions
    result = await skill_get_instructions(skill_id="skill:notexist")
    assert "not found" in result.lower()


async def test_skill_search_tool(migrated_db):
    """skill_search returns matching skills by keyword."""
    from app.agent.skills import init_skill_store
    store = init_skill_store(migrated_db)
    await store.create_skill(_make_skill(name="PythonHelper", description="Helps with Python code"))
    await store.create_skill(_make_skill(name="Unrelated", description="Something else entirely"))

    from app.tools.builtin.skill_tools import skill_search
    result = await skill_search(query="Python")
    assert "PythonHelper" in result
    assert "Unrelated" not in result  # Exact match filter


async def test_skill_list_resources_tool(migrated_db):
    """skill_list_resources returns resource metadata for a skill."""
    from app.agent.skills import init_skill_store
    store = init_skill_store(migrated_db)
    skill = _make_skill(name="WithResources")
    await store.create_skill(skill)
    res = _make_resource(skill.skill_id, name="My Checklist")
    await store.create_resource(res)

    from app.tools.builtin.skill_tools import skill_list_resources
    result = await skill_list_resources(skill_id=skill.skill_id)
    assert "My Checklist" in result
    assert res.resource_id in result


async def test_skill_read_resource_tool(migrated_db):
    """skill_read_resource returns the full resource content."""
    from app.agent.skills import init_skill_store
    store = init_skill_store(migrated_db)
    skill = _make_skill()
    await store.create_skill(skill)
    res = _make_resource(skill.skill_id, name="My Template", content="## Template\nStep 1: Do this.")
    await store.create_resource(res)

    from app.tools.builtin.skill_tools import skill_read_resource
    result = await skill_read_resource(resource_id=res.resource_id)
    assert "My Template" in result
    assert "Step 1: Do this." in result


async def test_skill_activate_deactivate_tools(migrated_db):
    """skill_activate / skill_deactivate return confirmation messages."""
    from app.agent.skills import init_skill_store
    store = init_skill_store(migrated_db)
    skill = _make_skill(name="TargetSkill")
    await store.create_skill(skill)

    from app.tools.builtin.skill_tools import skill_activate, skill_deactivate

    activate_result = await skill_activate(skill_id=skill.skill_id, session_id="sess:test")
    assert "TargetSkill" in activate_result
    assert "activated" in activate_result.lower()

    deactivate_result = await skill_deactivate(skill_id=skill.skill_id, session_id="sess:test")
    assert "TargetSkill" in deactivate_result
    assert "deactivated" in deactivate_result.lower()


# ── Prompt assembly integration test ─────────────────────────────────────────


async def test_prompt_assembly_skill_index_in_system_prompt(migrated_db):
    """When agent has skills, Level 1 index appears in system prompt."""
    from app.agent.skills import init_skill_store
    store = init_skill_store(migrated_db)
    skill = _make_skill(name="Testable", summary="This skill does X and Y")
    await store.create_skill(skill)

    from app.agent.models import AgentConfig, SoulConfig
    from app.agent.prompt_assembly import AssemblyContext, assemble_prompt

    agent = AgentConfig(name="Test", soul=SoulConfig(persona="test agent"), skills=[skill.skill_id])
    ctx = AssemblyContext(agent_config=agent, user_message="hello")
    messages = await assemble_prompt(ctx)

    system_text = messages[0].content
    assert "Available Skills" in system_text or "Testable" in system_text


async def test_prompt_assembly_level2_triggered(migrated_db):
    """Trigger match injects Level 2 instructions into system prompt."""
    from app.agent.skills import init_skill_store
    store = init_skill_store(migrated_db)
    skill = _make_skill(
        name="CodeReviewSkill",
        summary="A code review helper",
        instructions="Check for bugs, security, and style.",
        activation_mode="trigger",
        trigger_patterns=[r"review.*code"],
        priority=1,
    )
    await store.create_skill(skill)

    from app.agent.models import AgentConfig, SoulConfig
    from app.agent.prompt_assembly import AssemblyContext, assemble_prompt

    agent = AgentConfig(name="Test", soul=SoulConfig(persona="test agent"), skills=[skill.skill_id])
    ctx = AssemblyContext(agent_config=agent, user_message="Please review my code")
    messages = await assemble_prompt(ctx)
    system_text = messages[0].content
    # Level 2 instructions should appear
    assert "Check for bugs" in system_text


async def test_prompt_assembly_no_trigger_no_level2(migrated_db):
    """Without trigger match, Level 2 instructions NOT injected."""
    from app.agent.skills import init_skill_store
    store = init_skill_store(migrated_db)
    skill = _make_skill(
        name="EmailSkill",
        summary="An email drafting skill",
        instructions="Draft professional emails with proper structure.",
        activation_mode="trigger",
        trigger_patterns=[r"draft.*email"],
        priority=1,
    )
    await store.create_skill(skill)

    from app.agent.models import AgentConfig, SoulConfig
    from app.agent.prompt_assembly import AssemblyContext, assemble_prompt

    agent = AgentConfig(name="Test", soul=SoulConfig(persona="test agent"), skills=[skill.skill_id])
    ctx = AssemblyContext(agent_config=agent, user_message="Tell me the weather")
    messages = await assemble_prompt(ctx)
    system_text = messages[0].content
    # Level 2 instruction text should NOT appear
    assert "Draft professional emails with proper structure." not in system_text
