# Tequila v2 — Implementation Agent Prompt

You are implementing **Tequila v2**, a local-first personal AI agent platform. All design decisions are final. Your job is to implement the codebase from scratch, one sprint at a time, following the documentation exactly.

### Before writing a single line of code, read these files in full:

1. `docs/README.md` — project overview and documentation map
2. `docs/architecture.md` — system architecture and data flow
3. `docs/module-map.md` — all planned modules, classes, and routes
4. `docs/application_reference/tequila_v2_specification.md` — the full design specification (6700+ lines). This is the authoritative source for all data models, SQL schemas, API contracts, edge-case handling, and acceptance criteria.
5. `docs/application_reference/sprints/README.md` — sprint plan, implementation workflow (steps 1–11), coding style, naming conventions, async patterns, SQLite rules, frontend data-flow rules, and the anti-duplication policy. **Read this in full before you write anything.**

### How to work

- Implement **one sprint at a time**. Do not start a sprint until all prerequisites are met.
- The current sprint is **Sprint 01** (`docs/application_reference/sprints/sprint_01.md`). Start there.
- For each sprint, follow the 11-step workflow in `docs/application_reference/sprints/README.md` exactly — do not skip or reorder steps.
- Sprint files say **what** to build and in **what order**. The specification says **how** it should work. Always read both.
- After completing a sprint, update the sprint file (mark DoD checklist), the README sprint table, and `docs/README.md` status — then stop and report completion before starting the next sprint.

### Key rules (enforced throughout)

- **Never duplicate code across sprints.** If a file already exists from a prior sprint, extend it — do not create a parallel implementation. Check before creating.
- **Follow the 4-layer architecture**: `routes → service → repository → DB`. No SQL in route handlers. No imports between layers that skip a level.
- **Python 3.12, async everywhere.** Start every Python file with `from __future__ import annotations`. No `print()` — use `logger`.
- **All data models are Pydantic v2 `BaseModel`.** No dataclasses for structured data. Every field has a docstring.
- **Tests are written alongside implementation** — a sprint is not done until its tests pass. Backend: `pytest tests/ -v`. Frontend: `npm test`.
- **Update `docs/module-map.md` and `docs/architecture.md`** after every sprint to reflect new modules and routes.

### Workspace state

- No source code exists yet. Only `docs/`, `.venv/`, `.git/` are present.
- The `.venv` is already created at `.venv/`. Use it for all Python commands.
- Target OS: Windows. Use PowerShell for terminal commands.

Start by reading the five documents listed above, then begin Sprint 01.
