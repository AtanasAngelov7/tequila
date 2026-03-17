"""Skills API — Skill CRUD, resource CRUD, agent assignment, import/export (§4.5.5, Sprint 14a).

Endpoints
---------
GET    /api/skills                             — list skills
POST   /api/skills                             — create skill
GET    /api/skills/{skill_id}                  — get skill
PATCH  /api/skills/{skill_id}                  — update skill
DELETE /api/skills/{skill_id}                  — delete skill
POST   /api/skills/import                      — import skill (JSON/YAML v1.1 + v1.0 compat)
GET    /api/skills/{skill_id}/export           — export skill as JSON v1.1
POST   /api/skills/{skill_id}/clone            — clone skill (new ID, copy content)
GET    /api/agents/{agent_id}/skills           — list skills assigned to agent
POST   /api/agents/{agent_id}/skills           — assign skill to agent
DELETE /api/agents/{agent_id}/skills/{skill_id} — remove skill from agent
GET    /api/skills/{skill_id}/resources        — list Level 3 resources
POST   /api/skills/{skill_id}/resources        — create resource
GET    /api/skills/{skill_id}/resources/{resource_id} — get resource
PATCH  /api/skills/{skill_id}/resources/{resource_id} — update resource
DELETE /api/skills/{skill_id}/resources/{resource_id} — delete resource
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.agent.skills import (
    SkillDef,
    SkillResource,
    get_skill_store,
    skill_from_import_dict,
    skill_to_export_dict,
)
from app.api.deps import require_gateway_token

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["skills"],
    dependencies=[Depends(require_gateway_token)],
)


# ── Request / Response models ─────────────────────────────────────────────────


class SkillCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    version: str = "1.0.0"
    summary: str = ""
    instructions: str = ""
    required_tools: list[str] = []
    recommended_tools: list[str] = []
    activation_mode: str = "trigger"
    trigger_patterns: list[str] = []
    trigger_tool_presence: list[str] = []
    priority: int = 100
    tags: list[str] = []
    author: str = "user"


class SkillUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    version: str | None = None
    summary: str | None = None
    instructions: str | None = None
    required_tools: list[str] | None = None
    recommended_tools: list[str] | None = None
    activation_mode: str | None = None
    trigger_patterns: list[str] | None = None
    trigger_tool_presence: list[str] | None = None
    priority: int | None = None
    tags: list[str] | None = None
    author: str | None = None


class ResourceCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    content: str


class ResourceUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None


class AssignSkillRequest(BaseModel):
    skill_id: str


class ImportSkillRequest(BaseModel):
    data: dict  # v1.0 or v1.1 payload


def _skill_dict(skill: SkillDef) -> dict:
    return {
        "skill_id": skill.skill_id,
        "name": skill.name,
        "description": skill.description,
        "version": skill.version,
        "summary": skill.summary,
        "instructions": skill.instructions,
        "required_tools": skill.required_tools,
        "recommended_tools": skill.recommended_tools,
        "activation_mode": skill.activation_mode,
        "trigger_patterns": skill.trigger_patterns,
        "trigger_tool_presence": skill.trigger_tool_presence,
        "priority": skill.priority,
        "tags": skill.tags,
        "author": skill.author,
        "is_builtin": skill.is_builtin,
        "created_at": skill.created_at.isoformat(),
        "updated_at": skill.updated_at.isoformat(),
    }


def _resource_dict(r: SkillResource) -> dict:
    return {
        "resource_id": r.resource_id,
        "skill_id": r.skill_id,
        "name": r.name,
        "description": r.description,
        "content": r.content,
        "content_tokens": r.content_tokens,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


# ── Skill CRUD ────────────────────────────────────────────────────────────────


@router.get("/api/skills", response_model=list[dict])
async def list_skills(
    q: str | None = Query(default=None, description="Search name/description"),
    tags: str | None = Query(default=None, description="Comma-separated tag filter"),
    is_builtin: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """List all skills with optional filtering."""
    store = get_skill_store()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    skills = await store.list_skills(
        tags=tag_list, is_builtin=is_builtin, q=q, limit=limit, offset=offset
    )
    return [_skill_dict(s) for s in skills]


@router.post("/api/skills", response_model=dict, status_code=201)
async def create_skill(body: SkillCreateRequest) -> dict:
    """Create a new skill definition."""
    store = get_skill_store()
    now = datetime.now(timezone.utc)
    skill = SkillDef(
        name=body.name,
        description=body.description,
        version=body.version,
        summary=body.summary,
        instructions=body.instructions,
        required_tools=body.required_tools,
        recommended_tools=body.recommended_tools,
        activation_mode=body.activation_mode,
        trigger_patterns=body.trigger_patterns,
        trigger_tool_presence=body.trigger_tool_presence,
        priority=body.priority,
        tags=body.tags,
        author=body.author,
        created_at=now,
        updated_at=now,
    )
    created = await store.create_skill(skill)
    return _skill_dict(created)


@router.get("/api/skills/{skill_id}", response_model=dict)
async def get_skill(skill_id: str) -> dict:
    """Get a skill by ID."""
    store = get_skill_store()
    try:
        skill = await store.get_skill(skill_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
    return _skill_dict(skill)


@router.patch("/api/skills/{skill_id}", response_model=dict)
async def update_skill(skill_id: str, body: SkillUpdateRequest) -> dict:
    """Partial update a skill."""
    store = get_skill_store()
    try:
        await store.get_skill(skill_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
    updates = body.model_dump(exclude_none=True)
    updated = await store.update_skill(skill_id, updates)
    return _skill_dict(updated)


@router.delete("/api/skills/{skill_id}", status_code=204)
async def delete_skill(skill_id: str) -> None:
    """Delete a skill (cascades to resources)."""
    store = get_skill_store()
    try:
        skill = await store.get_skill(skill_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
    if skill.is_builtin:
        raise HTTPException(status_code=400, detail="Cannot delete built-in skills")
    await store.delete_skill(skill_id)


# ── Import / Export / Clone ────────────────────────────────────────────────────


@router.post("/api/skills/import", response_model=dict, status_code=201)
async def import_skill(body: ImportSkillRequest) -> dict:
    """Import a skill from a v1.0 or v1.1 JSON payload."""
    store = get_skill_store()
    try:
        skill, resources = skill_from_import_dict(body.data)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid skill payload: {exc}")
    # Assign a fresh ID to avoid collision
    skill = skill.model_copy(update={"skill_id": f"skill:{uuid.uuid4().hex[:12]}"})
    for i, r in enumerate(resources):
        resources[i] = r.model_copy(update={
            "skill_id": skill.skill_id,
            "resource_id": f"res:{uuid.uuid4().hex[:12]}",
        })
    created = await store.create_skill(skill)
    for r in resources:
        await store.create_resource(r)
    return _skill_dict(created)


@router.get("/api/skills/{skill_id}/export", response_model=dict)
async def export_skill(skill_id: str) -> dict:
    """Export a skill as a v1.1 JSON payload (includes resources)."""
    store = get_skill_store()
    try:
        skill = await store.get_skill(skill_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
    resources = await store.list_resources(skill_id)
    return skill_to_export_dict(skill, resources)


@router.post("/api/skills/{skill_id}/clone", response_model=dict, status_code=201)
async def clone_skill(skill_id: str) -> dict:
    """Clone a skill with a new ID and '(copy)' suffix on name."""
    store = get_skill_store()
    try:
        skill = await store.get_skill(skill_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
    now = datetime.now(timezone.utc)
    new_id = f"skill:{uuid.uuid4().hex[:12]}"
    clone = SkillDef(
        skill_id=new_id,
        name=f"{skill.name} (copy)",
        description=skill.description,
        version=skill.version,
        summary=skill.summary,
        instructions=skill.instructions,
        required_tools=skill.required_tools,
        recommended_tools=skill.recommended_tools,
        activation_mode=skill.activation_mode,
        trigger_patterns=skill.trigger_patterns,
        trigger_tool_presence=skill.trigger_tool_presence,
        priority=skill.priority,
        tags=skill.tags,
        author=skill.author,
        is_builtin=False,
        created_at=now,
        updated_at=now,
    )
    created = await store.create_skill(clone)
    # Clone resources
    for r in await store.list_resources(skill_id):
        await store.create_resource(SkillResource(
            skill_id=new_id,
            name=r.name,
            description=r.description,
            content=r.content,
            content_tokens=r.content_tokens,
            created_at=now,
            updated_at=now,
        ))
    return _skill_dict(created)


# ── Agent ↔ Skill Assignment ───────────────────────────────────────────────────


@router.get("/api/agents/{agent_id}/skills", response_model=list[dict])
async def list_agent_skills(agent_id: str) -> list[dict]:
    """List all skills assigned to an agent."""
    from app.agent.store import get_agent_store
    agent_store = get_agent_store()
    try:
        agent = await agent_store.get_by_id(agent_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    skill_store = get_skill_store()
    skills = await skill_store.get_skills_for_agent(agent.skills)
    return [_skill_dict(s) for s in skills]


@router.post("/api/agents/{agent_id}/skills", response_model=dict, status_code=201)
async def assign_skill_to_agent(agent_id: str, body: AssignSkillRequest) -> dict:
    """Assign a skill to an agent."""
    from app.agent.store import get_agent_store
    agent_store = get_agent_store()
    skill_store = get_skill_store()
    try:
        agent = await agent_store.get_by_id(agent_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    try:
        skill = await skill_store.get_skill(body.skill_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill not found: {body.skill_id}")
    if body.skill_id in agent.skills:
        return {"agent_id": agent_id, "skill_id": body.skill_id, "status": "already_assigned"}
    new_skills = agent.skills + [body.skill_id]
    await agent_store.update(agent_id, version=agent.version, skills=new_skills)
    return {"agent_id": agent_id, "skill_id": body.skill_id, "status": "assigned"}


@router.delete("/api/agents/{agent_id}/skills/{skill_id}", status_code=204)
async def unassign_skill_from_agent(agent_id: str, skill_id: str) -> None:
    """Remove a skill assignment from an agent."""
    from app.agent.store import get_agent_store
    agent_store = get_agent_store()
    try:
        agent = await agent_store.get_by_id(agent_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    if skill_id not in agent.skills:
        raise HTTPException(status_code=404, detail=f"Skill {skill_id} not assigned to agent")
    new_skills = [s for s in agent.skills if s != skill_id]
    await agent_store.update(agent_id, version=agent.version, skills=new_skills)


# ── Skill Resources (Level 3) ─────────────────────────────────────────────────


@router.get("/api/skills/{skill_id}/resources", response_model=list[dict])
async def list_skill_resources(skill_id: str) -> list[dict]:
    """List Level 3 resources for a skill."""
    store = get_skill_store()
    try:
        await store.get_skill(skill_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
    resources = await store.list_resources(skill_id)
    return [_resource_dict(r) for r in resources]


@router.post("/api/skills/{skill_id}/resources", response_model=dict, status_code=201)
async def create_skill_resource(skill_id: str, body: ResourceCreateRequest) -> dict:
    """Create a new Level 3 resource for a skill."""
    store = get_skill_store()
    try:
        await store.get_skill(skill_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
    now = datetime.now(timezone.utc)
    resource = SkillResource(
        skill_id=skill_id,
        name=body.name,
        description=body.description,
        content=body.content,
        created_at=now,
        updated_at=now,
    )
    created = await store.create_resource(resource)
    return _resource_dict(created)


@router.get("/api/skills/{skill_id}/resources/{resource_id}", response_model=dict)
async def get_skill_resource(skill_id: str, resource_id: str) -> dict:
    """Get a specific resource."""
    store = get_skill_store()
    try:
        resource = await store.get_resource(resource_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Resource not found: {resource_id}")
    if resource.skill_id != skill_id:
        raise HTTPException(status_code=404, detail="Resource does not belong to this skill")
    return _resource_dict(resource)


@router.patch("/api/skills/{skill_id}/resources/{resource_id}", response_model=dict)
async def update_skill_resource(skill_id: str, resource_id: str, body: ResourceUpdateRequest) -> dict:
    """Partial update a resource."""
    store = get_skill_store()
    try:
        resource = await store.get_resource(resource_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Resource not found: {resource_id}")
    if resource.skill_id != skill_id:
        raise HTTPException(status_code=404, detail="Resource does not belong to this skill")
    updates = body.model_dump(exclude_none=True)
    updated = await store.update_resource(resource_id, updates)
    return _resource_dict(updated)


@router.delete("/api/skills/{skill_id}/resources/{resource_id}", status_code=204)
async def delete_skill_resource(skill_id: str, resource_id: str) -> None:
    """Delete a resource."""
    store = get_skill_store()
    try:
        resource = await store.get_resource(resource_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Resource not found: {resource_id}")
    if resource.skill_id != skill_id:
        raise HTTPException(status_code=404, detail="Resource does not belong to this skill")
    await store.delete_resource(resource_id)
