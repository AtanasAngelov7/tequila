"""Sprint 04 — Agent management API (§4.1, §4.2).

Endpoints
---------
GET    /api/agents              — list agents
POST   /api/agents              — create agent
GET    /api/agents/{agent_id}   — get agent
PATCH  /api/agents/{agent_id}   — update agent (OCC)
DELETE /api/agents/{agent_id}   — delete agent
POST   /api/agents/{agent_id}/clone   — clone agent
GET    /api/agents/{agent_id}/soul    — get soul config
PUT    /api/agents/{agent_id}/soul    — update soul config
GET    /api/agents/{agent_id}/export  — export agent JSON
POST   /api/agents/import             — import agent JSON
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.agent.models import AgentConfig, SoulConfig
from app.agent.store import get_agent_store
from app.api.deps import require_gateway_token
from app.exceptions import AgentNotFoundError, ConflictError

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/agents",
    tags=["agents"],
    dependencies=[Depends(require_gateway_token)],
)


# ── Request / Response models ─────────────────────────────────────────────────


class AgentCreateRequest(BaseModel):
    name: str
    provider: str = "anthropic"
    default_model: str = "anthropic:claude-sonnet-4-5"
    persona: str = "a helpful AI assistant"
    role: str = "main"
    is_admin: bool = False
    soul: dict[str, Any] | None = None


class AgentUpdateRequest(BaseModel):
    version: int
    name: str | None = None
    provider: str | None = None
    default_model: str | None = None
    persona: str | None = None
    role: str | None = None
    is_admin: bool | None = None
    status: str | None = None
    soul: dict[str, Any] | None = None
    tools: list[str] | None = None
    skills: list[str] | None = None
    escalation: dict[str, Any] | None = None


class SoulUpdateRequest(BaseModel):
    version: int
    soul: dict[str, Any]


class AgentCloneRequest(BaseModel):
    name: str | None = None


def _agent_response(agent: AgentConfig) -> dict[str, Any]:
    d = agent.model_dump(mode="json")
    return d


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("", summary="List agents")
async def list_agents(
    status: str | None = Query(None),
    role: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    store = get_agent_store()
    agents = await store.list(status=status, role=role, q=q, limit=limit, offset=offset)
    return {"agents": [_agent_response(a) for a in agents], "count": len(agents)}


@router.post("", status_code=201, summary="Create agent")
async def create_agent(
    body: AgentCreateRequest,
) -> dict[str, Any]:
    store = get_agent_store()
    soul = SoulConfig(**body.soul) if body.soul else None
    agent = await store.create(
        name=body.name,
        provider=body.provider,
        default_model=body.default_model,
        persona=body.persona,
        role=body.role,
        is_admin=body.is_admin,
        soul=soul,
    )
    return _agent_response(agent)


@router.get("/{agent_id}", summary="Get agent")
async def get_agent(
    agent_id: str,
) -> dict[str, Any]:
    store = get_agent_store()
    try:
        agent = await store.get_by_id(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _agent_response(agent)


@router.patch("/{agent_id}", summary="Update agent (OCC)")
async def update_agent(
    agent_id: str,
    body: AgentUpdateRequest,
) -> dict[str, Any]:
    store = get_agent_store()
    fields: dict[str, Any] = {}
    for attr in ("name", "provider", "default_model", "persona", "role", "is_admin", "status"):
        val = getattr(body, attr)
        if val is not None:
            fields[attr] = val
    if body.soul is not None:
        fields["soul"] = SoulConfig(**body.soul)
    if body.tools is not None:
        fields["tools"] = body.tools
    if body.skills is not None:
        fields["skills"] = body.skills
    if body.escalation is not None:
        fields["escalation"] = json.dumps(body.escalation)

    try:
        agent = await store.update(agent_id, version=body.version, **fields)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _agent_response(agent)


@router.delete("/{agent_id}", status_code=204, summary="Delete agent")
async def delete_agent(
    agent_id: str,
) -> None:
    store = get_agent_store()
    try:
        await store.delete(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{agent_id}/clone", status_code=201, summary="Clone agent")
async def clone_agent(
    agent_id: str,
    body: AgentCloneRequest | None = None,
) -> dict[str, Any]:
    store = get_agent_store()
    new_name = body.name if body else None
    try:
        cloned = await store.clone(agent_id, new_name=new_name)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _agent_response(cloned)


# ── Soul sub-resource ─────────────────────────────────────────────────────────


@router.get("/{agent_id}/soul", summary="Get agent soul config")
async def get_soul(
    agent_id: str,
) -> dict[str, Any]:
    store = get_agent_store()
    try:
        agent = await store.get_by_id(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return agent.soul.model_dump(mode="json") if agent.soul else {}


@router.put("/{agent_id}/soul", summary="Update agent soul config")
async def update_soul(
    agent_id: str,
    body: SoulUpdateRequest,
) -> dict[str, Any]:
    store = get_agent_store()
    soul = SoulConfig(**body.soul)
    try:
        agent = await store.update(agent_id, version=body.version, soul=soul)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return agent.soul.model_dump(mode="json") if agent.soul else {}


# ── Import / Export ───────────────────────────────────────────────────────────


@router.get("/{agent_id}/export", summary="Export agent as JSON")
async def export_agent(
    agent_id: str,
) -> dict[str, Any]:
    store = get_agent_store()
    try:
        agent = await store.get_by_id(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    data = _agent_response(agent)
    data.pop("agent_id", None)
    data.pop("created_at", None)
    data.pop("updated_at", None)
    data.pop("version", None)
    return {"schema_version": "04", "agent": data}


@router.post("/import", status_code=201, summary="Import agent from JSON")
async def import_agent(
    body: dict[str, Any],
) -> dict[str, Any]:
    store = get_agent_store()
    agent_data = body.get("agent", body)
    soul_data = agent_data.pop("soul", None)
    soul = SoulConfig(**soul_data) if soul_data else None
    agent = await store.create(
        name=agent_data.get("name", "Imported Agent"),
        provider=agent_data.get("provider", "anthropic"),
        default_model=agent_data.get("default_model", "anthropic:claude-sonnet-4-5"),
        persona=agent_data.get("persona", "a helpful AI assistant"),
        soul=soul,
        role=agent_data.get("role", "main"),
        is_admin=agent_data.get("is_admin", False),
    )
    return _agent_response(agent)
