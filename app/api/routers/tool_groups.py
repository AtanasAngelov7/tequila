"""Tool Groups API — per-agent tool group enable/disable (§4.5.8, Sprint 14a).

Endpoints
---------
GET  /api/tools/groups                        — list all available tool groups
GET  /api/agents/{agent_id}/tools             — get agent's enabled tool groups
PUT  /api/agents/{agent_id}/tools             — set agent's enabled tool groups (replace list)
POST /api/agents/{agent_id}/tools/{group_id}  — enable a specific tool group
DELETE /api/agents/{agent_id}/tools/{group_id} — disable a specific tool group
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.agent.skills import TOOL_GROUPS
from app.api.deps import require_gateway_token

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["tool-groups"],
    dependencies=[Depends(require_gateway_token)],
)


class SetToolGroupsRequest(BaseModel):
    groups: list[str]
    """List of group_ids to enable."""


@router.get("/tools/groups", response_model=list[dict])
async def list_tool_groups() -> list[dict]:
    """Return all available tool groups with their tool lists."""
    return list(TOOL_GROUPS.values())


@router.get("/agents/{agent_id}/tools", response_model=dict)
async def get_agent_tools(agent_id: str) -> dict:
    """Get the enabled tool groups for an agent."""
    from app.agent.store import get_agent_store
    store = get_agent_store()
    try:
        agent = await store.get_by_id(agent_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    enabled = agent.tools
    groups = []
    for gid in enabled:
        if gid in TOOL_GROUPS:
            groups.append(TOOL_GROUPS[gid])
        elif gid.startswith("plugin:"):
            groups.append({"group_id": gid, "name": gid, "description": "Plugin tool group", "tools": []})
    return {
        "agent_id": agent_id,
        "enabled_groups": enabled,
        "groups": groups,
    }


@router.put("/agents/{agent_id}/tools", response_model=dict)
async def set_agent_tools(agent_id: str, body: SetToolGroupsRequest) -> dict:
    """Replace the full list of enabled tool groups for an agent."""
    from app.agent.store import get_agent_store
    store = get_agent_store()
    try:
        agent = await store.get_by_id(agent_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    # Validate known group IDs (allow plugin: prefix freely)
    unknown = [g for g in body.groups if g not in TOOL_GROUPS and not g.startswith("plugin:")]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown tool group(s): {unknown}")
    await store.update(agent_id, version=agent.version, tools=body.groups)
    return {"agent_id": agent_id, "enabled_groups": body.groups}


@router.post("/agents/{agent_id}/tools/{group_id}", response_model=dict, status_code=201)
async def enable_tool_group(agent_id: str, group_id: str) -> dict:
    """Enable a specific tool group for an agent."""
    from app.agent.store import get_agent_store
    store = get_agent_store()
    try:
        agent = await store.get_by_id(agent_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    if group_id not in TOOL_GROUPS and not group_id.startswith("plugin:"):
        raise HTTPException(status_code=404, detail=f"Tool group not found: {group_id}")
    if group_id in agent.tools:
        return {"agent_id": agent_id, "group_id": group_id, "status": "already_enabled"}
    new_tools = agent.tools + [group_id]
    await store.update(agent_id, version=agent.version, tools=new_tools)
    return {"agent_id": agent_id, "group_id": group_id, "status": "enabled"}


@router.delete("/agents/{agent_id}/tools/{group_id}", status_code=204)
async def disable_tool_group(agent_id: str, group_id: str) -> None:
    """Disable a specific tool group for an agent."""
    from app.agent.store import get_agent_store
    store = get_agent_store()
    try:
        agent = await store.get_by_id(agent_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    if group_id not in agent.tools:
        raise HTTPException(status_code=404, detail=f"Tool group '{group_id}' not enabled on this agent")
    new_tools = [t for t in agent.tools if t != group_id]
    await store.update(agent_id, version=agent.version, tools=new_tools)
