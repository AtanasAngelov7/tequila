"""Tool registry — ToolDefinition model, @tool decorator, and ToolRegistry (§11.1).

Usage
-----
Register a tool via the ``@tool`` decorator::

    from app.tools.registry import tool

    @tool(description="Return the current UTC time.", safety="read_only")
    def get_current_time() -> str:
        return datetime.now(timezone.utc).isoformat()

Access registrations via the singleton::

    registry = get_tool_registry()
    td = registry.get("get_current_time")

Safety levels
-------------
- ``read_only``   — no side effects; always auto-approved
- ``side_effect`` — causes external changes (API call, DB write); approved by default
- ``destructive`` — irreversible action (delete file, drop table); requires confirmation
- ``critical``    — high-risk action (format disk, send email); always requires confirmation
"""
from __future__ import annotations

import inspect
import json
import logging
from typing import Any, Callable, Literal, Union

from pydantic import BaseModel

logger = logging.getLogger(__name__)

SafetyLevel = Literal["read_only", "side_effect", "destructive", "critical"]


# ── ToolDefinition ─────────────────────────────────────────────────────────────


class ToolDefinition(BaseModel):
    """Full metadata for one registered tool (§11.1)."""

    name: str
    """Identifier used by the LLM and the executor — snake_case."""

    description: str
    """Human/LLM readable description of what this tool does."""

    parameters: dict[str, Any]
    """JSON Schema object describing the tool's input parameters."""

    safety: SafetyLevel = "side_effect"
    """Safety classification — used for policy checks and approval gating."""

    def to_provider_tool_def(self) -> dict[str, Any]:
        """Return a provider-agnostic ``ToolDef``-compatible dict."""
        from app.providers.base import ToolDef
        return ToolDef(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
            safety=self.safety,
        ).model_dump()


# ── ToolRegistry ───────────────────────────────────────────────────────────────


class ToolRegistry:
    """In-process registry of all enabled tools.

    Maintains a mapping of ``name → (ToolDefinition, callable)``.
    Thread-safe for reads (append-only after startup).
    """

    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolDefinition, Callable[..., Any]]] = {}
        self._frozen = False  # TD-208: Prevent overwrites after startup

    def freeze(self) -> None:
        """Prevent further overwrites of existing tool registrations."""
        self._frozen = True

    # ── Registration ─────────────────────────────────────────────────────────

    def register(self, td: ToolDefinition, fn: Callable[..., Any]) -> None:
        """Register *td* with its implementation *fn*."""
        if td.name in self._tools:
            if self._frozen:
                logger.warning("Tool %r overwrite blocked (registry frozen)", td.name)
                return
            logger.warning("Tool %r already registered — overwriting", td.name)
        self._tools[td.name] = (td, fn)
        logger.debug("Tool registered: %s (safety=%s)", td.name, td.safety)

    def unregister(self, name: str) -> bool:
        """Remove a tool by name. Returns True if found and removed."""
        if name in self._tools:
            del self._tools[name]
            logger.debug("Tool unregistered: %s", name)
            return True
        return False

    # ── Lookup ────────────────────────────────────────────────────────────────

    def get(self, name: str) -> tuple[ToolDefinition, Callable[..., Any]] | None:
        """Return ``(ToolDefinition, callable)`` or ``None`` if not found."""
        return self._tools.get(name)

    def get_definition(self, name: str) -> ToolDefinition | None:
        """Return only the ``ToolDefinition`` for *name*, or ``None``."""
        entry = self._tools.get(name)
        return entry[0] if entry else None

    def list(self) -> list[ToolDefinition]:
        """All registered tool definitions, sorted by name."""
        return sorted((td for td, _ in self._tools.values()), key=lambda t: t.name)

    def by_safety(self, level: SafetyLevel) -> list[ToolDefinition]:
        """All definitions matching *level* exactly."""
        return [td for td, _ in self._tools.values() if td.safety == level]

    def to_provider_defs(self) -> list[dict[str, Any]]:
        """Return all tools as provider ToolDef dicts for prompt assembly."""
        return [td.to_provider_tool_def() for td in self.list()]

    def names(self) -> set[str]:
        return set(self._tools)

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ToolRegistry tools={list(self._tools)}>"


# ── Singleton ─────────────────────────────────────────────────────────────────

_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Return the process-wide ``ToolRegistry`` singleton."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


# ── @tool decorator ───────────────────────────────────────────────────────────


def _build_json_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """Derive a simple JSON Schema from *fn*'s type annotations.

    Handles primitive types (str, int, float, bool), ``list[str]``,
    ``Optional[T]`` / ``T | None``, and ``dict[str, Any]``.
    Complex types default to ``{"type": "string"}``.
    """
    import types
    sig = inspect.signature(fn)
    hints = fn.__annotations__

    type_map: dict[type, str] = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
    }

    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        annotation = hints.get(name)
        if annotation is None:
            prop = {"type": "string"}
        else:
            origin = getattr(annotation, "__origin__", None)
            args = getattr(annotation, "__args__", ())

            # TD-238: Handle Optional[T] / Union[T, None]
            if origin is types.UnionType or origin is Union:
                non_none = [a for a in args if a is not type(None)]
                if len(non_none) == 1:
                    inner = non_none[0]
                    inner_origin = getattr(inner, "__origin__", None)
                    if inner_origin is list:
                        prop = {"type": "array", "items": {"type": "string"}}
                    elif inner_origin is dict:
                        prop = {"type": "object"}
                    else:
                        prop = {"type": type_map.get(inner, "string")}
                else:
                    prop = {"type": "string"}
            elif origin is list:
                prop = {"type": "array", "items": {"type": "string"}}
            elif origin is dict:
                prop = {"type": "object"}
            else:
                prop = {"type": type_map.get(annotation, "string")}

        properties[name] = prop

        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def tool(
    *,
    description: str = "",
    safety: SafetyLevel = "side_effect",
    parameters: dict[str, Any] | None = None,
    name: str | None = None,
    registry: ToolRegistry | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that registers a function as a tool in the global registry.

    Parameters
    ----------
    description:
        Human/LLM readable description.  Defaults to the function ``__doc__``.
    safety:
        Safety classification for approval-gating.
    parameters:
        Explicit JSON Schema.  If omitted, derived from type annotations.
    name:
        Override the tool name.  Defaults to ``fn.__name__``.
    registry:
        Registry to use.  Defaults to the global singleton.
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        tool_name = name or fn.__name__
        tool_description = description or (fn.__doc__ or "").strip()
        tool_params = parameters if parameters is not None else _build_json_schema(fn)

        td = ToolDefinition(
            name=tool_name,
            description=tool_description,
            parameters=tool_params,
            safety=safety,
        )

        target_registry = registry if registry is not None else get_tool_registry()
        target_registry.register(td, fn)

        # Preserve function identity
        fn._tool_definition = td  # type: ignore[attr-defined]
        return fn

    return decorator
