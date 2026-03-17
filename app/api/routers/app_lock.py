"""App-lock REST API (Sprint 14b D4).

Routes:
  GET    /api/lock/state           — lock state
  POST   /api/lock/pin             — set PIN
  POST   /api/lock/lock            — lock immediately
  POST   /api/lock/unlock          — unlock with PIN or recovery key
  DELETE /api/lock/disable         — disable lock entirely
  PATCH  /api/lock/timeout         — set idle timeout
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import require_gateway_token
from app.auth.app_lock import AppLockState, get_app_lock

router = APIRouter(prefix="/api/lock", tags=["app_lock"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class SetPinRequest(BaseModel):
    pin: str


class UnlockRequest(BaseModel):
    pin: str | None = None
    recovery_key: str | None = None


class TimeoutRequest(BaseModel):
    idle_timeout_seconds: int


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get(
    "/state",
    response_model=AppLockState,
    dependencies=[Depends(require_gateway_token)],
)
async def get_state() -> AppLockState:
    lock = get_app_lock()
    lock.record_activity()
    return await lock.get_state()


@router.post("/pin", dependencies=[Depends(require_gateway_token)])
async def set_pin(body: SetPinRequest) -> dict:
    lock = get_app_lock()
    lock.record_activity()
    try:
        recovery_key = await lock.set_pin(body.pin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "status": "pin_set",
        "recovery_key": recovery_key,
        "note": "Save this recovery key — it will not be shown again.",
    }


@router.post("/lock", dependencies=[Depends(require_gateway_token)])
async def lock_app() -> dict:
    lock = get_app_lock()
    await lock.lock()
    return {"status": "locked"}


@router.post("/unlock", dependencies=[Depends(require_gateway_token)])
async def unlock_app(body: UnlockRequest) -> dict:
    lock = get_app_lock()
    if body.pin:
        success = await lock.verify_pin(body.pin)
        if not success:
            raise HTTPException(status_code=401, detail="Invalid PIN")
    elif body.recovery_key:
        success = await lock.verify_recovery_key(body.recovery_key)
        if not success:
            raise HTTPException(status_code=401, detail="Invalid recovery key")
    else:
        raise HTTPException(status_code=400, detail="Provide pin or recovery_key")
    lock.record_activity()
    return {"status": "unlocked"}


@router.delete("/disable", dependencies=[Depends(require_gateway_token)])
async def disable_lock() -> dict:
    lock = get_app_lock()
    await lock.disable()
    return {"status": "disabled"}


@router.patch("/timeout", dependencies=[Depends(require_gateway_token)])
async def set_timeout(body: TimeoutRequest) -> dict:
    lock = get_app_lock()
    lock.record_activity()
    await lock.set_idle_timeout(body.idle_timeout_seconds)
    return {"idle_timeout_seconds": body.idle_timeout_seconds}
