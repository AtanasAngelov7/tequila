# Sprint 05 — Turn Loop, Message Model & Tool Framework

**Phase**: 2 – Agent Core
**Duration**: 2 weeks
**Status**: ⬜ Not Started
**Build Sequence Items**: BS-10, BS-10a, BS-10b, BS-11

> **📖 Spec reference**: For full design context, data models, and acceptance details, consult [tequila_v2_specification.md](../tequila_v2_specification.md) at the §-sections listed in the Spec References table below.

---

## Goal

Wire up the full agent turn loop: user message → prompt assembly → provider streaming → tool-call parsing → tool execution → response persistence. Implement the complete message model with branching/regeneration, message feedback, and the tool framework with safety classification. By sprint end, a user can chat with an LLM, see streaming responses, and the agent can call tools.

---

## Spec References

| Section | Topic |
|---------|-------|
| §3.4 | Full Message model (ContentBlock, ToolCallRecord, provenance, branching) |
| §3.5 | Conversation branching & regeneration |
| §3.6 | Message feedback (thumbs up/down) |
| §4.3 | Turn loop (7-step cycle) |
| §4.6a | Tool-calling protocol (parallel tool calls, ToolResult) |
| §11.1 | Tool safety classification |
| §11.2 | Approval flow |
| §20.6 | Turn queuing integration |

---

## Prerequisites

- Requires Sprint 04 deliverables to be completed before this sprint begins.

---

## Deliverables

### D1: Full Message Model
- `app/sessions/models.py` (upgrade) — complete `Message` with all fields from §3.4:
  - `content_blocks: list[ContentBlock]`, `tool_calls: list[ToolCallRecord]`, `tool_call_id`
  - `file_ids`, `parent_id`, `active` (branching), `provenance` enum
  - `compressed`, `compressed_source_ids`, `turn_cost_id`
  - `feedback_rating`, `feedback_note`, `feedback_at`
  - `model`, `input_tokens`, `output_tokens`
- Migration: update `messages` table schema with all columns + indexes
- `ContentBlock`, `ToolCallRecord`, `MessageFeedback` models

**Acceptance**: Full message schema in DB. All fields serialize/deserialize correctly.

### D2: Turn Loop
- `app/agent/turn_loop.py` — core execution cycle:
  1. Gateway routes `inbound.message` to session's agent
  2. Prompt assembly (from S04)
  3. Provider streaming call with tool definitions
  4. Stream tokens → `agent.run.stream` gateway events → WS → frontend
  5. Tool call detection → parse → policy check → approval gate → execute → loop
  6. Final response: persist + `agent.run.complete` event
  7. Post-turn: extraction check (stub), budget tracker (stub), audit event
- Max tool rounds: 25 per turn (configurable)
- Integration with turn queue (S02)

**Acceptance**: User sends message → sees streaming response from LLM. Tool calls execute and results loop back to LLM.

### D3: Streaming UI
- Frontend: real-time token display as `agent.run.stream` events arrive
- Streaming response component with cursor animation
- Tool call display: show tool name, args, result inline in chat
- Turn progress indicator (thinking, calling tool X, responding)

**Acceptance**: Response streams token-by-token in the UI. Tool calls shown clearly.

### D4: Tool Framework
- `app/tools/registry.py` — tool registry, `@tool` decorator, safety classification (§11.1)
- `app/tools/executor.py` — tool execution engine, approval gates (§11.2)
- `ToolDefinition` model with name, description, parameters (JSON Schema), safety level
- Safety levels: `read_only`, `side_effect`, `destructive`, `critical`
- Parallel tool call support (`asyncio.gather` for multiple tool calls)
- Tool result model: `ToolResult`

**Acceptance**: Tools register via decorator. Executor runs tools by name. Safety levels enforced.

### D5: Approval Flow (Initial Mechanism)
- Tool executor detects `destructive` or `critical` safety level → emits `approval_request` gateway event
- Frontend: approval banner (approve / deny / allow-all buttons)
- Keyboard shortcuts: `Y` (approve), `N` (deny), `A` (allow-all for this turn)
- Gateway waits for user response before tool executes
- Timeout: configurable approval timeout (default: 5 minutes)
- Allow-all scope: applies to the **current turn only** — resets on next turn
- **Note**: Sprint 07 extends this with policy-driven approval triggering (`SessionPolicy.require_confirmation` overrides safety-level defaults), persistent per-session batch-allow, and audit logging of all approval decisions.

**Acceptance**: Destructive tool → approval banner shown → user approves → tool executes. Allow-all works for current turn. Timeout auto-denies.

### D6: Branching & Regeneration
- `app/sessions/branching.py` — edit-and-resubmit, regenerate logic (§3.5)
- `POST /api/sessions/{id}/regenerate` — mark old messages `active=False`, re-run turn
- `POST /api/sessions/{id}/edit` — mark old chain inactive, insert edited message, new turn
- Frontend: regenerate button on assistant messages, edit button on user messages
- Deactivated messages hidden by default; "show previous versions" toggle

**Acceptance**: User regenerates response → new response appears, old hidden. Edit-and-resubmit works.

### D7: Message Feedback
- `PATCH /api/messages/{id}/feedback` — set rating (up/down) + optional note
- Frontend: thumbs up/down buttons on assistant messages
- Feedback stored on message row

**Acceptance**: User clicks thumbs up → feedback saved. Down → optional note input.

---

## Tasks

### Backend — Message Model
- [ ] Upgrade Message model with full field set (§3.4)
- [ ] Create ContentBlock, ToolCallRecord, MessageFeedback models
- [ ] Migration: update messages table schema
- [ ] Update message CRUD to handle all fields

### Backend — Turn Loop
- [ ] Create `app/agent/turn_loop.py` — main execution cycle
- [ ] Integrate with prompt assembly pipeline (S04)
- [ ] Implement stream processing: text_delta → gateway event forwarding
- [ ] Implement tool call detection from stream events
- [ ] Implement tool call → policy check → approval gate → execute → loop
- [ ] Integrate with turn queue (mutual exclusion, one turn at a time)
- [ ] Add max_tool_rounds cap (default 25)
- [ ] Post-turn hooks: extraction stub, budget stub, audit event

### Backend — Tool Framework
- [ ] Create `app/tools/registry.py` — tool registry, @tool decorator
- [ ] Create `app/tools/executor.py` — execution engine, approval gates
- [ ] Implement parallel tool call execution (asyncio.gather)
- [ ] Implement approval_request/approval_response gateway events

### Backend — Branching
- [ ] Create `app/sessions/branching.py` — regenerate, edit-and-resubmit
- [ ] Add `/regenerate` and `/edit` endpoints
- [ ] Update prompt assembly to filter by `active=True`

### Backend — Feedback
- [ ] Add `PATCH /api/messages/{id}/feedback` endpoint
- [ ] Store feedback on message row

### Frontend
- [ ] Implement streaming response display (token-by-token rendering)
- [ ] Create tool call display component (name, args, result)
- [ ] Create approval banner with approve/deny/allow-all buttons
- [ ] Wire approval keyboard shortcuts (Y/N/A)
- [ ] Add regenerate button on assistant messages
- [ ] Add edit button on user messages with inline editor
- [ ] Add "show previous versions" toggle
- [ ] Add thumbs up/down feedback buttons
- [ ] Turn progress indicator (thinking → tool calling → responding)

### Tests
- [ ] `tests/integration/test_turn_loop.py` — full turn execution with mock provider
- [ ] `tests/unit/test_tool_registry.py` — registration, safety classification
- [ ] `tests/unit/test_tool_executor.py` — execution, parallel calls
- [ ] `tests/unit/test_branching.py` — regenerate, edit logic
- [ ] `tests/integration/test_approval_flow.py` — approval request/response cycle

---

## Testing Requirements

- Turn loop: message → streaming response → persistence (with mock provider).
- Tool calls: single tool, parallel tools, max rounds cap.
- Approval: tool requiring confirmation → wait → approve → execute.
- Branching: regenerate marks old inactive, creates new. Edit works same way.

---

## Definition of Done

- [ ] User chats with LLM — streaming response visible in real-time
- [ ] Agent can call tools; tool calls shown in chat with results
- [ ] Approval banner appears for destructive tools; Y/N/A work
- [ ] Regenerate produces new response; edit-and-resubmit works
- [ ] Feedback thumbs up/down saved on messages
- [ ] All tests pass
- [ ] Max 25 tool rounds enforced per turn

---

## Risks & Notes

- **This is the most complex sprint**: the turn loop is the critical path. Allocate extra review time.
- **Mock provider essential**: `MockProvider` with scripted responses (including tool call simulation) is critical for testing. Build it first.
- **Streaming UI complexity**: handling interleaved text_delta and tool_call events requires careful state management in the frontend.
