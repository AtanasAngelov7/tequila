"""Audit sinks & stats REST API (§12.1–12.3 extension, Sprint 14b D2).

Routes:
  GET    /api/audit/stats                    — aggregate counts
  GET    /api/audit/sinks                    — list sinks
  POST   /api/audit/sinks                    — create sink
  GET    /api/audit/sinks/{id}               — get sink
  PATCH  /api/audit/sinks/{id}               — update sink
  DELETE /api/audit/sinks/{id}               — remove sink
  GET    /api/audit/sinks/{id}/retention     — get retention policy
  PUT    /api/audit/sinks/{id}/retention     — set retention policy
  POST   /api/audit/retention/apply          — trigger pruning
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import require_gateway_token
from app.audit.sinks import AuditRetention, AuditSink, get_audit_sink_manager

router = APIRouter(prefix="/api/audit", tags=["audit"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class SinkIn(BaseModel):
    kind: str
    name: str
    config: dict[str, Any] = {}
    enabled: bool = True


class SinkUpdate(BaseModel):
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class RetentionIn(BaseModel):
    retain_days: int = 90
    max_events: int | None = None


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/stats", dependencies=[Depends(require_gateway_token)])
async def audit_stats() -> dict:
    mgr = get_audit_sink_manager()
    return await mgr.stats()


@router.get(
    "/sinks",
    response_model=list[AuditSink],
    dependencies=[Depends(require_gateway_token)],
)
async def list_sinks() -> list[AuditSink]:
    mgr = get_audit_sink_manager()
    return await mgr.list_sinks()


@router.post(
    "/sinks",
    response_model=AuditSink,
    status_code=201,
    dependencies=[Depends(require_gateway_token)],
)
async def create_sink(body: SinkIn) -> AuditSink:
    mgr = get_audit_sink_manager()
    sink = AuditSink(kind=body.kind, name=body.name, config=body.config, enabled=body.enabled)  # type: ignore[arg-type]
    return await mgr.create_sink(sink)


@router.get(
    "/sinks/{sink_id}",
    response_model=AuditSink,
    dependencies=[Depends(require_gateway_token)],
)
async def get_sink(sink_id: str) -> AuditSink:
    mgr = get_audit_sink_manager()
    try:
        return await mgr.get_sink(sink_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Sink not found")


@router.patch(
    "/sinks/{sink_id}",
    response_model=AuditSink,
    dependencies=[Depends(require_gateway_token)],
)
async def update_sink(sink_id: str, body: SinkUpdate) -> AuditSink:
    mgr = get_audit_sink_manager()
    try:
        sink = await mgr.get_sink(sink_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Sink not found")
    updates: dict[str, Any] = {}
    if body.config is not None:
        updates["config"] = body.config
    if body.enabled is not None:
        updates["enabled"] = body.enabled
    return await mgr.update_sink(sink_id, **updates)


@router.delete(
    "/sinks/{sink_id}",
    dependencies=[Depends(require_gateway_token)],
    status_code=204,
)
async def delete_sink(sink_id: str) -> None:
    mgr = get_audit_sink_manager()
    await mgr.delete_sink(sink_id)


@router.get(
    "/sinks/{sink_id}/retention",
    response_model=AuditRetention,
    dependencies=[Depends(require_gateway_token)],
)
async def get_retention(sink_id: str) -> AuditRetention:
    mgr = get_audit_sink_manager()
    try:
        policy = await mgr.get_retention(sink_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Sink not found")
    if policy is None:
        raise HTTPException(status_code=404, detail="No retention policy for this sink")
    return policy


@router.put(
    "/sinks/{sink_id}/retention",
    response_model=AuditRetention,
    dependencies=[Depends(require_gateway_token)],
)
async def set_retention(sink_id: str, body: RetentionIn) -> AuditRetention:
    mgr = get_audit_sink_manager()
    policy = AuditRetention(sink_id=sink_id, retain_days=body.retain_days, max_events=body.max_events)
    await mgr.set_retention(policy)
    return policy


@router.post("/retention/apply", dependencies=[Depends(require_gateway_token)])
async def apply_retention() -> dict[str, str]:
    mgr = get_audit_sink_manager()
    await mgr.apply_retention()
    return {"status": "ok"}
