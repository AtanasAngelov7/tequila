"""Hook engine — runs pipeline hooks in priority order (Sprint 13, D5).

Usage::

    engine = get_hook_engine()
    engine.register(spec, my_hook_fn)
    ctx = HookContext(hook_point="pre_prompt", session_id="...", data={...})
    ctx = await engine.run(ctx)
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from app.plugins.hooks.models import HookContext, HookPoint, HookResult, PipelineHookSpec

logger = logging.getLogger(__name__)

# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: HookEngine | None = None


def get_hook_engine() -> HookEngine:
    """Return (creating if necessary) the process-wide :class:`HookEngine`."""
    global _engine  # noqa: PLW0603
    if _engine is None:
        _engine = HookEngine()
    return _engine


# ── HookEngine ────────────────────────────────────────────────────────────────


class HookEngine:
    """Registry and executor for pipeline hooks.

    All hooks for a given point are executed in ascending ``priority`` order.
    If any hook sets ``abort=True`` the remaining hooks for that point are
    skipped and ``ctx.data`` retains the last modified state.
    """

    def __init__(self) -> None:
        # hook_point → sorted list of (spec, callable)
        self._hooks: dict[HookPoint, list[tuple[PipelineHookSpec, Callable[..., Any]]]] = {}

    # ── Registration ─────────────────────────────────────────────────────────

    def register(
        self,
        spec: PipelineHookSpec,
        fn: Callable[[HookContext], Any],
    ) -> None:
        """Register *fn* to run at ``spec.hook_point`` with given priority."""
        point = spec.hook_point
        if point not in self._hooks:
            self._hooks[point] = []
        self._hooks[point].append((spec, fn))
        # Keep sorted by priority (ascending)
        self._hooks[point].sort(key=lambda item: item[0].priority)
        logger.debug(
            "Hook registered: %s → priority=%d plugin=%r",
            point, spec.priority, spec.plugin_id,
        )

    def unregister_plugin(self, plugin_id: str) -> int:
        """Remove all hooks registered by *plugin_id*. Returns count removed."""
        removed = 0
        for point in list(self._hooks.keys()):
            before = len(self._hooks[point])
            self._hooks[point] = [
                (s, f) for s, f in self._hooks[point]
                if s.plugin_id != plugin_id
            ]
            removed += before - len(self._hooks[point])
        return removed

    def list_hooks(self, point: HookPoint | None = None) -> list[dict[str, Any]]:
        """Return metadata about registered hooks, optionally filtered by point."""
        results: list[dict[str, Any]] = []
        for hp, entries in self._hooks.items():
            if point and hp != point:
                continue
            for spec, _ in entries:
                results.append({
                    "hook_point": hp,
                    "priority": spec.priority,
                    "plugin_id": spec.plugin_id,
                    "description": spec.description,
                })
        return results

    # ── Execution ─────────────────────────────────────────────────────────────

    async def run(self, ctx: HookContext) -> HookContext:
        """Run all hooks registered for ``ctx.hook_point`` in priority order.

        Returns the (possibly modified) :class:`HookContext`.
        """
        entries = self._hooks.get(ctx.hook_point, [])
        if not entries:
            return ctx

        for spec, fn in entries:
            try:
                result: HookResult | None = await _invoke(fn, ctx)
                if result is None:
                    continue
                if result.log_message:
                    logger.info(
                        "Hook %s/%s: %s",
                        ctx.hook_point,
                        spec.plugin_id,
                        result.log_message,
                    )
                if result.modified_data is not None:
                    ctx = ctx.model_copy(update={"data": result.modified_data})
                if result.abort:
                    logger.debug(
                        "Hook aborted pipeline at %s (plugin=%r).",
                        ctx.hook_point,
                        spec.plugin_id,
                    )
                    break
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Hook error at %s (plugin=%r): %s",
                    ctx.hook_point,
                    spec.plugin_id,
                    exc,
                )
                # Non-fatal — continue with remaining hooks
        return ctx


async def _invoke(fn: Callable[..., Any], ctx: HookContext) -> HookResult | None:
    """Call *fn* with *ctx*; handle both sync and async callables."""
    import asyncio
    import inspect

    if inspect.iscoroutinefunction(fn):
        result = await fn(ctx)
    else:
        result = await asyncio.to_thread(fn, ctx)

    if result is None:
        return None
    if isinstance(result, HookResult):
        return result
    # If hook returns a plain dict, coerce to HookResult
    if isinstance(result, dict):
        return HookResult(**result)
    return None
