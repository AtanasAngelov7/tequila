"""Budget tracking and cost management for Tequila v2 (§23.1–23.5).

Tracks per-turn LLM costs (token counts × provider pricing), enforces daily/
monthly budget caps, and emits ``budget.warning`` / ``budget.exceeded`` gateway
events when thresholds are crossed.

Startup::

    budget_tracker = init_budget_tracker(db)
    # Wire the gateway event handler (done in app.py):
    router.on(ET.BUDGET_TURN_COST, budget_tracker.handle_turn_cost)
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import aiosqlite
from pydantic import BaseModel, Field

from app.db.connection import write_transaction

logger = logging.getLogger(__name__)


def _date_range(date_or_month: str) -> tuple[str, str]:
    """Convert a YYYY-MM-DD or YYYY-MM string to (start, exclusive_end) range.

    TD-304: Used instead of LIKE patterns for index-friendly range queries.
    """
    if len(date_or_month) == 10:  # YYYY-MM-DD
        from datetime import date as _date
        d = _date.fromisoformat(date_or_month)
        next_day = (d + timedelta(days=1)).isoformat()
        return date_or_month, next_day
    elif len(date_or_month) == 7:  # YYYY-MM
        year, month = int(date_or_month[:4]), int(date_or_month[5:7])
        start = f"{date_or_month}-01"
        if month == 12:
            end = f"{year + 1}-01-01"
        else:
            end = f"{year}-{month + 1:02d}-01"
        return start, end
    else:
        # Fallback: treat as prefix with next-char boundary
        return date_or_month, date_or_month + "\xff"


# ── Models ────────────────────────────────────────────────────────────────────


class ProviderPricing(BaseModel):
    """Pricing entry for a specific (provider, model) pair (§23.1)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    provider_id: str
    model: str
    input_cost_per_1k: float = 0.0
    """USD per 1 000 input tokens."""
    output_cost_per_1k: float = 0.0
    """USD per 1 000 output tokens."""
    effective_date: str = Field(default_factory=lambda: datetime.now(timezone.utc).date().isoformat())


class TurnCost(BaseModel):
    """Per-turn cost record (§23.1)."""

    turn_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    agent_id: str
    provider_id: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BudgetCap(BaseModel):
    """Budget cap for daily or monthly spending (§23.3)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    period: Literal["daily", "monthly"]
    limit_usd: float
    action: Literal["warn", "block"] = "warn"


class BudgetSummary(BaseModel):
    """Aggregated usage summary returned by reporting endpoints."""

    period: str
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    turn_count: int = 0


# ── Default pricing table ─────────────────────────────────────────────────────
# Approximate pricing as of early 2026. Users can override via API.

_DEFAULT_PRICING: list[dict[str, Any]] = [
    {"provider_id": "anthropic", "model": "claude-opus-4-5", "input_cost_per_1k": 0.015, "output_cost_per_1k": 0.075},
    {"provider_id": "anthropic", "model": "claude-sonnet-4-5", "input_cost_per_1k": 0.003, "output_cost_per_1k": 0.015},
    {"provider_id": "anthropic", "model": "claude-haiku-3", "input_cost_per_1k": 0.00025, "output_cost_per_1k": 0.00125},
    {"provider_id": "openai", "model": "gpt-4o", "input_cost_per_1k": 0.005, "output_cost_per_1k": 0.015},
    {"provider_id": "openai", "model": "gpt-4o-mini", "input_cost_per_1k": 0.00015, "output_cost_per_1k": 0.0006},
    {"provider_id": "openai", "model": "gpt-4-turbo", "input_cost_per_1k": 0.01, "output_cost_per_1k": 0.03},
    {"provider_id": "ollama", "model": "*", "input_cost_per_1k": 0.0, "output_cost_per_1k": 0.0},
]


# ── BudgetTracker ─────────────────────────────────────────────────────────────


class BudgetTracker:
    """Tracks LLM costs and enforces budget caps.

    Listens on the ``budget.turn_cost`` gateway event emitted by the turn loop
    after each LLM call. Persists a ``TurnCost`` record and checks caps.
    """

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db
        self._notifier: Any = None  # set by wire_notifier()

    def wire_notifier(self, notifier: Any) -> None:
        """Inject notification dispatcher (called after both are initialised)."""
        self._notifier = notifier

    # ── Gateway event handler ──────────────────────────────────────────────

    async def handle_turn_cost(self, event: Any) -> None:
        """Handle ``budget.turn_cost`` gateway event."""
        payload = getattr(event, "payload", {})
        session_id = payload.get("session_id", "")
        message_id = payload.get("message_id", "")
        input_tokens: int = int(payload.get("input_tokens", 0))
        output_tokens: int = int(payload.get("output_tokens", 0))

        # Try to get agent and provider from session
        agent_id = "unknown"
        provider_id = "unknown"
        model = "unknown"
        try:
            from app.sessions.store import get_session_store
            session = await get_session_store().get_by_id(session_id)
            agent_id = session.agent_id or "unknown"
            from app.agent.store import get_agent_store
            agent_cfg = await get_agent_store().get_by_id(agent_id)
            qualified_model = getattr(agent_cfg, "default_model", "") or "unknown"
            if ":" in qualified_model:
                provider_id, model = qualified_model.split(":", 1)
            else:
                model = qualified_model
        except Exception:
            pass

        cost_usd = await self._calculate_cost(provider_id, model, input_tokens, output_tokens)

        turn_cost = TurnCost(
            turn_id=message_id or str(uuid.uuid4()),
            session_id=session_id,
            agent_id=agent_id,
            provider_id=provider_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )
        await self._persist_turn_cost(turn_cost)
        await self._check_caps(turn_cost)

    # ── Pricing ───────────────────────────────────────────────────────────────

    async def seed_default_pricing(self) -> None:
        """Insert default pricing rows if not already present."""
        for p in _DEFAULT_PRICING:
            pid = str(uuid.uuid4())
            async with write_transaction(self._db):
                await self._db.execute(
                    """
                    INSERT OR IGNORE INTO provider_pricing
                        (id, provider_id, model, input_cost_per_1k, output_cost_per_1k)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (pid, p["provider_id"], p["model"],
                     p["input_cost_per_1k"], p["output_cost_per_1k"]),
                )

    async def _calculate_cost(
        self, provider_id: str, model: str, input_tokens: int, output_tokens: int
    ) -> float:
        """Look up pricing and compute cost_usd."""
        # Exact match first, then wildcard model
        cursor = await self._db.execute(
            """
            SELECT input_cost_per_1k, output_cost_per_1k
            FROM provider_pricing
            WHERE provider_id = ? AND (model = ? OR model = '*')
            ORDER BY CASE WHEN model = ? THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (provider_id, model, model),
        )
        row = await cursor.fetchone()
        if not row:
            return 0.0
        in_rate, out_rate = row[0], row[1]
        return (input_tokens * in_rate + output_tokens * out_rate) / 1000.0

    async def upsert_pricing(self, pricing: ProviderPricing) -> ProviderPricing:
        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT INTO provider_pricing
                    (id, provider_id, model, input_cost_per_1k, output_cost_per_1k, effective_date)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_id, model) DO UPDATE SET
                    input_cost_per_1k = excluded.input_cost_per_1k,
                    output_cost_per_1k = excluded.output_cost_per_1k,
                    effective_date = excluded.effective_date
                """,
                (pricing.id, pricing.provider_id, pricing.model,
                 pricing.input_cost_per_1k, pricing.output_cost_per_1k,
                 pricing.effective_date),
            )
        return pricing

    async def list_pricing(self) -> list[ProviderPricing]:
        cursor = await self._db.execute(
            "SELECT id, provider_id, model, input_cost_per_1k, output_cost_per_1k, effective_date "
            "FROM provider_pricing ORDER BY provider_id, model"
        )
        rows = await cursor.fetchall()
        return [ProviderPricing.model_validate(dict(r)) for r in rows]

    # ── Turn cost persistence ──────────────────────────────────────────────

    async def _persist_turn_cost(self, tc: TurnCost) -> None:
        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT OR REPLACE INTO turn_costs
                    (turn_id, session_id, agent_id, provider_id, model,
                     input_tokens, output_tokens, cost_usd, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (tc.turn_id, tc.session_id, tc.agent_id, tc.provider_id,
                 tc.model, tc.input_tokens, tc.output_tokens,
                 tc.cost_usd, tc.timestamp),
            )

    # ── Budget caps ────────────────────────────────────────────────────────

    async def set_cap(self, cap: BudgetCap) -> BudgetCap:
        cap_id = str(uuid.uuid4())
        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT INTO budget_caps (id, period, limit_usd, action, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(period) DO UPDATE SET
                    limit_usd = excluded.limit_usd,
                    action = excluded.action,
                    updated_at = excluded.updated_at
                """,
                (cap_id, cap.period, cap.limit_usd, cap.action,
                 datetime.now(timezone.utc).isoformat()),
            )
            # TD-305: Read back the actual ID (may differ on upsert conflict)
            cursor = await self._db.execute(
                "SELECT id FROM budget_caps WHERE period = ?", (cap.period,)
            )
            row = await cursor.fetchone()
            actual_id = row[0] if row else cap_id
        cap.id = actual_id
        return cap

    async def delete_cap(self, period: str) -> None:
        async with write_transaction(self._db):
            await self._db.execute(
                "DELETE FROM budget_caps WHERE period = ?", (period,)
            )

    async def list_caps(self) -> list[BudgetCap]:
        cursor = await self._db.execute(
            "SELECT id, period, limit_usd, action FROM budget_caps"
        )
        rows = await cursor.fetchall()
        return [BudgetCap.model_validate(dict(r)) for r in rows]

    async def _get_cap(self, period: Literal["daily", "monthly"]) -> BudgetCap | None:
        cursor = await self._db.execute(
            "SELECT id, period, limit_usd, action FROM budget_caps WHERE period = ?",
            (period,),
        )
        row = await cursor.fetchone()
        return BudgetCap.model_validate(dict(row)) if row else None

    # ── Cap checking ──────────────────────────────────────────────────────

    async def _check_caps(self, turn_cost: TurnCost) -> None:
        """After recording a turn cost, check daily+monthly caps."""
        now = datetime.now(timezone.utc)
        date_str = now.date().isoformat()
        month_str = now.strftime("%Y-%m")

        # TD-160: Use range queries instead of LIKE for index usage
        # Daily usage
        daily_cap = await self._get_cap("daily")
        if daily_cap:
            next_day = (now.date() + timedelta(days=1)).isoformat()
            cursor = await self._db.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM turn_costs "
                "WHERE timestamp >= ? AND timestamp < ?",
                (date_str, next_day),
            )
            row = await cursor.fetchone()
            daily_total = float(row[0]) if row else 0.0
            await self._maybe_alert(daily_total, daily_cap, "daily")

        # Monthly usage
        monthly_cap = await self._get_cap("monthly")
        if monthly_cap:
            # Compute next month boundary
            if now.month == 12:
                next_month = f"{now.year + 1}-01"
            else:
                next_month = f"{now.year}-{now.month + 1:02d}"
            cursor = await self._db.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM turn_costs "
                "WHERE timestamp >= ? AND timestamp < ?",
                (f"{month_str}-01", f"{next_month}-01"),
            )
            row = await cursor.fetchone()
            monthly_total = float(row[0]) if row else 0.0
            await self._maybe_alert(monthly_total, monthly_cap, "monthly")

    async def _maybe_alert(
        self, current: float, cap: BudgetCap, period_label: str
    ) -> None:
        ratio = current / cap.limit_usd if cap.limit_usd > 0 else 0.0
        if ratio < 0.8:
            return

        # Throttle: at most one alert per period_label per 60 seconds
        import time as _time
        now_mono = _time.monotonic()
        if not hasattr(self, "_last_alert_times"):
            self._last_alert_times: dict[str, float] = {}
        last = self._last_alert_times.get(period_label, 0.0)
        if now_mono - last < 60.0:
            return
        self._last_alert_times[period_label] = now_mono

        event_type = "budget.warning" if ratio < 1.0 else "budget.exceeded"
        body = (
            f"{period_label.capitalize()} spending: ${current:.4f} / ${cap.limit_usd:.2f} "
            f"({ratio * 100:.0f}%)."
        )
        if ratio >= 1.0 and cap.action == "block":
            body += " LLM calls are blocked."
        if self._notifier:
            try:
                await self._notifier.dispatch(
                    notification_type=event_type,
                    title="Budget warning" if ratio < 1.0 else "Budget limit reached",
                    body=body,
                    severity="warning" if ratio < 1.0 else "error",
                )
            except Exception as exc:
                logger.warning("Failed to send budget notification: %s", exc, exc_info=True)

    async def is_blocked(self) -> bool:
        """Return True if any block-mode cap is 100%+ exhausted."""
        now = datetime.now(timezone.utc)
        date_str = now.date().isoformat()
        month_str = now.strftime("%Y-%m")

        # TD-303: Use range queries instead of LIKE for index usage
        for period, start, end in [
            ("daily", date_str, (now.date() + timedelta(days=1)).isoformat()),
            ("monthly", f"{month_str}-01", f"{(now.year + 1) if now.month == 12 else now.year}-{1 if now.month == 12 else (now.month + 1):02d}-01"),
        ]:
            cap = await self._get_cap(period)  # type: ignore[arg-type]
            if not cap or cap.action != "block":
                continue
            cursor = await self._db.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM turn_costs WHERE timestamp >= ? AND timestamp < ?",
                (start, end),
            )
            row = await cursor.fetchone()
            if row and float(row[0]) >= cap.limit_usd:
                return True
        return False

    # ── Reporting ─────────────────────────────────────────────────────────

    async def get_summary(self, *, period: str, date_or_month: str) -> BudgetSummary:
        """Return aggregated cost for a day (YYYY-MM-DD) or month (YYYY-MM)."""
        # TD-304: Use range queries instead of LIKE for index usage
        start, end = _date_range(date_or_month)
        cursor = await self._db.execute(
            """
            SELECT COALESCE(SUM(cost_usd), 0),
                   COALESCE(SUM(input_tokens), 0),
                   COALESCE(SUM(output_tokens), 0),
                   COUNT(*)
            FROM turn_costs WHERE timestamp >= ? AND timestamp < ?
            """,
            (start, end),
        )
        row = await cursor.fetchone()
        return BudgetSummary(
            period=date_or_month,
            total_cost_usd=float(row[0]) if row else 0.0,
            total_input_tokens=int(row[1]) if row else 0,
            total_output_tokens=int(row[2]) if row else 0,
            turn_count=int(row[3]) if row else 0,
        )

    async def get_by_agent(
        self, *, period: str, date_or_month: str | None = None
    ) -> list[dict[str, Any]]:
        # TD-179/TD-304: Use range queries instead of LIKE
        start, end = _date_range(date_or_month or period)
        cursor = await self._db.execute(
            """
            SELECT agent_id,
                   COALESCE(SUM(cost_usd), 0) AS total_cost,
                   COALESCE(SUM(input_tokens), 0) AS total_in,
                   COALESCE(SUM(output_tokens), 0) AS total_out,
                   COUNT(*) AS turns
            FROM turn_costs WHERE timestamp >= ? AND timestamp < ?
            GROUP BY agent_id ORDER BY total_cost DESC
            """,
            (start, end),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_by_provider(
        self, *, period: str, date_or_month: str | None = None
    ) -> list[dict[str, Any]]:
        # TD-179/TD-304: Use range queries instead of LIKE
        start, end = _date_range(date_or_month or period)
        cursor = await self._db.execute(
            """
            SELECT provider_id, model,
                   COALESCE(SUM(cost_usd), 0) AS total_cost,
                   COALESCE(SUM(input_tokens), 0) AS total_in,
                   COALESCE(SUM(output_tokens), 0) AS total_out,
                   COUNT(*) AS turns
            FROM turn_costs WHERE timestamp >= ? AND timestamp < ?
            GROUP BY provider_id, model ORDER BY total_cost DESC
            """,
            (start, end),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def list_turn_costs(
        self,
        *,
        session_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TurnCost]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        cursor = await self._db.execute(
            f"SELECT turn_id, session_id, agent_id, provider_id, model, "
            f"input_tokens, output_tokens, cost_usd, timestamp "
            f"FROM turn_costs {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            params,
        )
        rows = await cursor.fetchall()
        return [TurnCost.model_validate(dict(r)) for r in rows]


# ── Singleton ─────────────────────────────────────────────────────────────────

_tracker: BudgetTracker | None = None


def init_budget_tracker(db: aiosqlite.Connection) -> BudgetTracker:
    global _tracker
    _tracker = BudgetTracker(db)
    return _tracker


def get_budget_tracker() -> BudgetTracker:
    if _tracker is None:
        raise RuntimeError("BudgetTracker not initialised — call init_budget_tracker() first")
    return _tracker
