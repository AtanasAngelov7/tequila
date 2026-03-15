"""Sprint 04 — Agent data models (§4.1, §4.1a, §4.2a, §4.7).

This module defines all Pydantic models for the agent subsystem:
- ``SessionPolicy`` — tool / channel permission matrix for a session
- ``MemoryScope`` — what memory partitions an agent can access
- ``SoulConfig`` — personality, system-prompt template, and behaviour rules
- ``EscalationConfig`` — sub-agent handoff configuration
- ``ContextBudget`` — per-category token allocations for prompt assembly
- ``AgentConfig`` — the top-level agent record stored in the ``agents`` table
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── DEFAULT SYSTEM PROMPT TEMPLATE ────────────────────────────────────────────

DEFAULT_SYSTEM_PROMPT: str = """{{ persona }}

{% if instructions %}
## Rules
{% for rule in instructions %}
- {{ rule }}
{% endfor %}
{% endif %}

## Current context
- Date/time: {{ datetime }}
{% if user_name %}- User: {{ user_name }}{% endif %}

{% if skill_index %}
## Available Skills
{{ skill_index }}
{% endif %}

{% if active_skills %}
## Active Skills
{{ active_skills }}
{% endif %}

{% if memory %}
## Memory
{{ memory }}
{% endif %}

## Available tools
{{ tools }}
"""


# ── SESSION POLICY (§3.7) ─────────────────────────────────────────────────────


class SessionPolicy(BaseModel):
    """Permission matrix for a session — enforced by the gateway."""

    allowed_channels: list[str] = ["*"]
    """Delivery channels the agent may use (``*`` = all)."""

    allowed_tools: list[str] = ["*"]
    """Tool names the agent may invoke (``*`` = all)."""

    allowed_paths: list[str] = ["*"]
    """Filesystem path whitelist (``*`` = all)."""

    can_spawn_agents: bool = True
    """Whether this session may spawn sub-agents."""

    can_send_inter_session: bool = True
    """Whether this session may send messages to other sessions."""

    max_tokens_per_run: int | None = None
    """Cap on total tokens consumed per turn. ``None`` = unlimited."""

    max_tool_rounds: int = 25
    """Maximum tool-call iterations per turn."""

    require_confirmation: list[str] = []
    """Tool names that require explicit user approval before execution."""

    auto_approve: list[str] = []
    """Tools that bypass the confirmation gate even when in ``require_confirmation``."""


# ── MEMORY SCOPE (§5.2) ───────────────────────────────────────────────────────


class MemoryScope(BaseModel):
    """Memory access permissions for an agent."""

    can_read_shared: bool = True
    """Whether the agent can read from the shared knowledge/memory pool."""

    can_write_shared: bool = False
    """Only the main admin agent writes to shared memory."""

    private_namespace: str = ""
    """Agent-specific memory partition prefix.  Defaults to the agent_id."""


# ── SOUL CONFIGURATION (§4.1a) ────────────────────────────────────────────────


class SoulConfig(BaseModel):
    """Personality, behavioural rules, and system-prompt template for an agent."""

    # --- Identity ---
    persona: str = ""
    """Who the agent is — name, personality, tone, core purpose."""

    instructions: list[str] = []
    """Behavioural rules and constraints (each becomes a bullet in the system prompt)."""

    system_prompt_template: str = DEFAULT_SYSTEM_PROMPT
    """Jinja2 template rendered at prompt-assembly time (§4.3a step 1)."""

    # --- Behaviour modifiers ---
    tone: Literal["professional", "casual", "friendly", "formal", "custom"] = "friendly"
    """Desired conversational tone."""

    verbosity: Literal["concise", "balanced", "detailed"] = "balanced"
    """Default response length preference."""

    language: str = "en"
    """Preferred response language (ISO 639-1 code)."""

    emoji_usage: Literal["none", "minimal", "normal"] = "minimal"
    """How freely the agent may use emoji."""

    # --- Response formatting ---
    prefer_markdown: bool = True
    """Use markdown formatting in responses."""

    prefer_lists: bool = False
    """Prefer bullet-point lists over prose paragraphs."""

    code_block_style: Literal["fenced", "inline"] = "fenced"
    """Code formatting style."""

    # --- Safety & boundaries ---
    refuse_topics: list[str] = []
    """Topics the agent should decline to engage with."""

    escalation_phrases: list[str] = []
    """Phrases that trigger handoff to the main agent (sub-agents only)."""

    # --- Custom metadata ---
    metadata: dict[str, Any] = {}
    """Arbitrary key-value pairs available as ``{{ custom.key }}`` in templates."""


# ── ESCALATION CONFIG (§4.2a) ─────────────────────────────────────────────────


class EscalationConfig(BaseModel):
    """Controls automated sub-agent→main-agent handoff behaviour."""

    enabled: bool = True
    """Enable or disable escalation for this agent."""

    target_agent_id: str | None = None
    """Override target agent.  ``None`` → route to the main (is_admin=True) agent."""

    include_full_history: bool = False
    """Transfer entire session history vs. a short auto-generated summary."""

    context_message_count: int = 5
    """Number of recent messages to include in the context summary."""

    max_consecutive_failures: int = 3
    """Consecutive tool errors before auto-escalation fires."""

    notify_user: bool = True
    """Display a UI notification when escalation occurs."""


# ── CONTEXT BUDGET (§4.7) ─────────────────────────────────────────────────────


class ContextBudget(BaseModel):
    """Per-category token budget for prompt assembly (§4.3a)."""

    max_context_tokens: int = 200_000
    """Provider model's context window size."""

    reserved_for_response: int = 4_096
    """Tokens reserved for the model's output."""

    system_prompt_budget: int = 2_000
    """Budget for system prompt and soul instructions."""

    memory_always_recall_budget: int = 500
    """Always-recalled and pinned memories (step 2)."""

    memory_recall_budget: int = 2_000
    """Per-turn recalled memories (step 3)."""

    knowledge_source_budget: int = 1_500
    """External knowledge source results (step 3a)."""

    skill_index_budget: int = 500
    """Level-1 skill summaries — all assigned skills (step 4a)."""

    skill_instruction_budget: int = 1_500
    """Level-2 skill instructions — active skills only (step 4b)."""

    tool_schema_budget: int = 2_000
    """Tool definitions sent to the model (step 5)."""

    file_context_budget: int = 3_000
    """Uploaded file previews (step 6)."""

    max_tool_rounds: int = 25
    """Maximum tool-call loop iterations per turn."""

    compression_threshold: float = 0.6
    """Compress history when it exceeds this fraction of the remaining history budget."""

    min_recent_messages: int = 4
    """Always keep at least this many of the most recent messages."""

    @property
    def history_budget(self) -> int:
        """Tokens available for session history (all other budgets consumed)."""
        allocated = (
            self.reserved_for_response
            + self.system_prompt_budget
            + self.memory_always_recall_budget
            + self.memory_recall_budget
            + self.knowledge_source_budget
            + self.skill_index_budget
            + self.skill_instruction_budget
            + self.tool_schema_budget
            + self.file_context_budget
        )
        return max(0, self.max_context_tokens - allocated)


# ── AGENT CONFIG (§4.1) ───────────────────────────────────────────────────────


class AgentConfig(BaseModel):
    """Full agent record.  Stored (serialised as JSON sub-fields) in the ``agents`` table."""

    agent_id: str = Field(default_factory=lambda: f"agent:{uuid.uuid4().hex[:12]}")
    """Unique identifier, e.g. ``agent:abc123def456``."""

    name: str
    """Human-readable agent name."""

    role: str = "main"
    """Semantic role — ``main``, ``research``, ``code``, ``calendar``, etc."""

    soul: SoulConfig = Field(default_factory=SoulConfig)
    """Personality, system-prompt template, and behavioural rules."""

    default_model: str = ""
    """Provider-qualified model ID, e.g. ``anthropic:claude-sonnet-4-5``."""

    fallback_provider_id: str | None = None
    """Provider to switch to when the primary provider's circuit-breaker opens."""

    tools: list[str] = []
    """Enabled tool-group names (§4.5.8)."""

    skills: list[str] = []
    """Attached skill IDs (§4.5.3)."""

    default_policy: SessionPolicy = Field(default_factory=SessionPolicy)
    """Default ``SessionPolicy`` applied to new sessions for this agent."""

    memory_scope: MemoryScope = Field(default_factory=MemoryScope)
    """Memory access permissions."""

    is_admin: bool = False
    """Admin agents can modify other agents' configs and see all sessions."""

    context_budget: ContextBudget = Field(default_factory=ContextBudget)
    """Per-category token budgets for prompt assembly (§4.5)."""

    escalation: EscalationConfig = Field(default_factory=EscalationConfig)
    """Escalation behaviour configuration (§4.2a)."""

    status: Literal["active", "paused", "archived"] = "active"
    """Lifecycle status."""

    version: int = 1
    """Optimistic concurrency counter (OCC, §20.3b)."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ── DB serialisation helpers ──────────────────────────────────────────────

    def to_row(self) -> dict[str, Any]:
        """Serialise to a flat dict for the ``agents`` table."""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "role": self.role,
            "soul": self.soul.model_dump_json(),
            "provider": self.default_model.split(":")[0] if ":" in self.default_model else "",
            "default_model": self.default_model,
            "persona": self.soul.persona,
            "fallback_provider_id": self.fallback_provider_id,
            "tools": json.dumps(self.tools),
            "skills": json.dumps(self.skills),
            "default_policy": self.default_policy.model_dump_json(),
            "memory_scope": self.memory_scope.model_dump_json(),
            "is_admin": int(self.is_admin),
            "escalation": self.escalation.model_dump_json(),
            "status": self.status,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "AgentConfig":
        """Deserialise from an ``agents`` table row dict."""

        def _load(key: str, default: Any = None) -> Any:
            raw = row.get(key)
            if raw is None or raw == "":
                return default
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return default

        soul_data = _load("soul", {})
        soul = SoulConfig(**soul_data) if soul_data else SoulConfig()

        policy_data = _load("default_policy", {})
        policy = SessionPolicy(**policy_data) if policy_data else SessionPolicy()

        scope_data = _load("memory_scope", {})
        scope = MemoryScope(**scope_data) if scope_data else MemoryScope()

        esc_data = _load("escalation", {})
        esc = EscalationConfig(**esc_data) if esc_data else EscalationConfig()

        return cls(
            agent_id=row["agent_id"],
            name=row["name"],
            role=row.get("role", "main"),
            soul=soul,
            default_model=row.get("default_model", ""),
            fallback_provider_id=row.get("fallback_provider_id"),
            tools=_load("tools", []),
            skills=_load("skills", []),
            default_policy=policy,
            memory_scope=scope,
            is_admin=bool(row.get("is_admin", False)),
            escalation=esc,
            status=row.get("status", "active"),
            version=row.get("version", 1),
            created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row.get("updated_at") else datetime.now(timezone.utc),
        )
