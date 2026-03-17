"""Budget / cost-tracking REST API (§23.1–23.5, Sprint 14b D3).

Routes:
  GET    /api/budget/summary             — period summary
  GET    /api/budget/by-agent            — breakdown by agent
  GET    /api/budget/by-provider         — breakdown by provider
  GET    /api/budget/usage               — paginated turn costs
  GET    /api/budget/pricing             — list provider pricing
  PUT    /api/budget/pricing             — upsert pricing entry
  GET    /api/budget/caps                — list caps
  PUT    /api/budget/caps/{period}       — set cap
  DELETE /api/budget/caps/{period}       — remove cap
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.deps import require_gateway_token
from app.budget import BudgetCap, ProviderPricing, get_budget_tracker

router = APIRouter(prefix="/api/budget", tags=["budget"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class ProviderPricingIn(BaseModel):
    provider_id: str
    model: str
    input_cost_per_1k: float
    output_cost_per_1k: float


class BudgetCapIn(BaseModel):
    limit_usd: float
    action: Literal["warn", "block"] = "warn"


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/summary", dependencies=[Depends(require_gateway_token)])
async def get_summary(
    period: Literal["daily", "monthly"] = Query(default="daily"),
    date_or_month: str | None = Query(default=None, description="YYYY-MM-DD or YYYY-MM"),
) -> dict:
    tracker = get_budget_tracker()
    summary = await tracker.get_summary(period=period, date_or_month=date_or_month)
    return summary.model_dump()


@router.get("/by-agent", dependencies=[Depends(require_gateway_token)])
async def get_by_agent(
    period: Literal["daily", "monthly"] = Query(default="daily"),
    date_or_month: str | None = Query(default=None),
) -> list[dict]:
    tracker = get_budget_tracker()
    rows = await tracker.get_by_agent(period=period, date_or_month=date_or_month)
    return rows


@router.get("/by-provider", dependencies=[Depends(require_gateway_token)])
async def get_by_provider(
    period: Literal["daily", "monthly"] = Query(default="daily"),
    date_or_month: str | None = Query(default=None),
) -> list[dict]:
    tracker = get_budget_tracker()
    return await tracker.get_by_provider(period=period, date_or_month=date_or_month)


@router.get("/usage", dependencies=[Depends(require_gateway_token)])
async def list_usage(
    session_id: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    tracker = get_budget_tracker()
    costs = await tracker.list_turn_costs(
        session_id=session_id, agent_id=agent_id, limit=limit, offset=offset
    )
    return [c.model_dump() for c in costs]


@router.get("/pricing", dependencies=[Depends(require_gateway_token)])
async def list_pricing() -> list[dict]:
    tracker = get_budget_tracker()
    return [p.model_dump() for p in await tracker.list_pricing()]


@router.put("/pricing", dependencies=[Depends(require_gateway_token)])
async def upsert_pricing(body: ProviderPricingIn) -> dict:
    tracker = get_budget_tracker()
    pricing = ProviderPricing(
        provider_id=body.provider_id,
        model=body.model,
        input_cost_per_1k=body.input_cost_per_1k,
        output_cost_per_1k=body.output_cost_per_1k,
    )
    await tracker.upsert_pricing(pricing)
    return {"status": "ok"}


@router.get("/caps", dependencies=[Depends(require_gateway_token)])
async def list_caps() -> list[dict]:
    tracker = get_budget_tracker()
    return [c.model_dump() for c in await tracker.list_caps()]


@router.put("/caps/{period}", dependencies=[Depends(require_gateway_token)])
async def set_cap(period: Literal["daily", "monthly"], body: BudgetCapIn) -> dict:
    tracker = get_budget_tracker()
    cap = BudgetCap(period=period, limit_usd=body.limit_usd, action=body.action)
    await tracker.set_cap(cap)
    return {"status": "ok"}


@router.delete(
    "/caps/{period}",
    dependencies=[Depends(require_gateway_token)],
    status_code=204,
)
async def delete_cap(period: Literal["daily", "monthly"]) -> None:
    tracker = get_budget_tracker()
    await tracker.delete_cap(period)
