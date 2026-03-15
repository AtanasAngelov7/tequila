"""Sprint 07 — Unit tests for GracefulDegradation and circuit registry (§19.3)."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from app.providers.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    GracefulDegradation,
    get_all_circuit_breakers,
    get_circuit_breaker,
    reset_circuit_registry,
)
from app.providers.base import ProviderStreamEvent


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_provider(provider_id: str, stream_result=None, raises: Exception | None = None):
    """Build a mock LLMProvider whose stream_completion matches the real API.

    ``stream_completion`` is a regular ``async def`` that returns an
    ``AsyncIterator[ProviderStreamEvent]`` — it is NOT itself an async
    generator.
    """
    provider = MagicMock()
    provider.provider_id = provider_id

    if raises is not None:
        async def _impl(*args, **kwargs):
            raise raises
        provider.stream_completion = _impl
    else:
        events = list(stream_result or [ProviderStreamEvent(kind="done")])

        async def _impl(*args, **kwargs):
            async def _gen():
                for item in events:
                    yield item
            return _gen()

        provider.stream_completion = _impl

    return provider


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset the circuit-breaker registry before each test."""
    reset_circuit_registry()
    yield
    reset_circuit_registry()


# ── Circuit-breaker registry ──────────────────────────────────────────────────


def test_get_circuit_breaker_creates_instance():
    cb = get_circuit_breaker("prov-a")
    assert isinstance(cb, CircuitBreaker)
    assert cb.provider_id == "prov-a"


def test_get_circuit_breaker_returns_same_instance():
    cb1 = get_circuit_breaker("prov-b")
    cb2 = get_circuit_breaker("prov-b")
    assert cb1 is cb2


def test_get_all_circuit_breakers_returns_copy():
    get_circuit_breaker("prov-c")
    all_cbs = get_all_circuit_breakers()
    assert "prov-c" in all_cbs
    # Modifying the returned dict doesn't affect the registry
    all_cbs.clear()
    assert "prov-c" in get_all_circuit_breakers()


def test_reset_circuit_registry_clears():
    get_circuit_breaker("prov-d")
    reset_circuit_registry()
    assert "prov-d" not in get_all_circuit_breakers()


def test_get_circuit_breaker_default_params():
    cb = get_circuit_breaker("prov-defaults")
    assert cb.failure_threshold == 5
    assert cb.success_threshold == 2
    assert cb.reset_timeout == 30.0


# ── GracefulDegradation: construction ─────────────────────────────────────────


def test_graceful_degradation_empty_chain_raises():
    with pytest.raises(ValueError, match="chain must have at least one entry"):
        GracefulDegradation(chain=[])


# ── GracefulDegradation: first provider succeeds ──────────────────────────────


@pytest.mark.asyncio
async def test_graceful_degradation_first_succeeds():
    events = [ProviderStreamEvent(kind="text_delta", text="hello"), ProviderStreamEvent(kind="done")]
    p1 = _make_provider("provider-1", stream_result=events)

    gd = GracefulDegradation(chain=[(p1, "model-a")])
    stream = await gd.stream_completion(messages=[])

    collected = []
    async for e in stream:
        collected.append(e)

    assert any(e.kind == "text_delta" for e in collected)


# ── GracefulDegradation: first fails, second succeeds ────────────────────────


@pytest.mark.asyncio
async def test_graceful_degradation_fallback_to_second():
    p1 = _make_provider("fail-prov", raises=RuntimeError("timeout"))
    events = [ProviderStreamEvent(kind="text_delta", text="fallback"), ProviderStreamEvent(kind="done")]
    p2 = _make_provider("ok-prov", stream_result=events)

    gd = GracefulDegradation(chain=[(p1, "m1"), (p2, "m2")])
    stream = await gd.stream_completion(messages=[])

    collected = []
    async for e in stream:
        collected.append(e)
    assert any(e.kind == "text_delta" for e in collected)


# ── GracefulDegradation: all fail → RuntimeError ─────────────────────────────


@pytest.mark.asyncio
async def test_graceful_degradation_all_fail_raises():
    p1 = _make_provider("fail1", raises=ConnectionError("no conn"))
    p2 = _make_provider("fail2", raises=ConnectionError("no conn 2"))

    gd = GracefulDegradation(chain=[(p1, "m1"), (p2, "m2")])
    with pytest.raises(RuntimeError, match="All providers"):
        await gd.stream_completion(messages=[])


# ── GracefulDegradation: skips OPEN circuits ──────────────────────────────────


@pytest.mark.asyncio
async def test_graceful_degradation_skips_open_circuit():
    """Provider with OPEN circuit is skipped; next is used."""
    p1 = _make_provider("open-prov")
    # Manually open the circuit
    cb = get_circuit_breaker("open-prov", failure_threshold=1, reset_timeout=60.0)
    await cb.record_failure()
    assert cb.state == CircuitState.OPEN

    events = [ProviderStreamEvent(kind="text_delta", text="from second"), ProviderStreamEvent(kind="done")]
    p2 = _make_provider("fallback-prov", stream_result=events)

    gd = GracefulDegradation(chain=[(p1, "m1"), (p2, "m2")])
    stream = await gd.stream_completion(messages=[])

    collected = []
    async for e in stream:
        collected.append(e)
    assert any(e.kind == "text_delta" and e.text == "from second" for e in collected)
    # If p1 had been called, it would have returned the default event (no text) — 
    # the text "from second" proves p2 was used.


# ── GracefulDegradation: circuit closes on success ────────────────────────────


@pytest.mark.asyncio
async def test_graceful_degradation_records_success():
    events = [ProviderStreamEvent(kind="done")]
    p1 = _make_provider("success-cb-prov", stream_result=events)

    gd = GracefulDegradation(chain=[(p1, "m1")])
    await gd.stream_completion(messages=[])

    cb = get_circuit_breaker("success-cb-prov")
    assert cb._failure_count == 0
    assert cb.state == CircuitState.CLOSED


# ── GracefulDegradation: records failure ─────────────────────────────────────


@pytest.mark.asyncio
async def test_graceful_degradation_records_failure():
    p1 = _make_provider("record-fail-prov", raises=ValueError("boom"))

    gd = GracefulDegradation(chain=[(p1, "m1")])
    with pytest.raises(RuntimeError):
        await gd.stream_completion(messages=[])

    cb = get_circuit_breaker("record-fail-prov")
    assert cb._failure_count >= 1
