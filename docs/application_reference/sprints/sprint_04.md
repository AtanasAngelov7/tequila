# Sprint 04 — Agent Model, Providers & Prompt Assembly

**Phase**: 2 – Agent Core
**Duration**: 2 weeks
**Status**: ⬜ Not Started
**Build Sequence Items**: BS-6, BS-7, BS-8, BS-9

> **📖 Spec reference**: For full design context, data models, and acceptance details, consult [tequila_v2_specification.md](../tequila_v2_specification.md) at the §-sections listed in the Spec References table below.

---

## Goal

Build the agent runtime foundation: agent model with SoulConfig, the full LLM provider abstraction layer (Anthropic, OpenAI, Ollama adapters), the model capability registry, and the 9-step prompt assembly pipeline. By sprint end, prompt assembly produces correct, budget-aware message lists for any configured provider.

---

## Spec References

| Section | Topic |
|---------|-------|
| §4.1 | AgentConfig model |
| §4.1a | SoulConfig, Jinja2 system prompt template |
| §4.2a | Escalation protocol + EscalationConfig |
| §4.3a | 9-step prompt assembly pipeline |
| §4.5.8 | Tool groups (definitions only — full skill system is Sprint 14, §4.5.0–4.5.7) |
| §4.6 | Provider abstraction layer (LLMProvider ABC) |
| §4.6a | Tool-calling protocol (ToolDef, ProviderStreamEvent, ToolResult) |
| §4.6b | Model capability registry (ModelCapabilities) |
| §4.6c | Ollama provider adapter |
| §4.7 | Context window management (ContextBudget) |

---

## Prerequisites

- Requires Sprint 03 deliverables and the Phase 1 gate to be completed before this sprint begins.

---

## Deliverables

### D1: Agent Config Model + CRUD
- `app/agent/models.py` — `AgentConfig`, `SoulConfig`, `ContextBudget`, `EscalationConfig`
- `agents` database table + migration
- `app/api/routers/agents.py` — full agent CRUD: create, list, get, update, delete, clone
- Agent soul read/update endpoints
- Import/export agent config (JSON)

**Acceptance**: Agents can be created, configured, and managed via REST API.

### D2: Soul Configuration
- `SoulConfig` model (§4.1a): persona, instructions, tone, verbosity, language, emoji_usage, response formatting, refuse_topics, escalation_phrases, metadata
- `app/agent/soul.py` — Jinja2 template rendering with variables (persona, instructions, datetime, user_name, tools, skills, memory, custom)
- Default system prompt template (`DEFAULT_SYSTEM_PROMPT`)
- Soul editor UI component (frontend)

**Acceptance**: System prompt renders correctly from SoulConfig via Jinja2. All template variables injected.

### D3: Provider Abstraction Layer
- `app/providers/base.py` — `LLMProvider` ABC, `ProviderStreamEvent`, `ToolDef`, `ToolResult`, `ResponseFormat`
- `app/providers/registry.py` — provider registry, model discovery, `ModelCapabilities` cache
- `app/providers/anthropic.py` — Anthropic adapter (streaming, tool calls, vision content blocks)
- `app/providers/openai.py` — OpenAI adapter (streaming, tool calls, vision content blocks)
- `app/providers/ollama.py` — Ollama adapter (§4.6c: model discovery, tiktoken fallback, $0 cost)
- `app/providers/circuit_breaker.py` — `RetryPolicy`, `CircuitBreaker` (§19.1–19.2)

**Acceptance**: Each adapter can stream a completion, return tool calls in unified format, and handle errors. Ollama adapter connects and lists models.

### D4: Model Capability Registry
- `ModelCapabilities` model (§4.6b): context_window, max_output, vision, tools, thinking, structured_output, cost rates
- `ModelInfo` model for UI model selector
- Per-provider model listing → capabilities populated
- UI model selector: models grouped by provider with capability badges

**Acceptance**: `/api/providers` lists all available models with capabilities. UI shows model picker.

### D5: Prompt Assembly Pipeline
- `app/agent/prompt_assembly.py` — 9-step pipeline (§4.3a)
  - Step 1: System prompt render (Jinja2)
  - Step 2: Always-recall memories (stub — returns empty until S09)
  - Step 3: Per-turn memory recall (stub)
  - Step 3a: Knowledge source context (stub)
  - Step 4: Skill descriptions (stub)
  - Step 5: Tool definitions (formats per provider)
  - Step 6: File context injection (stub)
  - Step 7: Session history (load messages, apply compression)
  - Step 8: Current message (always included)
- Budget allocation per step from `ContextBudget`
- Priority trimming when over budget (§4.3a trimming order)
- Token counting via provider's `count_tokens()`

**Acceptance**: Pipeline produces provider-ready message list. Budget trimming verified via unit tests.

### D6: Escalation Protocol
- `app/agent/escalation.py` — escalation triggers (phrase-match, tool-call, failure-count)
- `EscalationConfig` model on agents
- Gateway `escalation.triggered` event
- Context transfer: auto-summary of last N messages to target agent
- `POST /api/sessions/{id}/escalate` endpoint

**Acceptance**: Escalation triggers fire correctly. Context transferred to target session.

### D7: Agent Management UI
- `frontend/src/pages/AgentsPage.tsx` — agent list, create, edit, delete
- `frontend/src/components/agents/AgentCard.tsx` — agent summary card
- `frontend/src/components/agents/SoulEditor.tsx` — persona, instructions, tone editor
- Agent selector in chat (switch which agent to talk to)

**Acceptance**: Agents manageable from UI. Soul editor saves and renders preview.

### D8: Session Title Auto-Generation & Summaries (deferred from S03)
- Wire up LLM-powered session features using the new provider abstraction:
  - After first user+assistant exchange, auto-generate title via LLM call (§3.2)
  - Title re-generation heuristic: if conversation topic shifts significantly (max once per 20 messages)
  - Summary generation: update periodically (every 20 messages or on session archive)
- Uses provider abstraction (D3) for LLM calls — no standalone helper needed
- **Note**: Sprint 03 created the session title field, default titles, and manual rename. This deliverable adds the LLM-powered intelligence on top.

**Acceptance**: After first exchange, session title auto-updates to a contextual summary. Title re-generates on topic shift. Summary field populated on archive.

---

## Tasks

### Backend — Agent Model
- [ ] Create `app/agent/models.py` — AgentConfig, SoulConfig, ContextBudget, EscalationConfig
- [ ] Add `agents` table migration
- [ ] Create `app/api/routers/agents.py` — CRUD + clone + import/export
- [ ] Create `app/agent/soul.py` — Jinja2 rendering + DEFAULT_SYSTEM_PROMPT

### Backend — Providers
- [ ] Create `app/providers/base.py` — LLMProvider ABC + models
- [ ] Create `app/providers/registry.py` — provider registration, ModelCapabilities cache
- [ ] Create `app/providers/anthropic.py` — Anthropic streaming adapter
- [ ] Create `app/providers/openai.py` — OpenAI streaming adapter
- [ ] Create `app/providers/ollama.py` — Ollama adapter (model discovery, tiktoken fallback)
- [ ] Create `app/providers/circuit_breaker.py` — RetryPolicy, CircuitBreaker

### Backend — Prompt Assembly
- [ ] Create `app/agent/prompt_assembly.py` — 9-step pipeline
- [ ] Implement budget allocation + priority trimming
- [ ] Wire token counting per provider
- [ ] Implement compression trigger detection (threshold = 60% of history budget)

### Backend — Escalation
- [ ] Create `app/agent/escalation.py` — trigger detection + context transfer
- [ ] Add escalation gateway event
- [ ] Add `POST /api/sessions/{id}/escalate` endpoint

### Backend — Session LLM Features (deferred from S03)
- [ ] Implement title auto-generation (LLM call via provider abstraction after first exchange)
- [ ] Implement title re-generation heuristic (topic shift detection, max 1 per 20 msgs)
- [ ] Implement summary generation (periodic + on archive)

### Frontend
- [ ] Create AgentsPage with list/create/edit/delete
- [ ] Create SoulEditor component
- [ ] Create AgentCard component
- [ ] Add agent selector dropdown in chat header
- [ ] Add model picker UI component (grouped by provider, capability badges)
- [ ] Wire up TanStack Query hooks: `useAgents.ts`

### Tests
- [ ] `tests/unit/test_prompt_assembly.py` — pipeline steps, budget trimming
- [ ] `tests/unit/test_soul_render.py` — Jinja2 template rendering
- [ ] `tests/unit/test_circuit_breaker.py` — retry, circuit states
- [ ] `tests/unit/test_context_budget.py` — budget allocation, priority order
- [ ] `tests/unit/test_session_title_gen.py` — LLM title auto-generation, re-generation heuristic, summary
- [ ] `tests/integration/test_api_agents.py` — agent CRUD

---

## Testing Requirements

- Prompt assembly produces correct message structure for Anthropic, OpenAI, Ollama format requirements.
- Budget trimming removes lower-priority content first.
- Circuit breaker transitions: closed → open → half-open → closed.
- Agent CRUD API fully tested.

---

## Definition of Done

- [ ] Agents can be created and configured via UI and API
- [ ] Soul editor renders system prompt preview
- [ ] Provider adapters stream completions (tested with at least one real provider)
- [ ] Prompt assembly pipeline produces correct message lists under budget
- [ ] Model capability registry populated from provider queries
- [ ] Escalation protocol detects triggers and transfers context
- [ ] Session title auto-generates after first exchange; summary generates on archive
- [ ] All tests pass

---

## Risks & Notes

- **Provider API keys**: Real provider testing requires API keys. Use `MockProvider` for CI; manual testing with real providers during development.
- **Ollama may not be installed**: Ollama adapter should gracefully handle "not connected" state (mark `available=False`).
- **Prompt assembly stubs**: Steps 2, 3, 3a, 4, 6 return empty content until Memory (S09–S11), Skills (S14), and Files (S13) are implemented. The pipeline structure is complete; content fills in later.
- **Token counting cost**: Token counting happens on every turn. Cache per-message token counts in S07.
