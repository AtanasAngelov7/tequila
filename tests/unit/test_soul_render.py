"""Sprint 04 — Unit tests for soul.render_soul_prompt (§4.2)."""
from __future__ import annotations

import pytest

from app.agent.models import SoulConfig
from app.agent.soul import render_soul_prompt


def test_render_with_default_template():
    soul = SoulConfig(persona="a friendly bot", instructions=["always be kind"])
    result = render_soul_prompt(soul, user_name="Alice")
    assert "a friendly bot" in result
    assert "always be kind" in result
    assert "Alice" in result


def test_render_with_custom_template():
    soul = SoulConfig(
        persona="test persona",
        instructions=[],
        system_prompt_template="Hello {{ user_name }}! You are {{ persona }}.",
    )
    result = render_soul_prompt(soul, user_name="Bob")
    assert result == "Hello Bob! You are test persona."


def test_render_without_soul_uses_defaults():
    result = render_soul_prompt(None)
    assert "helpful" in result.lower()


def test_render_includes_tools_block():
    soul = SoulConfig(persona="p", instructions=[])
    result = render_soul_prompt(soul, tools="Tool: fs_read_file")
    assert "fs_read_file" in result


def test_render_includes_datetime():
    soul = SoulConfig(persona="p", instructions=[])
    result = render_soul_prompt(soul)
    # Should contain a year like 2024 or 2025
    import re
    assert re.search(r"20\d{2}", result)


def test_render_strips_excess_blank_lines():
    soul = SoulConfig(
        persona="p",
        instructions=[],
        system_prompt_template="A\n\n\n\n\nB",
    )
    result = render_soul_prompt(soul)
    assert "\n\n\n" not in result


def test_render_missing_variable_silent_by_default():
    soul = SoulConfig(
        persona="p",
        instructions=[],
        system_prompt_template="{{ unknown_var }} text",
    )
    result = render_soul_prompt(soul)
    assert "text" in result
    # Unknown variable silently renders as empty string
    assert "unknown_var" not in result


def test_render_missing_variable_strict_raises():
    soul = SoulConfig(
        persona="p",
        instructions=[],
        system_prompt_template="{{ unknown_var }} text",
    )
    with pytest.raises(ValueError, match="render error"):
        render_soul_prompt(soul, strict=True)


def test_render_extra_context():
    soul = SoulConfig(
        persona="p",
        instructions=[],
        system_prompt_template="Custom: {{ my_var }}",
    )
    result = render_soul_prompt(soul, extra={"my_var": "hello world"})
    assert "hello world" in result
