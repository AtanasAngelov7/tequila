# Sprint 07 — Context Management, Policies & Approvals

**Phase**: 2 – Agent Core (**Phase Gate Sprint**)
**Duration**: 2 weeks
**Status**: ⬜ Not Started
**Build Sequence Items**: BS-16, BS-17, BS-18

> **📖 Spec reference**: For full design context, data models, and acceptance details, consult [tequila_v2_specification.md](../tequila_v2_specification.md) at the §-sections listed in the Spec References table below.

---

## Goal

Complete the Agent Core phase by implementing context window management (compression, token counting, budget enforcement), session policy enforcement in the gateway, and the full approval flow wiring. By sprint end, the agent intelligently manages long conversations within token limits, policies govern what each session/agent can do, and approval requests flow end-to-end through the UI.

---

## Spec References

| Section | Topic |
|---------|-------|
| §4.7 | Context window management (ContextBudget, compression strategies, token counting cache) |
| §4.3a | Prompt assembly budget allocation & priority trimming |
| §19.1 | Retry policy (exponential backoff, prefix-matched errors) |
| §19.2 | Circuit breaker |
| §19.3 | Graceful degradation |
| §11.2 | Approval flow (full wiring) |
| §20.3c | State transition safety (conditional WHERE clauses) |

---

## Prerequisites

- Requires Sprint 06 deliverables to be completed before this sprint begins.

---

## Deliverables

### D1: Context Window Management
- `app/agent/context.py` — `ContextBudget` class:
  - Total budget = model's context window − reserved output tokens
  - Slot allocation: system prompt, soul, memories, conversation history, tool results
  - Priority trimming: when over budget, trim lowest-priority slots first
  - Token counting: use `tiktoken` for OpenAI models, `tiktoken` approximation for others, Ollama fallback
  - Token counting cache: session-level cache for message token counts (invalidated on edit)
- Compression strategies:
  - `summarize_old`: LLM-compress early conversation turns into summary block
  - `drop_tool_results`: replace large tool outputs with `[result truncated]`
  - `trim_oldest`: remove oldest messages when all else fails
- Automatic compression trigger: when usage > 80% of budget

**Acceptance**: Long conversation → compression fires → conversation stays within budget. Token counts accurate.

### D2: Error Handling & Resilience
- Extend `app/providers/circuit_breaker.py` (created in Sprint 04 with `RetryPolicy` + `CircuitBreaker`):
  - Add `GracefulDegradation`: fallback provider chain (e.g., Claude → GPT-4 → Ollama local) (§19.3)
- Integrate the existing `RetryPolicy` and `CircuitBreaker` from S04 with provider streaming calls in the turn loop
- Circuit breaker state visible in health endpoint
- **Note**: `RetryPolicy` and `CircuitBreaker` already exist from Sprint 04 in `app/providers/circuit_breaker.py`. This sprint adds `GracefulDegradation` to the same file and wires all three into the turn loop — do not recreate or duplicate them.

**Acceptance**: Provider timeout → retry with backoff → circuit trips after 3 failures → fallback provider used.

### D3: Session Policy Enforcement
- `app/sessions/policy.py` — expand the SessionPolicy model (created in Sprint 01) with enforcement logic:
  - Fields already defined in Sprint 01: `allowed_channels`, `allowed_tools`, `allowed_paths`, `can_spawn_agents`, `can_send_inter_session`, `max_tokens_per_run`, `max_tool_rounds`, `require_confirmation`, `auto_approve`
  - ~~`blocked_tools`~~ — **removed from spec** (§4.5.8); use `require_confirmation` for tools needing human-in-the-loop
  - Add enforcement function: `check_policy(policy, event, session_record)` → `PolicyResult`
- Policy checked at gateway level before tool execution
- Default policy: all tools allowed, destructive requires approval
- Policy presets (§2.7): `ADMIN`, `STANDARD` (default), `WORKER`, `CODE_RUNNER`, `READ_ONLY`, `CHAT_ONLY`

**Acceptance**: Session with restricted policy → blocked tool → clear error. Auto-approve skips approval for listed tools. `require_confirmation` forces approval gate.

### D4: Approval Flow (Policy-Driven Extension)
- Extend the initial approval mechanism from Sprint 05 with policy-driven controls:
  - `SessionPolicy.require_confirmation` overrides safety-level defaults — any tool in this list requires approval regardless of its safety classification
  - `SessionPolicy.auto_approve` skips approval gate for listed tools
  - Policy checked at gateway level before tool execution
- Persistent batch-allow: "allow-all for this tool **in this session**" option (persists across turns, unlike S05's per-turn allow-all)
- Audit logging: all approval decisions logged with decision, actor, tool, timestamp
- **Note**: Sprint 05 built the core mechanism (safety-level trigger → banner → approve/deny → execute). This sprint adds policy overrides, persistent session-scoped batch-allow, and audit integration.

**Acceptance**: Policy `require_confirmation` forces approval on safe tools. `auto_approve` skips gate. Batch-allow persists for session. All decisions audited.

### D5: Agent Error Recovery
- Turn-level error handling:
  - Provider error → retry → fallback → user-visible error message
  - Tool error → error result fed back to LLM for self-correction
  - Context overflow → auto-compress → retry turn
- Error messages: structured, user-friendly, with "retry" button in UI
- Frontend: error state display, retry action

**Acceptance**: Provider failure → graceful fallback shown. Tool error → agent self-corrects. Context overflow → compression.

---

## Tasks

### Backend — Context Management
- [ ] Create `app/agent/context.py` — ContextBudget class
- [ ] Implement slot allocation (system, soul, memories, history, tools)
- [ ] Implement priority trimming algorithm
- [ ] Implement token counting with tiktoken + cache
- [ ] Implement compression: summarize_old strategy
- [ ] Implement compression: drop_tool_results strategy
- [ ] Implement compression: trim_oldest strategy
- [ ] Auto-compression trigger at 80% threshold
- [ ] Integration with prompt assembly pipeline

### Backend — Resilience
- [ ] Extend `app/providers/circuit_breaker.py` (from S04) — add `GracefulDegradation` class (§19.3)
- [ ] Integrate `RetryPolicy` (from S04) with provider streaming calls in turn loop
- [ ] Integrate `CircuitBreaker` (from S04) with provider streaming calls in turn loop
- [ ] Wire `GracefulDegradation` fallback provider chain into turn loop
- [ ] Expose circuit breaker state in health endpoint

### Backend — Session Policy
- [ ] Expand `app/sessions/policy.py` (from S01) — add enforcement logic to SessionPolicy model
- [ ] Add policy column to sessions table + migration
- [ ] Policy enforcement in gateway (pre-tool-execution check)
- [ ] Default policy: all tools, destructive approval required
- [ ] API: `PATCH /api/sessions/{id}/policy`

### Backend — Approval Flow (extend S05)
- [ ] Add policy-driven approval triggering (`require_confirmation` list overrides safety level)
- [ ] Add `auto_approve` bypass for listed tools
- [ ] Upgrade batch-allow from per-turn (S05) to persistent per-session override
- [ ] Audit log entries for all approval decisions (decision, actor, tool, timestamp)

### Frontend
- [ ] Context budget indicator (show usage % in session header)
- [ ] Error state display with retry button
- [ ] Approval timeout countdown
- [ ] Session policy display (show active restrictions)

### Tests
- [ ] `tests/unit/test_context_budget.py` — allocation, trimming, compression
- [ ] `tests/unit/test_resilience.py` — retry, circuit breaker, fallback
- [ ] `tests/unit/test_session_policy.py` — allow/require_confirmation/auto-approve, presets
- [ ] `tests/integration/test_approval_e2e.py` — full round-trip
- [ ] `tests/integration/test_error_recovery.py` — provider failure → fallback

---

## Testing Requirements

- Context: 200+ message conversation → compression fires → stays in budget.
- Resilience: mock provider timeout → retry 3x → circuit trips → fallback activates.
- Policy: restricted session → non-allowed tool returns error. `require_confirmation` forces approval. Auto-approve skips gate.
- Approval: full round-trip with timeout and batch-allow scenarios.

---

## Definition of Done

- [ ] Context compression fires automatically for long conversations
- [ ] Token counting accurate (within 5% of actual provider count)
- [ ] Circuit breaker trips after consecutive failures, falls back gracefully
- [ ] Session policy restricts tools per configuration
- [ ] Approval flow works end-to-end with timeout and batch-allow
- [ ] Error recovery: provider failure, tool error, context overflow all handled
- [ ] All tests pass
- [ ] **Phase 2 gate**: Agent can chat, use tools, manage context, handle errors — full agent core operational

---

## Risks & Notes

- **Compression quality**: LLM-generated summaries may lose important context. Validate with conversation replay tests.
- **Token counting accuracy**: tiktoken estimates may diverge for non-OpenAI models. Monitor and calibrate.
- **Phase gate**: This sprint gates Phase 2. Allocate time for integration testing of the entire agent pipeline end-to-end (S04-S07 combined).
