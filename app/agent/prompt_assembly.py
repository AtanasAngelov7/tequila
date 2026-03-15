"""Sprint 04 — 9-Step prompt assembly pipeline (§4.5).

``assemble_prompt()`` builds the ordered list of messages to send to an LLM
provider, respecting the ``ContextBudgetConfig`` limits on every category.

Steps
-----
1. System prompt render    (Jinja2 via soul.render_soul_prompt)
2. Always-recall memories  (stub — returns empty in Sprint 04)
3. Per-turn memory recall  (stub)
3a. Knowledge source ctx   (stub)
4. Skill descriptions      (stub)
5. Tool definitions        (formatted per provider — budget‑capped)
6. File context injection  (stub)
7. Session history         (loads DB messages, oldest first, budget‑capped)
8. Current message         (always included last)

Each step tracks tokens against its category budget.  When a step would
exceed its budget, it is truncated / omitted gracefully.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.agent.models import AgentConfig, ContextBudgetConfig
from app.agent.soul import render_soul_prompt
from app.providers.base import Message, ToolDef

logger = logging.getLogger(__name__)


@dataclass
class AssemblyContext:
    """Mutable state object threaded through prompt assembly steps."""

    agent_config: AgentConfig
    user_message: str
    session_history: list[dict[str, Any]] = field(default_factory=list)
    """Raw message rows from the database (newest last)."""

    user_name: str = ""
    tools: list[ToolDef] = field(default_factory=list)

    # ── Optional context blobs (Sprint 04 stubs — empty strings) ──────────
    memory_always: str = ""
    memory_recall: str = ""
    knowledge_context: str = ""
    skill_index: str = ""
    active_skills: str = ""
    file_context: str = ""

    # ── Token budget tracking ──────────────────────────────────────────────
    tokens_used: int = 0

    def budget(self) -> ContextBudgetConfig:
        """Return the static slot-size limits from config (``ContextBudgetConfig``).

        This is the *configuration* object, not the runtime ``ContextBudget``
        engine.  Use it to read token ceilings per category (e.g.
        ``system_prompt_budget``, ``memory_recall_budget``).  For dynamic
        remaining-token tracking, call ``remaining()`` instead.
        """
        return self.agent_config.context_budget

    def remaining(self) -> int:
        b = self.budget()
        return max(0, b.max_context_tokens - b.reserved_for_response - self.tokens_used)


def _estimate_tokens(text: str) -> int:
    """Fast O(n) token estimate without a tokenizer.

    Splits on whitespace and punctuation; each whitespace-separated token
    ≈ 1.3 BPE tokens on average.  This is intentionally conservative.
    """
    if not text:
        return 0
    words = text.split()
    return max(1, int(len(words) * 1.3))


def _format_tools_for_prompt(tools: list[ToolDef]) -> str:
    """Render tool list as a compact text block for the system prompt."""
    if not tools:
        return ""
    lines = ["Available tools:\n"]
    for t in tools:
        lines.append(f"  • {t.name}: {t.description}")
    return "\n".join(lines)


async def assemble_prompt(ctx: AssemblyContext) -> list[Message]:
    """Run the 9-step prompt assembly pipeline.

    Returns an ordered list of ``Message`` objects ready to pass to
    ``LLMProvider.stream_completion()``.
    """
    budget = ctx.budget()
    messages: list[Message] = []

    # ── Step 1: System prompt render ──────────────────────────────────────
    tools_block = _format_tools_for_prompt(ctx.tools)
    system_text = render_soul_prompt(
        ctx.agent_config.soul,
        user_name=ctx.user_name,
        skill_index=ctx.skill_index,
        active_skills=ctx.active_skills,
        memory=ctx.memory_always,
        tools=tools_block,
    )
    sys_tokens = _estimate_tokens(system_text)
    if sys_tokens > budget.system_prompt_budget:
        # Hard truncate system prompt to budget (word boundary)
        words = system_text.split()
        approx_word_limit = int(budget.system_prompt_budget / 1.3)
        system_text = " ".join(words[:approx_word_limit])
        sys_tokens = _estimate_tokens(system_text)
        logger.warning("System prompt truncated to ~%d tokens", sys_tokens)

    messages.append(Message(role="system", content=system_text))
    ctx.tokens_used += sys_tokens

    # ── Step 2: Always-recall memories ────────────────────────────────────
    if ctx.memory_always:
        mem_tokens = _estimate_tokens(ctx.memory_always)
        if mem_tokens <= budget.memory_always_recall_budget:
            messages.append(
                Message(role="user", content=f"[system memory]\n{ctx.memory_always}")
            )
            messages.append(Message(role="assistant", content="Understood."))
            ctx.tokens_used += mem_tokens

    # ── Step 3: Per-turn memory recall ────────────────────────────────────
    if ctx.memory_recall:
        tokens = _estimate_tokens(ctx.memory_recall)
        if tokens <= budget.memory_recall_budget and ctx.remaining() > tokens:
            messages.append(
                Message(role="user", content=f"[recalled context]\n{ctx.memory_recall}")
            )
            messages.append(Message(role="assistant", content="Got it."))
            ctx.tokens_used += tokens

    # ── Step 3a: Knowledge source context ────────────────────────────────
    if ctx.knowledge_context:
        tokens = _estimate_tokens(ctx.knowledge_context)
        if tokens <= budget.knowledge_source_budget and ctx.remaining() > tokens:
            messages.append(
                Message(role="user", content=f"[knowledge]\n{ctx.knowledge_context}")
            )
            messages.append(Message(role="assistant", content="Noted."))
            ctx.tokens_used += tokens

    # ── Step 4: Skill descriptions ────────────────────────────────────────
    if ctx.skill_index:
        tokens = _estimate_tokens(ctx.skill_index)
        if tokens <= budget.skill_index_budget and ctx.remaining() > tokens:
            ctx.tokens_used += tokens  # already embedded in system prompt above

    # ── Step 5: Tool definitions ──────────────────────────────────────────
    # Tool defs are passed separately to provider.stream_completion() as
    # ToolDef objects — not injected into messages.  Token budget tracked here.
    if ctx.tools:
        tool_text = tools_block
        tool_tokens = _estimate_tokens(tool_text)
        if tool_tokens <= budget.tool_schema_budget:
            ctx.tokens_used += tool_tokens
        else:
            logger.warning("Tool schema exceeds budget (%d > %d)", tool_tokens, budget.tool_schema_budget)

    # ── Step 6: File context injection ───────────────────────────────────
    if ctx.file_context:
        tokens = _estimate_tokens(ctx.file_context)
        if tokens <= budget.file_context_budget and ctx.remaining() > tokens:
            messages.append(
                Message(role="user", content=f"[file context]\n{ctx.file_context}")
            )
            messages.append(Message(role="assistant", content="I see the file context."))
            ctx.tokens_used += tokens

    # ── Step 7: Session history (budget-capped) ────────────────────────────
    history_budget = budget.history_budget - ctx.tokens_used
    # Estimate current user message tokens and reserve that
    user_msg_tokens = _estimate_tokens(ctx.user_message)
    history_budget -= user_msg_tokens

    if history_budget > 0 and ctx.session_history:
        # Walk history newest-first, collect until budget exhausted
        selected: list[dict[str, Any]] = []
        used = 0
        for row in reversed(ctx.session_history):
            row_text = row.get("content", "")
            row_tokens = _estimate_tokens(row_text)
            if used + row_tokens > history_budget:
                if len(selected) < budget.min_recent_messages:
                    # Must include at least min_recent_messages
                    selected.append(row)
                    used += row_tokens
                break
            selected.append(row)
            used += row_tokens
            if len(selected) >= 200:  # hard cap on message count
                break

        # Reverse back to chronological order
        selected.reverse()

        for row in selected:
            role = row.get("role", "user")
            content = row.get("content", "")
            if role in ("user", "assistant", "tool", "system"):
                messages.append(Message(role=role, content=content))  # type: ignore[arg-type]

        ctx.tokens_used += used

    # ── Step 8: Current user message ─────────────────────────────────────
    messages.append(Message(role="user", content=ctx.user_message))
    ctx.tokens_used += user_msg_tokens

    logger.debug(
        "Prompt assembled: %d messages, ~%d tokens (budget=%d)",
        len(messages),
        ctx.tokens_used,
        budget.max_context_tokens,
    )
    return messages
