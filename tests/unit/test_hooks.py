"""Unit tests for Sprint 13 D5 — PipelineHookEngine."""
from __future__ import annotations

import pytest

from app.plugins.hooks.engine import HookEngine
from app.plugins.hooks.models import HookContext, HookPoint, HookResult, PipelineHookSpec


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_spec(
    point: HookPoint = "pre_prompt_assembly",
    priority: int = 50,
    plugin_id: str = "test",
) -> PipelineHookSpec:
    return PipelineHookSpec(
        hook_point=point,
        priority=priority,
        plugin_id=plugin_id,
        description="test hook",
    )


def make_ctx(point: HookPoint = "pre_prompt_assembly") -> HookContext:
    return HookContext(
        hook_point=point,
        session_id="s1",
        data={"text": "hello"},
    )


# ── Registration ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_and_list():
    engine = HookEngine()

    async def hook(ctx: HookContext) -> HookResult:
        return HookResult()

    spec = make_spec()
    engine.register(spec, hook)
    assert len(engine.list_hooks("pre_prompt_assembly")) == 1


@pytest.mark.asyncio
async def test_unregister_by_plugin_id():
    engine = HookEngine()

    async def hook(ctx: HookContext) -> HookResult:
        return HookResult()

    spec = make_spec(plugin_id="plugin_a")
    engine.register(spec, hook)
    engine.unregister_plugin("plugin_a")
    assert len(engine.list_hooks("pre_prompt_assembly")) == 0


# ── Priority ordering ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hooks_run_in_priority_order():
    engine = HookEngine()
    order: list[int] = []

    async def h1(ctx: HookContext) -> HookResult:
        order.append(1)
        return HookResult()

    async def h10(ctx: HookContext) -> HookResult:
        order.append(10)
        return HookResult()

    async def h5(ctx: HookContext) -> HookResult:
        order.append(5)
        return HookResult()

    engine.register(make_spec(priority=10, plugin_id="p10"), h10)
    engine.register(make_spec(priority=1, plugin_id="p1"), h1)
    engine.register(make_spec(priority=5, plugin_id="p5"), h5)

    ctx = make_ctx()
    await engine.run(ctx)
    assert order == [1, 5, 10]


# ── Data modification ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hook_can_modify_data():
    engine = HookEngine()

    async def uppercase(ctx: HookContext) -> HookResult:
        result = HookResult()
        result.modified_data = {"text": ctx.data.get("text", "").upper()}
        return result

    engine.register(make_spec(), uppercase)
    ctx = make_ctx()
    final = await engine.run(ctx)
    assert final.data.get("text") == "HELLO"


# ── Abort ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_abort_stops_chain():
    engine = HookEngine()
    second_ran = []

    async def aborter(ctx: HookContext) -> HookResult:
        r = HookResult()
        r.abort = True
        return r

    async def should_not_run(ctx: HookContext) -> HookResult:
        second_ran.append(True)
        return HookResult()

    engine.register(make_spec(priority=1, plugin_id="first"), aborter)
    engine.register(make_spec(priority=2, plugin_id="second"), should_not_run)

    ctx = make_ctx()
    await engine.run(ctx)
    assert second_ran == []


# ── Sync hooks ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_hook_is_supported():
    engine = HookEngine()
    ran = []

    def sync_hook(ctx: HookContext) -> HookResult:
        ran.append(True)
        return HookResult()

    engine.register(make_spec(), sync_hook)
    ctx = make_ctx()
    await engine.run(ctx)
    assert ran == [True]


# ── Multiple points ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hooks_scoped_to_point():
    """Hooks on 'post_prompt' must not fire when running 'pre_prompt'."""
    engine = HookEngine()
    fired = []

    async def post_hook(ctx: HookContext) -> HookResult:
        fired.append("post")
        return HookResult()

    engine.register(make_spec(point="post_prompt_assembly", plugin_id="pp"), post_hook)
    ctx = make_ctx(point="pre_prompt_assembly")
    await engine.run(ctx)
    assert fired == []
