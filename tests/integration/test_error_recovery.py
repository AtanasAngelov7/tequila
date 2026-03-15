"""Sprint 07 — Integration tests for error recovery mechanisms.

Covers:
* CircuitBreaker state transitions in realistic provider-failure scenarios
* Context auto-compression threshold in the turn loop
* GracefulDegradation fallback behaviour
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.providers.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    get_circuit_breaker,
)
from tests.reset_helpers import reset_circuit_registry


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_registry():
    reset_circuit_registry()
    yield
    reset_circuit_registry()


# ── CircuitBreaker state transitions ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_circuit_opens_after_threshold() -> None:
    """CircuitBreaker transitions CLOSED → OPEN after failure_threshold failures."""
    cb = get_circuit_breaker("prov-open", failure_threshold=3)
    for _ in range(3):
        await cb.record_failure()
    assert cb.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_circuit_stays_closed_below_threshold() -> None:
    cb = get_circuit_breaker("prov-below", failure_threshold=5)
    for _ in range(4):
        await cb.record_failure()
    assert cb.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_circuit_open_then_half_open_after_reset() -> None:
    """After reset_timeout elapses, circuit transitions OPEN → HALF_OPEN."""
    cb = CircuitBreaker(
        provider_id="prov-half",
        failure_threshold=1,
        reset_timeout=0.05,
    )
    await cb.record_failure()
    assert cb.state == CircuitState.OPEN

    await asyncio.sleep(0.08)
    await cb._maybe_transition_open_to_half_open()
    assert cb.state == CircuitState.HALF_OPEN


@pytest.mark.asyncio
async def test_circuit_half_open_to_closed_on_success() -> None:
    cb = CircuitBreaker(
        provider_id="prov-recover",
        failure_threshold=1,
        success_threshold=2,
        reset_timeout=0.05,
    )
    await cb.record_failure()
    await asyncio.sleep(0.08)
    await cb._maybe_transition_open_to_half_open()
    assert cb.state == CircuitState.HALF_OPEN

    await cb.record_success()
    await cb.record_success()
    assert cb.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_circuit_open_error_raised_via_call() -> None:
    """cb.call() raises CircuitOpenError when circuit is OPEN."""
    cb = CircuitBreaker(provider_id="prov-err", failure_threshold=1)
    await cb.record_failure()
    assert cb.state == CircuitState.OPEN

    async def _dummy():
        yield "x"

    with pytest.raises(CircuitOpenError):
        await cb.call(_dummy)


@pytest.mark.asyncio
async def test_is_available_open_circuit() -> None:
    cb = get_circuit_breaker("prov-available", failure_threshold=2)
    await cb.record_failure()
    await cb.record_failure()
    assert cb.is_available() is False


@pytest.mark.asyncio
async def test_is_available_closed_circuit() -> None:
    cb = get_circuit_breaker("prov-avail-closed")
    assert cb.is_available() is True


# ── Context Budget auto-compression in the turn loop ─────────────────────────


@pytest.mark.asyncio
async def test_auto_compress_fires_at_threshold(migrated_db: Any) -> None:
    """When context usage > 80 %, auto_compress is called and reduces the list."""
    from app.agent.context import ContextBudget, evict_budget

    # Use a tiny budget so a modest message list exceeds 80 %
    evict_budget("test-compress-session")
    cb = ContextBudget(model_id="", context_window=60, reserved_output=0)

    # Build a list that exceeds 80 %
    from app.providers.base import Message
    long_msgs = []
    for i in range(5):
        long_msgs.append(Message(role="user", content=f"message number {i} is here"))
        long_msgs.append(Message(role="assistant", content=f"reply number {i}"))

    # auto_compress should trim them down
    trimmed = await cb.auto_compress(long_msgs, threshold=0.80)
    assert len(trimmed) < len(long_msgs)
    assert cb.usage_ratio(trimmed) <= 0.80 or len(trimmed) >= 2


@pytest.mark.asyncio
async def test_context_budget_drop_tool_results_reduces_usage(migrated_db: Any) -> None:
    """compress_drop_tool_results lowers token count for large tool outputs."""
    from app.agent.context import ContextBudget
    from app.providers.base import Message

    cb = ContextBudget.for_model("gpt-4o")
    msgs_before = [
        Message(role="user", content="run tool"),
        Message(role="tool", content="x" * 2000),
    ]
    msgs_after = cb.compress_drop_tool_results(msgs_before)
    assert cb.count_messages(msgs_after) < cb.count_messages(msgs_before)


# ── GracefulDegradation fallback ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_graceful_degradation_fallback_flow() -> None:
    """First provider fails → second succeeds → result returned."""
    from app.providers.circuit_breaker import GracefulDegradation
    from app.providers.base import ProviderStreamEvent as StreamEvent

    fail_prov = MagicMock()
    fail_prov.provider_id = "failing"

    async def _fail(*_, **__):
        raise RuntimeError("provider down")

    fail_prov.stream_completion = _fail

    ok_prov = MagicMock()
    ok_prov.provider_id = "ok"

    async def _ok_stream(*_, **__):
        async def _gen():
            yield StreamEvent(kind="text_delta", text="recovered")
            yield StreamEvent(kind="done")
        return _gen()

    ok_prov.stream_completion = _ok_stream

    gd = GracefulDegradation(chain=[(fail_prov, "m1"), (ok_prov, "m2")])
    stream = await gd.stream_completion(messages=[])
    events = []
    async for e in stream:
        events.append(e)

    assert any(e.kind == "text_delta" and e.text == "recovered" for e in events)


@pytest.mark.asyncio
async def test_graceful_degradation_circuit_open_skips_provider() -> None:
    """A provider whose circuit is OPEN is skipped entirely."""
    from app.providers.circuit_breaker import GracefulDegradation
    from app.providers.base import ProviderStreamEvent as StreamEvent

    skip_prov = MagicMock()
    skip_prov.provider_id = "skip-me"

    async def _should_not_call(*_, **__):
        raise AssertionError("should not call")

    skip_prov.stream_completion = _should_not_call

    # Force OPEN
    cb = get_circuit_breaker("skip-me", failure_threshold=1)
    await cb.record_failure()
    assert cb.state == CircuitState.OPEN

    ok_prov = MagicMock()
    ok_prov.provider_id = "always-ok"

    async def _ok(*_, **__):
        async def _gen():
            yield StreamEvent(kind="done")
        return _gen()

    ok_prov.stream_completion = _ok

    gd = GracefulDegradation(chain=[(skip_prov, "m1"), (ok_prov, "m2")])
    stream = await gd.stream_completion(messages=[])
    async for _ in stream:
        pass
    # If skip_prov had been called, it would have raised AssertionError
