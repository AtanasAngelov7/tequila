"""Soul Editor API — LLM-assisted soul configuration (§4.1a, Sprint 14a).

Endpoints
---------
POST /api/agents/{agent_id}/soul/generate        — LLM-generate a soul from description
POST /api/agents/{agent_id}/soul/preview         — preview rendered system prompt
GET  /api/agents/{agent_id}/soul/history         — list soul version history
GET  /api/agents/{agent_id}/soul/history/{v}     — get a specific version
POST /api/agents/{agent_id}/soul/restore/{v}     — restore a soul version
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.agent.soul_editor import get_soul_editor
from app.api.deps import require_gateway_token

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/agents",
    tags=["soul-editor"],
    dependencies=[Depends(require_gateway_token)],
)


# ── Request models ────────────────────────────────────────────────────────────


class GenerateSoulRequest(BaseModel):
    description: str
    """Free-form personality description."""
    provider_id: str | None = None
    model: str | None = None
    save: bool = False
    """If True, save the generated soul to the agent immediately."""
    change_note: str = "LLM-generated soul"


class PreviewSoulRequest(BaseModel):
    soul: dict
    """SoulConfig field dict to preview."""


class RestoreVersionRequest(BaseModel):
    change_note: str = "Restored from version history"


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/{agent_id}/soul/generate", response_model=dict)
async def generate_soul(agent_id: str, body: GenerateSoulRequest) -> dict:
    """Use an LLM to generate a SoulConfig from a personality description.

    Returns generated soul fields and a rendered preview.
    Optionally saves the soul to the agent (save=true).
    """
    from app.agent.store import get_agent_store
    from app.agent.models import SoulConfig

    agent_store = get_agent_store()
    try:
        agent = await agent_store.get_by_id(agent_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    editor = get_soul_editor()
    soul_fields = await editor.generate_soul(
        body.description,
        agent_id=agent_id,
        provider_id=body.provider_id,
        model=body.model,
    )

    # Render preview
    preview = editor.preview_soul(soul_fields)

    result: dict = {"soul": soul_fields, "preview": preview}

    if body.save:
        # Merge generated fields into existing soul
        existing = agent.soul.model_dump()
        existing.update(soul_fields)
        new_soul = SoulConfig(**existing)
        await agent_store.update(agent_id, version=agent.version, soul=new_soul)
        # Save to version history
        version = await editor.save_version(
            agent_id, new_soul.model_dump_json(), change_note=body.change_note
        )
        result["saved"] = True
        result["version_num"] = version.version_num
    else:
        result["saved"] = False

    return result


@router.post("/{agent_id}/soul/preview", response_model=dict)
async def preview_soul(agent_id: str, body: PreviewSoulRequest) -> dict:
    """Render a full system prompt preview from soul field data."""
    from app.agent.store import get_agent_store
    try:
        from app.agent.store import get_agent_store
        await get_agent_store().get_by_id(agent_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    editor = get_soul_editor()
    try:
        preview = editor.preview_soul(body.soul)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid soul configuration: {exc}")
    return {"preview": preview}


@router.get("/{agent_id}/soul/history", response_model=list[dict])
async def list_soul_history(agent_id: str, limit: int = 50) -> list[dict]:
    """Return soul version history for an agent (newest-first)."""
    from app.agent.store import get_agent_store
    try:
        await get_agent_store().get_by_id(agent_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")

    editor = get_soul_editor()
    versions = await editor.list_versions(agent_id, limit=limit)
    return [
        {
            "version_id": v.version_id,
            "agent_id": v.agent_id,
            "version_num": v.version_num,
            "change_note": v.change_note,
            "created_at": v.created_at.isoformat(),
        }
        for v in versions
    ]


@router.get("/{agent_id}/soul/history/{version_num}", response_model=dict)
async def get_soul_version(agent_id: str, version_num: int) -> dict:
    """Get a specific soul version including its full JSON."""
    editor = get_soul_editor()
    try:
        version = await editor.get_version(agent_id, version_num)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Version {version_num} not found")
    return {
        "version_id": version.version_id,
        "agent_id": version.agent_id,
        "version_num": version.version_num,
        "soul_json": version.soul_json,
        "change_note": version.change_note,
        "created_at": version.created_at.isoformat(),
    }


@router.post("/{agent_id}/soul/restore/{version_num}", response_model=dict)
async def restore_soul_version(
    agent_id: str,
    version_num: int,
    body: RestoreVersionRequest,
) -> dict:
    """Restore a historical soul version as the agent's active soul."""
    import json
    from app.agent.models import SoulConfig
    from app.agent.store import get_agent_store

    agent_store = get_agent_store()
    editor = get_soul_editor()

    try:
        agent = await agent_store.get_by_id(agent_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    try:
        version = await editor.get_version(agent_id, version_num)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Version {version_num} not found")

    soul_data = json.loads(version.soul_json)
    try:
        restored_soul = SoulConfig(**soul_data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Stored soul is invalid: {exc}")

    await agent_store.update(agent_id, version=agent.version, soul=restored_soul)
    # Save restore as a new history entry
    new_version = await editor.save_version(
        agent_id,
        restored_soul.model_dump_json(),
        change_note=f"{body.change_note} (from v{version_num})",
    )

    return {
        "agent_id": agent_id,
        "restored_from_version": version_num,
        "new_version_num": new_version.version_num,
    }
