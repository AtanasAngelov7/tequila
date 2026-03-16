# Sprint 08 — Multi-Agent: Session Tools, Sub-Agents & Workflows

**Phase**: 3 – Multi-Agent (**Phase Gate Sprint**)
**Duration**: 2 weeks
**Status**: ✅ Done
**Build Sequence Items**: BS-19, BS-20, BS-21, BS-22

> **📖 Spec reference**: For full design context, data models, and acceptance details, consult [tequila_v2_specification.md](../tequila_v2_specification.md) at the §-sections listed in the Spec References table below.

---

## Goal

Enable multi-agent collaboration: agents can list, read, and write to other sessions, spawn sub-agents with scoped policies, and execute structured workflows (pipeline and parallel modes). By sprint end, the main agent can delegate tasks to specialised sub-agents and orchestrate multi-step workflows.

---

## Spec References

| Section | Topic |
|---------|-------|
| §3.3 | Session tools (sessions_list, sessions_history, sessions_send, sessions_spawn) |
| §10.1 | Workflow schema (pipeline mode) |
| §10.2 | Workflow schema (parallel mode) |
| §10.3 | Workflow API |
| §20.7 | Concurrent sub-agents (independent turn loops, max concurrency) |

---

## Prerequisites

- Requires Sprint 07 deliverables and the Phase 2 gate to be completed before this sprint begins.

---

## Deliverables

### D1: Session Tools
- `app/tools/builtin/sessions.py` — tools for cross-session interaction:
  - `sessions_list(filter?)` → list of accessible sessions with titles, states, agent names
  - `sessions_history(session_id, limit?)` → recent messages from another session
  - `sessions_send(session_id, message)` → inject a message into another session (triggers that session's agent)
  - `sessions_spawn(agent_config, initial_message?, policy?)` → create new session with specified agent, return session_id
- Policy scoping: spawned sub-agents inherit parent's policy restrictions + any additional restrictions specified
- Safety: `sessions_list`, `sessions_history` = `read_only`; `sessions_send`, `sessions_spawn` = `side_effect`

**Acceptance**: Agent lists sessions, reads history, sends messages to other sessions, spawns sub-agents. Policy restrictions inherited.

### D2: Sub-Agent Spawning
- `app/agent/sub_agent.py` — sub-agent management:
  - Spawn creates new session + agent with scoped config
  - Parent can monitor sub-agent progress via session tools
  - Sub-agent results flow back to parent via `sessions_history`
  - Auto-cleanup: sub-agent sessions archived after completion (configurable)
  - Concurrency limit: max active sub-agents per parent (default 5)

**Acceptance**: Main agent spawns sub-agent for task → sub-agent executes → main agent retrieves results.

### D3: Workflow Runtime
- `app/workflows/runtime.py` — workflow execution engine:
  - **Pipeline mode**: steps execute sequentially, output of step N becomes input to step N+1
  - **Parallel mode**: steps execute concurrently, results gathered when all complete
  - Step definition: `{agent_id, prompt_template, timeout_s, retry?}`
  - Workflow state machine: `pending → running → step_N → completed | failed | cancelled`
  - Step-level error handling: retry, skip, abort-workflow options
  - Progress tracking: current step, elapsed time, step results

**Acceptance**: Pipeline workflow executes steps in sequence. Parallel workflow runs steps concurrently. Failure handling works.

### D4: Workflow Schema & API
- `app/workflows/models.py` — Workflow, WorkflowStep, WorkflowRun models
- `app/workflows/api.py`:
  - `POST /api/workflows` — create workflow definition
  - `GET /api/workflows` — list workflows
  - `GET /api/workflows/{id}` — workflow detail + run history
  - `POST /api/workflows/{id}/run` — trigger workflow execution
  - `GET /api/workflows/{id}/runs/{run_id}` — run status + step results
  - `POST /api/workflows/{id}/runs/{run_id}/cancel` — cancel running workflow
- Workflow definitions stored in DB; reusable

**Acceptance**: Full CRUD for workflow definitions. Trigger run → monitor progress → see results.

### D5: Workflow UI
- Frontend workflow components:
  - Workflow list view (sidebar or dedicated page)
  - Workflow builder: visual step sequencer (add steps, set mode, configure agents)
  - Run monitor: live step progress, step results, timing
  - Run history with past results

**Acceptance**: User creates workflow via UI, triggers run, watches progress, sees results.

---

## Tasks

### Backend — Session Tools
- [x] Create `app/tools/builtin/sessions.py` with all 4 tools
- [x] Implement policy scoping for spawned sub-agents
- [x] Register tools with correct safety classifications
- [ ] Session access control: check permissions before cross-session access *(not yet enforced)*

### Backend — Sub-Agent
- [x] Create `app/agent/sub_agent.py`
- [x] Implement spawn with policy inheritance
- [x] Auto-cleanup for completed sub-agent sessions
- [x] Concurrency limit enforcement (max 3 active sub-agents per parent)

### Backend — Workflow Runtime
- [x] Create `app/workflows/runtime.py` — execution engine
- [x] Implement pipeline mode (sequential execution)
- [x] Implement parallel mode (asyncio.gather)
- [x] Workflow state machine with transitions
- [x] Step-level error handling (retry, abort)
- [x] Progress tracking via DB run status

### Backend — Workflow API
- [x] Create `app/workflows/models.py` — Workflow, WorkflowStep, WorkflowRun
- [x] Create `app/workflows/api.py` — full CRUD + run endpoints
- [x] DB migration for workflow tables

### Frontend — Workflow UI
- [ ] Workflow list view *(deferred)*
- [ ] Workflow builder (step sequencer, mode selector, agent picker) *(deferred)*
- [ ] Run monitor (live progress, step results) *(deferred)*
- [ ] Run history view *(deferred)*

### Tests
- [x] `tests/unit/test_session_tools.py` — list, history, send, spawn
- [x] `tests/unit/test_sub_agent.py` — spawn, policy inheritance, cleanup
- [x] `tests/unit/test_workflow_runtime.py` — pipeline, parallel, error handling
- [x] `tests/integration/test_workflow_e2e.py` — create workflow → run → results
- [x] `tests/integration/test_multi_agent.py` — parent spawns sub-agent, delegates, retrieves results

---

## Testing Requirements

- Session tools: agent lists sessions, reads history, sends message (triggers response), spawns sub-agent.
- Sub-agent: spawned agent executes task, parent retrieves results, cleanup happens.
- Workflow pipeline: 3-step sequential workflow completes in order.
- Workflow parallel: 3-step parallel workflow completes concurrently.
- Error: step failure → retry → succeed. Unrecoverable → abort.

---

## Definition of Done

- [x] Session tools operational: list, history, send, spawn
- [x] Sub-agent spawning works with policy inheritance
- [x] Workflow pipeline mode executes steps sequentially
- [x] Workflow parallel mode executes steps concurrently
- [x] Workflow API: full CRUD + run/cancel/status
- [ ] Workflow UI: build, run, monitor workflows *(deferred — backend-only sprint)*
- [x] All tests pass
- [x] **Phase 3 gate (backend)**: Multi-agent collaboration and workflow orchestration operational

---

## Risks & Notes

- **Cross-session security**: Ensure agents can only access sessions they own or are explicitly granted access to. Policy scoping is critical.
- **Deadlocks**: Prevent circular session_send calls (A → B → A). Implement depth limit or cycle detection.
- **Workflow complexity**: Keep the initial builder simple (linear pipeline + parallel fan-out). Complex DAG orchestration is out of scope for now.
- **Sub-agent cost**: Each sub-agent turn costs LLM tokens. Budget tracking should account for sub-agent costs attributed to parent.
