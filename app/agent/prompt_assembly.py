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
from app.agent.skills import SessionSkillState
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
    active_skill_ids: list[str] = field(default_factory=list)
    """Skill IDs that were activated this turn (populated by Step 0)."""
    session_skill_state: SessionSkillState = field(default_factory=SessionSkillState)
    """Per-session manual skill overrides (manually_activated / manually_deactivated)."""
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

    # ── Step 0: Resolve skill context (§4.5.2 steps 4a + 4b) ─────────────
    # Populate skill_index (Level 1) and active_skills (Level 2) before the
    # system prompt is rendered in Step 1 (both are embedded via Jinja2 slots).
    if not ctx.skill_index and ctx.agent_config.skills:
        try:
            from app.agent.skills import get_skill_store, get_skill_engine
            _skill_store = get_skill_store()
            _engine = get_skill_engine()
            _agent_skills = await _skill_store.get_skills_for_agent(ctx.agent_config.skills)
            # Step 4a: Level 1 index for all assigned skills
            ctx.skill_index = _engine.render_skill_index(
                _agent_skills, budget.skill_index_budget
            )
            # Step 4b: Level 2 instructions for active skills
            _active_text, _active_ids = _engine.resolve_active_skills(
                _agent_skills,
                ctx.user_message,
                ctx.session_skill_state,
                ctx.agent_config.tools,
                budget.skill_instruction_budget,
            )
            ctx.active_skills = _active_text
            ctx.active_skill_ids = _active_ids
        except RuntimeError:
            pass  # SkillStore not initialised — skip gracefully
        except Exception as _exc:
            logger.warning("Skill resolution failed (non-fatal): %s", _exc)

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
            # TD-222: Use system message instead of fake user/assistant pairs
            messages.append(
                Message(role="system", content=f"[system memory]\n{ctx.memory_always}")
            )
            ctx.tokens_used += mem_tokens

    # ── Step 3: Per-turn memory recall ────────────────────────────────────
    if ctx.memory_recall:
        tokens = _estimate_tokens(ctx.memory_recall)
        if tokens <= budget.memory_recall_budget and ctx.remaining() > tokens:
            messages.append(
                Message(role="system", content=f"[recalled context]\n{ctx.memory_recall}")
            )
            ctx.tokens_used += tokens

    # ── Step 3a: Knowledge source context ────────────────────────────────
    if ctx.knowledge_context:
        tokens = _estimate_tokens(ctx.knowledge_context)
        if tokens <= budget.knowledge_source_budget and ctx.remaining() > tokens:
            messages.append(
                Message(role="system", content=f"[knowledge]\n{ctx.knowledge_context}")
            )
            ctx.tokens_used += tokens

    # ── Step 4: Skill tokens (already counted in system prompt) ────────────
    # TD-202: Level 1 (skill_index) and Level 2 (active_skills) are embedded
    # into the system prompt via Jinja2 in Step 1.  Their tokens are already
    # counted as part of sys_tokens.  We do NOT add them again here.

    # ── Step 5: Tool definitions ──────────────────────────────────────────
    # Tool defs are passed separately to provider.stream_completion() as
    # ToolDef objects — not injected into messages.  Token budget tracked here.
    # Note: tools_block is also embedded in the system prompt (Step 1) via
    # render_soul_prompt — so we only log a warning if the schema is large,
    # but do NOT add tool_tokens to ctx.tokens_used (already counted in sys_tokens).
    if ctx.tools:
        tool_text = tools_block
        tool_tokens = _estimate_tokens(tool_text)
        if tool_tokens > budget.tool_schema_budget:
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
    # TD-203: Use remaining() for history budget instead of subtracting from
    # a slot-specific budget which can go negative.
    user_msg_tokens = _estimate_tokens(ctx.user_message)
    history_budget = max(0, ctx.remaining() - user_msg_tokens)

    if history_budget > 0 and ctx.session_history:
        # Walk history newest-first, collect until budget exhausted
        selected: list[dict[str, Any]] = []
        used = 0
        for row in reversed(ctx.session_history):
            row_text = row.get("content", "")
            row_tokens = _estimate_tokens(row_text)
            if used + row_tokens > history_budget:
                if len(selected) < budget.min_recent_messages:
                    # TD-223: Must include at least min_recent_messages
                    # TD-353: But cap forced inclusion at 150% of history budget
                    # to prevent a single huge message from blowing the context.
                    max_forced = int(history_budget * 1.5) if history_budget > 0 else row_tokens
                    if used + row_tokens <= max_forced:
                        selected.append(row)
                        used += row_tokens
                        continue  # keep going until min_recent_messages met
                    else:
                        logger.warning(
                            "min_recent_messages (%d) not fully met: message (%d tok) "
                            "would exceed forced-inclusion cap (%d tok)",
                            budget.min_recent_messages, row_tokens, max_forced,
                        )
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
                # TD-277: Preserve tool_call_id and tool_calls metadata
                msg_kwargs: dict[str, Any] = {"role": role, "content": content}
                if row.get("tool_call_id"):
                    msg_kwargs["tool_call_id"] = row["tool_call_id"]
                if row.get("tool_calls"):
                    msg_kwargs["tool_calls"] = row["tool_calls"]
                messages.append(Message(**msg_kwargs))  # type: ignore[arg-type]

        ctx.tokens_used += used

    # ── Step 8: Current user message ─────────────────────────────────────
    # TD-276: Only append user message when there's actual user content
    # (skip on tool continuation rounds where user_message is empty).
    if ctx.user_message:
        messages.append(Message(role="user", content=ctx.user_message))
        ctx.tokens_used += user_msg_tokens

    logger.debug(
        "Prompt assembled: %d messages, ~%d tokens (budget=%d)",
        len(messages),
        ctx.tokens_used,
        budget.max_context_tokens,
    )
    return messages
