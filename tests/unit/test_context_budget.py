"""Sprint 04 — Unit tests for ContextBudget (§4.5)."""
from __future__ import annotations

from app.agent.models import ContextBudget


def test_history_budget_arithmetic():
    budget = ContextBudget()
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
    budget = ContextBudget()
    assert budget.history_budget > 0


def test_custom_context_window():
    budget = ContextBudget(max_context_tokens=8_000, reserved_for_response=512)
    assert budget.history_budget < 8_000
    assert budget.history_budget >= 0


def test_default_max_context_tokens():
    budget = ContextBudget()
    assert budget.max_context_tokens == 200_000


def test_default_reserved_for_response():
    budget = ContextBudget()
    assert budget.reserved_for_response == 4_096


def test_min_recent_messages_default():
    budget = ContextBudget()
    assert budget.min_recent_messages >= 4


def test_compression_threshold_range():
    budget = ContextBudget()
    assert 0 < budget.compression_threshold < 1
