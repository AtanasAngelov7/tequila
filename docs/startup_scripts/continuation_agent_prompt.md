# Tequila v2 — Continuation Agent Prompt

You are continuing the implementation of **Tequila v2**, a local-first personal AI agent platform. Work is already in progress. Your job is to orient yourself, find exactly where implementation stopped, and continue from that point without duplicating or regressing any completed work.

### Step 1 — Orient yourself (do this before anything else)

Read these documents in order:

1. `docs/README.md` — check the Implementation Status table to see which sprints are done
2. `docs/application_reference/sprints/README.md` — re-read the 11-step workflow, coding style, naming conventions, async patterns, SQLite rules, frontend rules, and anti-duplication policy in full
3. `docs/architecture.md` — understand the current system architecture
4. `docs/module-map.md` — see all modules and routes that have been created so far

### Step 2 — Review past tech-debt lessons

Read `docs/application_reference/tech_debt/sprint_08_11_tech_debt.md` to understand the categories of issues that were found and cleaned up in Sprints 08–11. Apply these lessons to every sprint going forward — specifically:

- **Security**: Every new router must include `dependencies=[Depends(require_gateway_token)]`. Never interpolate user-supplied strings into SQL — always use parameterised queries or validate identifiers. Validate URLs, file paths, and connection configs with Pydantic schemas before use.
- **Correctness**: Never rebind a loop variable expecting the source list to change (`msg = dict(msg, ...)` doesn't update the list). Use `set` membership for dedup, not `in` on strings. When paginating during mutations, use cursor-based pagination (`WHERE id > ?`), not offset-based.
- **Async discipline**: Never call blocking I/O (`path.read_text()`, `model.encode()`, sync DB drivers) inside `async` functions. Always wrap in `await asyncio.to_thread(...)`.
- **Concurrency**: Protect check-then-act sequences with `asyncio.Lock`. Use OCC (`WHERE version = ?`) for concurrent writes. Thread cancellation tokens through long-running pipelines.
- **Validation**: Use `Literal[...]` for all enum-like string fields in Pydantic models. Raise on invalid input — never `except ValueError: pass`.
- **Observability**: Never write `except Exception: pass`. Always log at WARNING with `exc_info=True`. Return HTTP 503 (not empty `[]`) when a subsystem is unavailable.
- **Side effects**: Keep read methods pure. If a function needs to bump a counter or timestamp, make that a separate explicit method (e.g., `touch()`), not a hidden side effect of `get()`.

### Step 3 — Find the current sprint

- Open the sprint file for the **first sprint marked 🔧 In Progress or ⬜ Not Started** in `docs/application_reference/sprints/README.md`.
- If a sprint is 🔧 In Progress, read it fully and audit the existing codebase to determine exactly which tasks and DoD checklist items are already complete and which remain.
- If all sprints are ⬜ Not Started, begin with Sprint 01.

### Step 4 — Audit the codebase before writing anything

Before adding or changing any code:

- Read every file you will touch or that interacts with what you are building.
- Search for existing implementations of classes, functions, or modules before creating new ones — if they exist, extend them.
- Never assume a file doesn't exist. Check first.

### Step 5 — Continue implementation

- Follow the 11-step sprint workflow in `docs/application_reference/sprints/README.md` for any sprint you are working on.
- For full design context on any feature, read the spec sections listed in the sprint's **Spec References** table from `docs/application_reference/tequila_v2_specification.md`.
- After completing a sprint, update the sprint file (mark DoD checklist), the README sprint table, and `docs/README.md` status — then stop and report completion before starting the next sprint.

### Key rules (enforced throughout)

- **Never duplicate code across sprints.** If a file already exists from a prior sprint, extend it — do not create a parallel implementation. Check before creating.
- **Follow the 4-layer architecture**: `routes → service → repository → DB`. No SQL in route handlers. No imports between layers that skip a level.
- **Python 3.12, async everywhere.** Start every Python file with `from __future__ import annotations`. No `print()` — use `logger`.
- **All data models are Pydantic v2 `BaseModel`.** No dataclasses for structured data. Every field has a docstring.
- **Tests are written alongside implementation** — a sprint is not done until its tests pass. Backend: `pytest tests/ -v`. Frontend: `npm test`.
- **Update `docs/module-map.md` and `docs/architecture.md`** after every sprint to reflect new modules and routes.
- **Avoid introducing tech debt.** Review the lessons in Step 2 before writing any new code. Every new endpoint, model, and async function must comply with those guardrails.

### Workspace state

- The `.venv` is at `.venv/`. Use it for all Python commands.
- Target OS: Windows. Use PowerShell for terminal commands.
- Do not modify anything under `docs/` except to update sprint status, `docs/module-map.md`, and `docs/architecture.md` as part of sprint completion (step 9–11 of the workflow).
- Tech-debt audit history lives in `docs/application_reference/tech_debt/` for reference.
