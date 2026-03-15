"""Sprint 04 — Unit tests for CircuitBreaker (§4.6c)."""
from __future__ import annotations

import asyncio

import pytest

from app.providers.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState, RetryPolicy


@pytest.fixture
def cb():
    return CircuitBreaker(
        provider_id="test_provider",
        failure_threshold=3,
        success_threshold=2,
        reset_timeout=0.1,  # short timeout for tests
    )


def test_initial_state_closed(cb: CircuitBreaker):
    assert cb.state == CircuitState.CLOSED


async def test_transitions_to_open_after_failures(cb: CircuitBreaker):
    for _ in range(3):
        await cb.record_failure()
    assert cb.state == CircuitState.OPEN


async def test_stays_closed_below_threshold(cb: CircuitBreaker):
    for _ in range(2):
        await cb.record_failure()
    assert cb.state == CircuitState.CLOSED


async def test_open_to_half_open_after_timeout(cb: CircuitBreaker):
    for _ in range(3):
        await cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # Wait for reset timeout
    await asyncio.sleep(0.15)
    await cb._maybe_transition_open_to_half_open()
    assert cb.state == CircuitState.HALF_OPEN


async def test_half_open_to_closed_after_successes(cb: CircuitBreaker):
    for _ in range(3):
        await cb.record_failure()
    await asyncio.sleep(0.15)
    await cb._maybe_transition_open_to_half_open()
    assert cb.state == CircuitState.HALF_OPEN

    # Need success_threshold=2 successes to close
    await cb.record_success()
    assert cb.state == CircuitState.HALF_OPEN
    await cb.record_success()
    assert cb.state == CircuitState.CLOSED


async def test_half_open_to_open_on_failure(cb: CircuitBreaker):
    for _ in range(3):
        await cb.record_failure()
    await asyncio.sleep(0.15)
    await cb._maybe_transition_open_to_half_open()

    await cb.record_failure()
    assert cb.state == CircuitState.OPEN


async def test_success_resets_failure_count(cb: CircuitBreaker):
    await cb.record_failure()
    await cb.record_failure()
    await cb.record_success()
    assert cb._failure_count == 0
    assert cb.state == CircuitState.CLOSED


async def test_is_available_closed(cb: CircuitBreaker):
    assert cb.is_available() is True


async def test_is_available_open_blocks(cb: CircuitBreaker):
    for _ in range(3):
        await cb.record_failure()
    assert cb.is_available() is False


async def test_circuit_open_error_raised_when_open(cb: CircuitBreaker):
    for _ in range(3):
        await cb.record_failure()

    async def dummy():
        yield "event"

    with pytest.raises(CircuitOpenError):
        await cb.call(dummy)


def test_retry_policy_delay_backoff():
    policy = RetryPolicy(base_delay=1.0, backoff_factor=2.0, max_delay=30.0)
    assert policy.delay_for(0) == 1.0
    assert policy.delay_for(1) == 2.0
    assert policy.delay_for(2) == 4.0
    assert policy.delay_for(10) == 30.0  # capped at max_delay


def test_status_dict(cb: CircuitBreaker):
    status = cb.status_dict()
    assert status["provider_id"] == "test_provider"
    assert status["state"] == "closed"
    assert status["failure_count"] == 0
