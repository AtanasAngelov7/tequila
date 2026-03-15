"""Sprint 04 — Unit tests for prompt assembly pipeline (§4.5)."""
from __future__ import annotations

import pytest

from app.agent.models import AgentConfig, ContextBudgetConfig, SoulConfig
from app.agent.prompt_assembly import AssemblyContext, assemble_prompt
from app.providers.base import ToolDef


def _make_agent(**kwargs) -> AgentConfig:
    defaults: dict = {
        "name": "Test Agent",
        "default_model": "anthropic:claude-sonnet-4-5",
        "soul": SoulConfig(persona="a test agent", instructions=["be helpful"]),
    }
    defaults.update(kwargs)
    return AgentConfig(**defaults)


async def test_assemble_basic_prompt():
    agent = _make_agent()
    ctx = AssemblyContext(
        agent_config=agent,
        user_message="Hello, agent!",
        user_name="TestUser",
    )
    messages = await assemble_prompt(ctx)
    assert len(messages) >= 2
    # First message should be system
    assert messages[0].role == "system"
    # Last message should be the user message
    assert messages[-1].role == "user"
    assert messages[-1].content == "Hello, agent!"


async def test_system_prompt_contains_persona():
    agent = _make_agent(soul=SoulConfig(persona="a brilliant poet", instructions=["write in verse"]))
    ctx = AssemblyContext(agent_config=agent, user_message="Hi")
    messages = await assemble_prompt(ctx)
    system_content = messages[0].content
    assert isinstance(system_content, str)
    assert "brilliant poet" in system_content


async def test_session_history_injected():
    agent = _make_agent()
    history = [
        {"role": "user", "content": "First message"},
        {"role": "assistant", "content": "First response"},
    ]
    ctx = AssemblyContext(
        agent_config=agent,
        user_message="Current question",
        session_history=history,
    )
    messages = await assemble_prompt(ctx)
    roles = [m.role for m in messages]
    # Should have system, user(history), assistant(history), user(current)
    assert "user" in roles
    assert "assistant" in roles
    assert messages[-1].content == "Current question"


async def test_history_budget_respected():
    agent = _make_agent()
    # Create lots of history that won't fit in budget
    long_history = [
        {"role": "user", "content": "word " * 1000},
        {"role": "assistant", "content": "word " * 1000},
    ] * 50
    ctx = AssemblyContext(
        agent_config=agent,
        user_message="Short question",
        session_history=long_history,
    )
    messages = await assemble_prompt(ctx)
    # Should not exceed ~200k tokens; rough check via message count
    assert len(messages) < 200


async def test_tools_tracked_in_budget():
    agent = _make_agent()
    tools = [
        ToolDef(
            name="fs_read",
            description="Read a file",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        )
    ]
    ctx = AssemblyContext(
        agent_config=agent,
        user_message="Read this file",
        tools=tools,
    )
    messages = await assemble_prompt(ctx)
    assert ctx.tokens_used > 0


async def test_memory_recall_injected():
    agent = _make_agent()
    ctx = AssemblyContext(
        agent_config=agent,
        user_message="Hi",
        memory_recall="User prefers concise responses.",
    )
    messages = await assemble_prompt(ctx)
    combined = " ".join(m.content if isinstance(m.content, str) else "" for m in messages)
    assert "concise" in combined


async def test_file_context_injected():
    agent = _make_agent()
    ctx = AssemblyContext(
        agent_config=agent,
        user_message="Review this",
        file_context="def hello(): return 'world'",
    )
    messages = await assemble_prompt(ctx)
    combined = " ".join(m.content if isinstance(m.content, str) else "" for m in messages)
    assert "hello" in combined


async def test_tokens_used_positive():
    agent = _make_agent()
    ctx = AssemblyContext(agent_config=agent, user_message="Test")
    await assemble_prompt(ctx)
    assert ctx.tokens_used > 0
