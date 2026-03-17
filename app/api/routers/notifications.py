"""Notification REST API (§24.1–24.5, Sprint 14b D1).

Routes:
  GET    /api/notifications                  — list notifications
  PATCH  /api/notifications/{id}/read        — mark one read
  POST   /api/notifications/read-all         — mark all read
  GET    /api/notifications/preferences      — list preferences
  PUT    /api/notifications/preferences      — bulk upsert preferences
  GET    /api/notifications/unread-count     — count unread
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import require_gateway_token
from app.notifications import (
    NotificationPreference,
    get_notification_store,
)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class NotificationOut(BaseModel):
    id: str
    notification_type: str
    title: str
    body: str
    severity: str
    action_url: str | None
    source_session_key: str | None
    read: bool
    created_at: str


class PreferenceIn(BaseModel):
    notification_type: str
    channels: list[str]
    enabled: bool = True


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[NotificationOut],
    dependencies=[Depends(require_gateway_token)],
)
async def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[NotificationOut]:
    store = get_notification_store()
    items = await store.list(unread_only=unread_only, limit=limit, offset=offset)
    return [
        NotificationOut(
            id=n.id,
            notification_type=n.notification_type,
            title=n.title,
            body=n.body,
            severity=n.severity,
            action_url=n.action_url,
            source_session_key=n.source_session_key,
            read=n.read,
            created_at=n.created_at,
        )
        for n in items
    ]


@router.get("/unread-count", dependencies=[Depends(require_gateway_token)])
async def unread_count() -> dict[str, int]:
    store = get_notification_store()
    return {"count": await store.count_unread()}


@router.patch(
    "/{notification_id}/read",
    dependencies=[Depends(require_gateway_token)],
    status_code=204,
)
async def mark_read(notification_id: str) -> None:
    store = get_notification_store()
    await store.mark_read(notification_id)


@router.post(
    "/read-all",
    dependencies=[Depends(require_gateway_token)],
)
async def mark_all_read() -> dict[str, int]:
    store = get_notification_store()
    count = await store.mark_all_read()
    return {"marked": count}


@router.get(
    "/preferences",
    response_model=list[NotificationPreference],
    dependencies=[Depends(require_gateway_token)],
)
async def list_preferences() -> list[NotificationPreference]:
    store = get_notification_store()
    return await store.list_preferences()


@router.put(
    "/preferences",
    dependencies=[Depends(require_gateway_token)],
)
async def upsert_preferences(prefs: list[PreferenceIn]) -> dict[str, int]:
    store = get_notification_store()
    count = 0
    for p in prefs:
        await store.upsert_preference(
            NotificationPreference(
                notification_type=p.notification_type,
                channels=p.channels,  # type: ignore[arg-type]
                enabled=p.enabled,
            )
        )
        count += 1
    return {"updated": count}
