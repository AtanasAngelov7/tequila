"""Sprint 04 — Unit tests for ContextBudgetConfig (config model) and ContextBudget (runtime engine) (§4.5)."""
from __future__ import annotations

from app.agent.models import ContextBudgetConfig


def test_history_budget_arithmetic():
    budget = ContextBudgetConfig()
    expected = (
        budget.max_context_tokens
        - budget.reserved_for_response
        - budget.system_prompt_budget
        - budget.memory_always_recall_budget
        - budget.memory_recall_budget
        - budget.knowledge_source_budget
        - budget.skill_index_budget
        - budget.skill_instruction_budget
        - budget.tool_schema_budget
        - budget.file_context_budget
    )
    assert budget.history_budget == expected


def test_history_budget_positive():
    budget = ContextBudgetConfig()
    assert budget.history_budget > 0


def test_custom_context_window():
    budget = ContextBudgetConfig(max_context_tokens=8_000, reserved_for_response=512)
    assert budget.history_budget < 8_000
    assert budget.history_budget >= 0


def test_default_max_context_tokens():
    budget = ContextBudgetConfig()
    assert budget.max_context_tokens == 200_000


def test_default_reserved_for_response():
    budget = ContextBudgetConfig()
    assert budget.reserved_for_response == 4_096


def test_min_recent_messages_default():
    budget = ContextBudgetConfig()
    assert budget.min_recent_messages >= 4


def test_compression_threshold_range():
    budget = ContextBudgetConfig()
    assert 0 < budget.compression_threshold < 1


# ── Sprint 07: app.agent.context.ContextBudget ───────────────────────────────

import pytest
from unittest.mock import MagicMock

from app.agent.context import (
    ContextBudget as CB07,
    TokenCounter,
    get_or_create_budget,
    evict_budget,
)
from app.providers.base import Message


def _msg(role: str, content: str) -> Message:
    return Message(role=role, content=content)


# ── TokenCounter ──────────────────────────────────────────────────────────────


def test_token_counter_empty_string():
    tc = TokenCounter("gpt-4o")
    assert tc.count("") == 0


def test_token_counter_non_empty():
    tc = TokenCounter("gpt-4o")
    n = tc.count("hello world")
    assert n > 0


def test_token_counter_cache_hit():
    tc = TokenCounter("gpt-4o")
    first = tc.count("cached text")
    tc._enc = None  # remove encoder — must still return cached value
    second = tc.count("cached text")
    assert first == second


def test_token_counter_fallback_without_tiktoken(monkeypatch):
    """When tiktoken is unavailable, fall back to 4-char approximation."""
    tc = TokenCounter("unknown-model")
    tc._enc = None  # force fallback
    n = tc.count("abcdefgh")  # 8 chars → 2 tokens
    assert n == 2


def test_token_counter_count_messages():
    tc = TokenCounter("gpt-4o")
    msgs = [_msg("user", "hello"), _msg("assistant", "hi")]
    total = tc.count_messages(msgs)
    assert total > 0


def test_token_counter_clear_cache():
    tc = TokenCounter("gpt-4o")
    tc.count("hello")
    assert len(tc._cache) == 1
    tc.clear_cache()
    assert len(tc._cache) == 0


# ── ContextBudget.for_model ────────────────────────────────────────────────────


def test_for_model_known():
    cb = CB07.for_model("anthropic:claude-sonnet-4-5")
    assert cb.context_window == 200_000
    assert cb.total_budget == 200_000 - 4_096


def test_for_model_unknown_uses_default():
    cb = CB07.for_model("unknown-model")
    assert cb.context_window == 128_000  # _DEFAULT_CONTEXT_WINDOW


# ── usage_ratio / needs_compression ──────────────────────────────────────────


def test_usage_ratio_zero_budget():
    cb = CB07(model_id="", context_window=4_096, reserved_output=4_096)
    # total_budget == 0 → ratio capped at 1.0
    assert cb.usage_ratio([]) == 1.0


def test_needs_compression_below_threshold():
    cb = CB07.for_model("gpt-4o")  # large context window
    messages = [_msg("user", "hi")]
    assert cb.needs_compression(messages, threshold=0.80) is False


def test_needs_compression_above_threshold():
    # Use a tiny context window + natural-language content to force > 80 % usage
    cb = CB07(model_id="", context_window=30, reserved_output=0)
    content = "The quick brown fox jumps over the lazy dog. " * 10
    messages = [_msg("user", content)]
    assert cb.needs_compression(messages, threshold=0.80) is True


# ── compress_drop_tool_results ────────────────────────────────────────────────


def test_compress_drop_tool_results_long():
    cb = CB07.for_model("gpt-4o")
    long_content = "x" * 600
    msgs = [_msg("tool", long_content)]
    result = cb.compress_drop_tool_results(msgs)
    assert len(result) == 1
    assert "[tool result truncated" in result[0].content


def test_compress_drop_tool_results_short():
    cb = CB07.for_model("gpt-4o")
    msgs = [_msg("tool", "short")]
    result = cb.compress_drop_tool_results(msgs)
    assert result[0].content == "short"


def test_compress_drop_tool_results_preserves_non_tool():
    cb = CB07.for_model("gpt-4o")
    msgs = [_msg("user", "x" * 600), _msg("tool", "x" * 600)]
    result = cb.compress_drop_tool_results(msgs)
    assert result[0].content == "x" * 600  # user not truncated
    assert "[tool result truncated" in result[1].content


# ── compress_trim_oldest ──────────────────────────────────────────────────────


def test_compress_trim_oldest_preserves_system():
    cb = CB07(model_id="", context_window=200, reserved_output=0)
    sys_msg = _msg("system", "you are helpful")
    old_msg = _msg("user", "I have a question")
    recent_u = _msg("user", "latest")
    recent_a = _msg("assistant", "reply")
    msgs = [sys_msg, old_msg, recent_u, recent_a]

    result = cb.compress_trim_oldest(msgs, target_ratio=0.001)  # force max trim
    roles = [m.role for m in result]
    assert "system" in roles
    assert result[-2].role == "user"
    assert result[-1].role == "assistant"


def test_compress_trim_oldest_returns_new_list():
    cb = CB07.for_model("gpt-4o")
    msgs = [_msg("user", "hello")]
    result = cb.compress_trim_oldest(msgs)
    assert result is not msgs


# ── compress_summarize_old ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compress_summarize_old_not_enough_history():
    cb = CB07.for_model("gpt-4o")
    msgs = [_msg("user", "only one"), _msg("assistant", "response")]
    # keep_recent=10 means nothing to summarise → same list returned
    result = await cb.compress_summarize_old(msgs, provider=None, model="gpt-4o", keep_recent=10)
    assert result == msgs


@pytest.mark.asyncio
async def test_compress_summarize_old_uses_provider():
    cb = CB07.for_model("gpt-4o")

    async def _fake_stream_completion(*_, **__):
        from app.providers.base import ProviderStreamEvent
        yield ProviderStreamEvent(kind="text_delta", text="This is the summary")
        yield ProviderStreamEvent(kind="done")

    provider = MagicMock()
    provider.stream_completion = _fake_stream_completion

    msgs = [_msg("user", f"message {i}") for i in range(15)]
    result = await cb.compress_summarize_old(msgs, provider=provider, model="gpt-4o", keep_recent=5)
    # Should have system=0 + 1 summary + 5 recent = 6 messages
    assert len(result) == 6
    assert "summary" in result[0].content.lower()


@pytest.mark.asyncio
async def test_compress_summarize_old_fallback_on_empty_summary():
    cb = CB07(model_id="", context_window=50_000, reserved_output=4_096)

    async def _empty_stream(*_, **__):
        from app.providers.base import ProviderStreamEvent
        yield ProviderStreamEvent(kind="done")

    provider = MagicMock()
    provider.stream_completion = _empty_stream

    msgs = [_msg("user", f"message {i}") for i in range(15)]
    result = await cb.compress_summarize_old(msgs, provider=provider, model="m", keep_recent=5)
    # fallback → trim_oldest path, returns a list
    assert isinstance(result, list)


# ── auto_compress ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_compress_no_op_when_below_threshold():
    cb = CB07.for_model("gpt-4o")
    msgs = [_msg("user", "hi")]
    result = await cb.auto_compress(msgs)
    assert result is msgs  # exact same object — nothing was done


@pytest.mark.asyncio
async def test_auto_compress_strategy1_sufficient():
    """If dropping tool results brings usage below threshold, stop there."""
    # Use a tiny context window + long real-word content to guarantee >80 % usage
    cb = CB07(model_id="", context_window=30, reserved_output=0)
    # Use natural-language content that tokenizes to many tokens
    long_content = "The quick brown fox jumps over the lazy dog. " * 20  # ~180 tokens
    long_tool = _msg("tool", long_content)
    user = _msg("user", "hi")
    msgs = [long_tool, user]

    # Pre-condition: compression must be needed
    assert cb.needs_compression(msgs, threshold=0.80), (
        f"pre-condition failed: usage_ratio={cb.usage_ratio(msgs):.2f}"
    )

    result = await cb.auto_compress(msgs, threshold=0.80)
    # tool result was truncated (strategy 1 fired)
    assert any("[tool result truncated" in m.content for m in result)


# ── Session-level budget cache ────────────────────────────────────────────────


def test_get_or_create_budget_same_model():
    evict_budget("test-session-cb")
    b1 = get_or_create_budget("test-session-cb", "gpt-4o")
    b2 = get_or_create_budget("test-session-cb", "gpt-4o")
    assert b1 is b2


def test_get_or_create_budget_new_on_model_change():
    evict_budget("test-session-cb2")
    b1 = get_or_create_budget("test-session-cb2", "gpt-4o")
    b2 = get_or_create_budget("test-session-cb2", "gpt-4o-mini")
    assert b1 is not b2


def test_evict_budget():
    evict_budget("test-session-evict")
    b1 = get_or_create_budget("test-session-evict", "gpt-4o")
    evict_budget("test-session-evict")
    b2 = get_or_create_budget("test-session-evict", "gpt-4o")
    assert b1 is not b2


