"""Tests for app/gateway/router.py — event dispatch and handler registration."""
from __future__ import annotations

import pytest

from app.gateway.events import ET, GatewayEvent, EventSource
from app.gateway.router import GatewayRouter, init_router, get_router


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_event(event_type: str = ET.INBOUND_MESSAGE) -> GatewayEvent:
    return GatewayEvent(
        event_type=event_type,
        source=EventSource(kind="user", id="test_user"),
        session_key="user:main",
        payload={"text": "hello"},
    )


# ── Unit tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handler_receives_event() -> None:
    """A registered handler should receive the emitted event."""
    router = GatewayRouter()
    router.start()

    received: list[GatewayEvent] = []

    async def handler(event: GatewayEvent) -> None:
        received.append(event)

    router.on(ET.INBOUND_MESSAGE, handler)
    event = _make_event(ET.INBOUND_MESSAGE)
    await router.emit(event)

    assert len(received) == 1
    assert received[0].event_id == event.event_id


@pytest.mark.asyncio
async def test_wildcard_handler_receives_all_events() -> None:
    """A handler registered with '*' should receive every event type."""
    router = GatewayRouter()
    router.start()

    received: list[str] = []

    async def wildcard_handler(event: GatewayEvent) -> None:
        received.append(event.event_type)

    router.on("*", wildcard_handler)

    for et in [ET.INBOUND_MESSAGE, ET.AGENT_RUN_COMPLETE, ET.SESSION_CREATED]:
        await router.emit(_make_event(et))

    assert received == [ET.INBOUND_MESSAGE, ET.AGENT_RUN_COMPLETE, ET.SESSION_CREATED]


@pytest.mark.asyncio
async def test_handler_not_called_after_off() -> None:
    """Deregistered handler should not be called."""
    router = GatewayRouter()
    router.start()

    received: list[GatewayEvent] = []

    async def handler(event: GatewayEvent) -> None:
        received.append(event)

    router.on(ET.INBOUND_MESSAGE, handler)
    router.off(ET.INBOUND_MESSAGE, handler)
    await router.emit(_make_event(ET.INBOUND_MESSAGE))

    assert received == []


@pytest.mark.asyncio
async def test_duplicate_registration_is_noop() -> None:
    """Registering the same handler twice should not cause it to be called twice."""
    router = GatewayRouter()
    router.start()

    call_count = 0

    async def handler(event: GatewayEvent) -> None:
        nonlocal call_count
        call_count += 1

    router.on(ET.INBOUND_MESSAGE, handler)
    router.on(ET.INBOUND_MESSAGE, handler)  # duplicate
    await router.emit(_make_event(ET.INBOUND_MESSAGE))

    assert call_count == 1


@pytest.mark.asyncio
async def test_emit_returns_monotonic_sequence() -> None:
    """emit() should return incrementing sequence numbers."""
    router = GatewayRouter()
    router.start()

    seq1 = await router.emit(_make_event())
    seq2 = await router.emit(_make_event())
    seq3 = await router.emit(_make_event())

    assert seq1 < seq2 < seq3


@pytest.mark.asyncio
async def test_emit_on_stopped_router_returns_zero() -> None:
    """Emitting on a stopped router should return 0 (event dropped)."""
    router = GatewayRouter()
    router.start()
    router.stop()

    seq = await router.emit(_make_event())
    assert seq == 0


@pytest.mark.asyncio
async def test_handler_exception_does_not_abort_dispatch() -> None:
    """An exception in one handler should not prevent other handlers from running."""
    router = GatewayRouter()
    router.start()

    order: list[str] = []

    async def bad_handler(event: GatewayEvent) -> None:
        order.append("bad")
        raise ValueError("intentional error")

    async def good_handler(event: GatewayEvent) -> None:
        order.append("good")

    router.on(ET.INBOUND_MESSAGE, bad_handler)
    router.on(ET.INBOUND_MESSAGE, good_handler)
    await router.emit(_make_event())

    assert order == ["bad", "good"]


def test_get_router_raises_before_init() -> None:
    """get_router() should raise RuntimeError if called before init_router()."""
    import app.gateway.router as router_module

    original = router_module._router
    router_module._router = None
    try:
        with pytest.raises(RuntimeError, match="not initialised"):
            get_router()
    finally:
        router_module._router = original


def test_init_router_creates_singleton() -> None:
    """init_router() should create a running singleton accessible via get_router()."""
    import app.gateway.router as router_module

    original = router_module._router
    try:
        r = init_router()
        assert r._running is True
        assert get_router() is r
    finally:
        r.stop()
        router_module._router = original
