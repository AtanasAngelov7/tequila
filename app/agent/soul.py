"""Sprint 04 — Soul prompt rendering (§4.2).

``render_soul_prompt(soul, **context)`` renders the Jinja2 system-prompt
template stored on a ``SoulConfig`` (or the module-level DEFAULT).

Context variables available inside the template
------------------------------------------------
- ``persona``          — str: soul.persona
- ``instructions``     — str: soul.instructions
- ``datetime``         — str: current ISO-8601 timestamp
- ``user_name``        — str: session owner (empty string if not provided)
- ``skill_index``      — str: skill summary block (empty if not provided)
- ``active_skills``    — str: active skill instruction block (empty if not provided)
- ``memory``           — str: recalled memory block (empty if not provided)
- ``tools``            — str: tool definitions block (empty if not provided)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from jinja2 import Environment, StrictUndefined, TemplateError, Undefined

from app.agent.models import DEFAULT_SYSTEM_PROMPT, SoulConfig

logger = logging.getLogger(__name__)


def _make_env(strict: bool = False) -> Environment:
    """Return a Jinja2 ``Environment``.

    In ``strict=True`` mode (used by tests) missing variables raise
    ``UndefinedError``.  In normal mode missing variables become empty strings.
    """
    return Environment(
        undefined=StrictUndefined if strict else _SilentUndefined,
        keep_trailing_newline=True,
        autoescape=False,  # system prompts are plain text, not HTML
    )


class _SilentUndefined(Undefined):
    """Jinja2 Undefined subclass that renders unknown variables as ``""``."""

    def __str__(self) -> str:  # type: ignore[override]
        return ""

    __iter__ = lambda self: iter([])
    __bool__ = lambda self: False


def render_soul_prompt(
    soul: SoulConfig | None = None,
    *,
    user_name: str = "",
    skill_index: str = "",
    active_skills: str = "",
    memory: str = "",
    tools: str = "",
    strict: bool = False,
    extra: dict[str, Any] | None = None,
) -> str:
    """Render the Jinja2 system-prompt template for *soul*.

    If *soul* is ``None`` or has no custom template, the module-level
    ``DEFAULT_SYSTEM_PROMPT`` is used.  The caller-supplied *extra* dict is
    merged into the template context last (highest priority).

    Parameters
    ----------
    soul:
        The agent's ``SoulConfig`` (may be ``None`` for the default persona).
    user_name:
        Name of the current session user.
    skill_index:
        Formatted skill summary block (produced by prompt assembly step 5).
    active_skills:
        Active skill instruction text (produced by prompt assembly step 5).
    memory:
        Recalled memory text (produced by prompt assembly step 3).
    tools:
        Formatted tool definitions (produced by prompt assembly step 6).
    strict:
        Raise ``ValueError`` on undefined template variables (default: False).
    extra:
        Additional context variables to expose inside the template.

    Returns
    -------
    str
        The rendered system prompt string.
    """
    template_str = DEFAULT_SYSTEM_PROMPT
    if soul and soul.system_prompt_template:
        template_str = soul.system_prompt_template

    persona = soul.persona if soul else "a helpful AI assistant"
    instructions = soul.instructions if soul else []

    context: dict[str, Any] = {
        "persona": persona,
        "instructions": instructions,
        "datetime": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "user_name": user_name,
        "skill_index": skill_index,
        "active_skills": active_skills,
        "memory": memory,
        "tools": tools,
    }
    if extra:
        context.update(extra)

    env = _make_env(strict=strict)
    try:
        tmpl = env.from_string(template_str)
        rendered = tmpl.render(**context)
    except TemplateError as exc:
        logger.error("Failed to render soul prompt: %s", exc)
        if strict:
            raise ValueError(f"Soul prompt render error: {exc}") from exc
        # Graceful degradation — return un-rendered prompt
        return template_str

    # Post-process: strip excessive blank lines (>2 consecutive newlines → 2)
    import re
    rendered = re.sub(r"\n{3,}", "\n\n", rendered)
    return rendered.strip()
