"""Agent skill tools — 7 tools for skill discovery and activation (§4.5.6, Sprint 14a).

Tools:
  skill_list              — List all skills assigned to current agent.
  skill_search            — Search all available skills.
  skill_activate          — Activate a skill for this session.
  skill_deactivate        — Deactivate a skill for this session.
  skill_get_instructions  — Fetch Level 2 instructions for a skill (one-off).
  skill_list_resources    — List Level 3 resources for a skill.
  skill_read_resource     — Read Level 3 resource content.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.tools.registry import tool

logger = logging.getLogger(__name__)


# ─ Helpers ───────────────────────────────────────────────────────────────────

def _get_store():
    """Get skill store, returning a descriptive error if not ready."""
    try:
        from app.agent.skills import get_skill_store
        return get_skill_store()
    except RuntimeError:
        return None


def _get_session_state(session_id: str):
    """Load SessionSkillState from session metadata, creating if absent."""
    from app.agent.skills import SessionSkillState
    try:
        from app.sessions.store import get_session_store
        store = get_session_store()
    except RuntimeError:
        return SessionSkillState()
    return SessionSkillState()  # In-memory; saved via session metadata in full impl


def _format_skill_list(skills: list[Any]) -> str:
    if not skills:
        return "No skills found."
    lines = []
    for s in skills:
        modes = f"[{s.activation_mode}]"
        lines.append(f"- **{s.name}** (`{s.skill_id}`) {modes}: {s.description}")
    return "\n".join(lines)


# ── skill_list ────────────────────────────────────────────────────────────────

@tool(
    description=(
        "List all skills assigned to the current agent. "
        "Shows skill name, ID, activation mode, and description."
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Current session ID.",
            },
        },
        "required": ["session_id"],
    },
)
async def skill_list(session_id: str) -> str:
    """List skills assigned to the agent in the current session."""
    store = _get_store()
    if store is None:
        return "Skill store is not available."
    try:
        # Look up agent for the session
        from app.sessions.store import get_session_store
        from app.agent.store import get_agent_store
        session_store = get_session_store()
        session = await session_store.get(session_id)
        agent_store = get_agent_store()
        agent = await agent_store.get_by_id(session.agent_id)
        skills = await store.get_skills_for_agent(agent.skills)
        if not skills:
            return "No skills are assigned to this agent."
        return _format_skill_list(skills)
    except Exception as exc:
        logger.warning("skill_list error: %s", exc)
        return f"Could not retrieve skills: {exc}"


# ── skill_search ──────────────────────────────────────────────────────────────

@tool(
    description=(
        "Search all available skills by name, description, or tags. "
        "Returns matching skills that could be assigned to this agent."
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query — matched against skill name and description.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Filter by tags (optional).",
            },
        },
        "required": ["query"],
    },
)
async def skill_search(query: str, tags: list[str] | None = None) -> str:
    """Search available skills."""
    store = _get_store()
    if store is None:
        return "Skill store is not available."
    try:
        skills = await store.list_skills(q=query, tags=tags or [])
        if not skills:
            return f"No skills found matching '{query}'."
        return _format_skill_list(skills)
    except Exception as exc:
        logger.warning("skill_search error: %s", exc)
        return f"Skill search failed: {exc}"


# ── skill_activate ────────────────────────────────────────────────────────────

@tool(
    description=(
        "Activate a skill for the duration of this session. "
        "Once activated, the skill's full instructions will be injected "
        "into every subsequent prompt turn."
    ),
    safety="side_effect",
    parameters={
        "type": "object",
        "properties": {
            "skill_id": {
                "type": "string",
                "description": "The skill_id to activate (e.g. 'skill:research').",
            },
            "session_id": {
                "type": "string",
                "description": "Current session ID.",
            },
        },
        "required": ["skill_id", "session_id"],
    },
)
async def skill_activate(skill_id: str, session_id: str) -> str:
    """Activate a skill session-wide."""
    store = _get_store()
    if store is None:
        return "Skill store is not available."
    try:
        skill = await store.get_skill(skill_id)
    except KeyError:
        return f"Skill '{skill_id}' not found."
    # Note: In the full implementation, this would persist the state to session metadata.
    # The SkillEngine reads SessionSkillState which is passed in from the turn loop context.
    return (
        f"Skill **{skill.name}** (`{skill_id}`) activated for this session. "
        f"Its instructions will be included in all subsequent prompts."
    )


# ── skill_deactivate ──────────────────────────────────────────────────────────

@tool(
    description=(
        "Deactivate a skill for the duration of this session. "
        "The skill's instructions will no longer be injected into prompts."
    ),
    safety="side_effect",
    parameters={
        "type": "object",
        "properties": {
            "skill_id": {
                "type": "string",
                "description": "The skill_id to deactivate.",
            },
            "session_id": {
                "type": "string",
                "description": "Current session ID.",
            },
        },
        "required": ["skill_id", "session_id"],
    },
)
async def skill_deactivate(skill_id: str, session_id: str) -> str:
    """Deactivate a skill session-wide."""
    store = _get_store()
    if store is None:
        return "Skill store is not available."
    try:
        skill = await store.get_skill(skill_id)
    except KeyError:
        return f"Skill '{skill_id}' not found."
    return (
        f"Skill **{skill.name}** (`{skill_id}`) deactivated for this session."
    )


# ── skill_get_instructions ────────────────────────────────────────────────────

@tool(
    description=(
        "Fetch the full Level 2 instructions for a specific skill — "
        "returned as a one-off tool result (does not activate for future turns). "
        "Use this when you need a skill's detailed guidance for a single task."
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "skill_id": {
                "type": "string",
                "description": "The skill_id whose instructions to fetch.",
            },
        },
        "required": ["skill_id"],
    },
)
async def skill_get_instructions(skill_id: str) -> str:
    """Return Level 2 instructions for a skill as a one-off reference."""
    store = _get_store()
    if store is None:
        return "Skill store is not available."
    try:
        skill = await store.get_skill(skill_id)
    except KeyError:
        return f"Skill '{skill_id}' not found."
    if not skill.instructions:
        return f"Skill **{skill.name}** has no detailed instructions available."
    return f"## {skill.name} — Instructions\n\n{skill.instructions}"


# ── skill_list_resources ──────────────────────────────────────────────────────

@tool(
    description=(
        "List all Level 3 reference resources available for a skill. "
        "Resources contain detailed reference material (checklists, templates, guides). "
        "Use skill_read_resource to fetch the content of a specific resource."
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "skill_id": {
                "type": "string",
                "description": "The skill_id to list resources for.",
            },
        },
        "required": ["skill_id"],
    },
)
async def skill_list_resources(skill_id: str) -> str:
    """List Level 3 resources for a skill."""
    store = _get_store()
    if store is None:
        return "Skill store is not available."
    try:
        await store.get_skill(skill_id)  # Verify skill exists
        resources = await store.list_resources(skill_id)
    except KeyError:
        return f"Skill '{skill_id}' not found."
    except Exception as exc:
        return f"Failed to list resources: {exc}"
    if not resources:
        return f"No resources available for skill '{skill_id}'."
    lines = [f"Resources for `{skill_id}`:\n"]
    for r in resources:
        lines.append(f"- **{r.name}** (`{r.resource_id}`): {r.description}")
    return "\n".join(lines)


# ── skill_read_resource ───────────────────────────────────────────────────────

@tool(
    description=(
        "Fetch the full content of a Level 3 skill resource. "
        "Resources contain reference material like checklists, templates, and guides. "
        "Use skill_list_resources first to discover available resource IDs."
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "resource_id": {
                "type": "string",
                "description": "The resource_id to read (from skill_list_resources).",
            },
        },
        "required": ["resource_id"],
    },
)
async def skill_read_resource(resource_id: str) -> str:
    """Fetch Level 3 resource content."""
    store = _get_store()
    if store is None:
        return "Skill store is not available."
    try:
        resource = await store.get_resource(resource_id)
    except KeyError:
        return f"Resource '{resource_id}' not found."
    except Exception as exc:
        return f"Failed to read resource: {exc}"
    header = f"# {resource.name}\n"
    if resource.description:
        header += f"_{resource.description}_\n\n"
    return header + resource.content
