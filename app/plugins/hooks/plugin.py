"""Base class for pipeline-hook plugins (Sprint 13, D5).

A plugin that wants to inject behavior at pipeline hook points should
subclass :class:`HookPlugin` and override :meth:`get_hook_specs`.

Example::

    from app.plugins.hooks.plugin import HookPlugin
    from app.plugins.hooks.models import HookContext, HookResult, PipelineHookSpec

    class ContentFilterPlugin(HookPlugin):
        plugin_id = "content_filter"
        name = "Content Filter"

        def get_hook_specs(self):
            return [(
                PipelineHookSpec(hook_point="pre_response", priority=10,
                                 plugin_id=self.plugin_id),
                self._filter,
            )]

        async def _filter(self, ctx: HookContext) -> HookResult:
            text = ctx.data.get("text", "")
            censored = text.replace("bad_word", "***")
            return HookResult(modified_data={"text": censored})
"""
from __future__ import annotations

from typing import Any, Callable

from app.plugins.base import PluginBase
from app.plugins.hooks.engine import get_hook_engine
from app.plugins.hooks.models import HookContext, HookPoint, HookResult, PipelineHookSpec


class HookPlugin(PluginBase):
    """Convenience base for pipeline-hook plugins.

    Subclasses must override :meth:`get_hook_specs` to return a list of
    ``(PipelineHookSpec, async callable)`` pairs.  The base activate/deactivate
    handle registration with the global :class:`HookEngine`.
    """

    plugin_type = "pipeline_hook"

    async def configure(self, config: dict[str, Any], auth_store: Any) -> None:
        """Hook plugins typically need no credentials. Override if needed."""

    def get_hook_specs(
        self,
    ) -> list[tuple[PipelineHookSpec, Callable[[HookContext], Any]]]:
        """Return ``[(spec, callable), ...]`` pairs to register.

        Override in subclasses to declare your hooks.
        """
        return []

    async def activate(self) -> None:
        engine = get_hook_engine()
        for spec, fn in self.get_hook_specs():
            engine.register(spec, fn)

    async def deactivate(self) -> None:
        engine = get_hook_engine()
        engine.unregister_plugin(self.plugin_id)

    async def get_tools(self) -> list[Any]:
        # Hook plugins expose no tools directly.
        return []
