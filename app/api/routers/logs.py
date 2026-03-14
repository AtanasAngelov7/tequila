"""Audit log query endpoint for Tequila v2 (§12.4, §13.4).

### Routes

| Method | Path       | Auth          | Response          |
|--------|------------|---------------|-------------------|
| GET    | /api/logs  | Gateway token | list[AuditEvent]  |
"""
from __future__ import annotations

from datetime import datetime

import aiosqlite
from fastapi import APIRouter, Depends, Query

from app.api.deps import get_db_dep, require_gateway_token
from app.audit.log import AuditEvent, query_audit_log

router = APIRouter(tags=["logs"])


@router.get(
    "/api/logs",
    response_model=list[AuditEvent],
    dependencies=[Depends(require_gateway_token)],
)
async def list_audit_logs(
    actor: str | None = Query(default=None, description="Filter by actor"),
    action: str | None = Query(default=None, description="Filter by action prefix"),
    outcome: str | None = Query(default=None, description="Filter by outcome"),
    session_key: str | None = Query(default=None, description="Filter by session key"),
    since: datetime | None = Query(default=None, description="Only events on/after this UTC datetime"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: aiosqlite.Connection = Depends(get_db_dep),
) -> list[AuditEvent]:
    """Return paginated audit log entries, newest first."""
    return await query_audit_log(
        db,
        actor=actor,
        action=action,
        outcome=outcome,
        session_key=session_key,
        since=since,
        limit=limit,
        offset=offset,
    )
