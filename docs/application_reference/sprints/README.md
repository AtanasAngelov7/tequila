# Tequila v2 — Sprint Plan

**Created**: March 13, 2026
**Updated**: March 15, 2026
**Source**: [tequila_v2_specification.md](../tequila_v2_specification.md) §18 (Build Sequencing)
**Sprint cadence**: 2-week sprints
**Total sprints**: 17 (34 weeks)
**Phase gate rule**: each phase must be demonstrably working before the next phase begins.

---

## Implementation Status

| Status | Meaning |
|--------|---------|
| ✅ Done | Sprint complete — all tests passing, deliverables verified |
| 🔧 In Progress | Sprint actively being implemented |
| ⬜ Not Started | Sprint not yet begun — prerequisites may not be met |

---

## Sprint Overview

| Sprint | Phase | Focus | Status | Spec Sections |
|--------|-------|-------|--------|---------------|
| **[S01](sprint_01.md)** | 1 – Foundation | App skeleton, gateway, config, DB | ✅ Done | §2.1–2.3, §12.4, §14.1–14.4, §20.1–20.2, §28, §28.4 |
| **[S02](sprint_02.md)** | 1 – Foundation | Sessions, WebSocket, React shell | ✅ Done | §2.4–2.7, §3.1–3.2, §3.7, §9.1, §9.3–9.4, §13.2, §20.3–20.4, §20.6 |
| **[S03](sprint_03.md)** | 1 – Foundation | Setup wizard, health, session UX | ✅ Done | §3.2, §9.5, §13.3, §15.1–15.2 |
| **[S04](sprint_04.md)** | 2 – Agent Core | Agent model, providers, prompt assembly | ✅ Done | §4.1–4.3a, §4.5.8, §4.6–4.6c, §4.7 |
| **[S05](sprint_05.md)** | 2 – Agent Core | Turn loop, message model, tool framework | ✅ Done | §3.4–3.6, §4.3, §4.6a, §11.1–11.2, §20.6 |
| **[S06](sprint_06.md)** | 2 – Agent Core | Core tools (filesystem, web, vision) | ✅ Done | §16.1–16.3, §16.7, §17.1–17.2, §17.4, §17.6 |
| **[S07](sprint_07.md)** | 2 – Agent Core | Context management, policies, approvals | ✅ Done | §4.3a, §4.7, §11.2, §19.1–19.3, §20.3c |
| **[S08](sprint_08.md)** | 3 – Multi-Agent | Session tools, sub-agents, workflows | ✅ Done | §3.3, §10.1–10.3, §20.7 |
| **[S09](sprint_09.md)** | 4 – Memory (I) | Vault, embeddings, memory data model | ✅ Done | §5.1–5.4, §5.10, §5.13, §20.3b |
| **[S10](sprint_10.md)** | 4 – Memory (II) | Extraction, recall, knowledge sources | ✅ Done | §5.5–5.6, §5.14, §20.5 |
| **[S11](sprint_11.md)** | 4 – Memory (III) | Memory tools, lifecycle, graph | ⬜ Not Started | §5.7–5.9, §5.11–5.12, §20.5 |
| **[S12](sprint_12.md)** | 5 – Plugins (I) | Plugin system, auth, Telegram, email | ⬜ Not Started | §6.1, §8.0–8.1, §8.6–8.9, §20.4 |
| **[S13](sprint_13.md)** | 5 – Plugins (II) | Documents, browser, MCP, scheduler | ⬜ Not Started | §7.1–7.3, §8.0, §8.6–8.7, §17.1, §17.3, §17.5–17.6, §21.4, §20.8 |
| **[S14a](sprint_14.md)** | 6 – Polish (I) | Skills (3-level), soul editor | ⬜ Not Started | §4.5.0–4.5.8, §4.1a |
| **[S14b](sprint_14b.md)** | 6 – Polish (I) | Notifications, budget, audit, backup, export | ⬜ Not Started | §6.2, §12.1–12.3, §13.4, §23.1, §24.1–24.5, §26.1–26.6 |
| **[S15](sprint_15.md)** | 6 – Polish (II) | Full UI, file cleanup, packaging | ⬜ Not Started | §9.1–9.2b, §21.6–21.7, §29.1–29.5 |
| **[S16](sprint_16.md)** | 7 – Future | Image gen, additional connectors, auto-update | ⬜ Not Started | §8.6 (future), §29.5 |

**Progress**: 9 / 17 sprints complete — Phase 1 (S01–S03) ✅, Phase 2 (S04–S07) ✅, Phase 3 (S08) ✅, and Phase 4 Sprint 09 ✅ complete.

---

## Phase → Sprint Mapping

```
Phase 1: Foundation     → S01 ✅, S02 ✅, S03 ✅      (6 weeks) ← PHASE 1 COMPLETE
Phase 2: Agent Core     → S04 ✅, S05 ✅, S06 ✅, S07 ✅  (8 weeks) ← PHASE 2 COMPLETE
Phase 3: Multi-Agent    → S08 ✅                      (2 weeks) ← PHASE 3 COMPLETE
Phase 4: Memory         → S09 ✅, S10 ✅, S11 ⬜      (6 weeks)
Phase 5: Plugins        → S12 ⬜, S13 ⬜              (4 weeks)
Phase 6: Polish         → S14a ⬜, S14b ⬜, S15 ⬜    (6 weeks)
Phase 7: Future         → S16 ⬜                     (2 weeks, open-ended)
                          ─────────────────
                          Total: 34 weeks
```

---

## How to Read Sprint Files

Each sprint file (`sprint_XX.md`) contains:

1. **Goal** — one-sentence sprint objective
2. **Spec References** — which specification sections are implemented
3. **Build Sequence Items** — which §18 items are covered
4. **Prerequisites** — what must be complete before this sprint starts
5. **Deliverables** — concrete outputs with acceptance criteria
6. **Tasks** — detailed breakdown of implementation work
7. **Testing Requirements** — what tests must pass at sprint end
8. **Definition of Done** — checklist that gates sprint completion
9. **Risks & Notes** — known challenges and design decisions to resolve

---

## Implementation Guidance

> **📖 Always reference the specification.** Each sprint lists the spec sections it implements. During implementation, consult [tequila_v2_specification.md](../tequila_v2_specification.md) for the full design context — data models, SQL schemas, API contracts, edge-case handling, and acceptance criteria live there, not in the sprint files. The sprint files describe *what* to build and in *what order*; the specification describes *how* it should work in detail.

> **⏱ Sprint duration is flexible.** Sprints may extend beyond 2 weeks as needed to achieve full quality. The "2-week" cadence is a planning guideline, not a hard constraint. Do not rush, cut scope, or defer deliverables to meet a time target. Complete every item in the Definition of Done before moving to the next sprint.

---

## How to Implement a Sprint — Agent Workflow

Follow this sequence for every sprint. Do not skip steps.

1. **Read the sprint file in full.** Note the Goal, Deliverables, Tasks, and Definition of Done before writing any code.
2. **Read every referenced spec section.** Sprint files say *what* to build; the specification says *how*. SQL schemas, field-level rules, edge cases, and acceptance criteria live in the spec, not in the sprint file.
3. **Audit the existing codebase** for any files you will touch or that interact with what you're building. Read them before writing any code — do not guess at existing interfaces.
4. **Write Alembic migrations first** (if the sprint adds or alters schema). Migrations must run cleanly on a fresh database and on top of the previous migration.
5. **Implement backend in this order**: database helpers → domain models (Pydantic) → service/repository layer → API routes → register the router in `app/api/app.py`.
6. **Implement frontend** (if the sprint includes UI work): create or extend the appropriate component under `frontend/src/` — pages in `src/pages/`, feature components in `src/components/<feature>/`, Zustand stores in `src/stores/`, TanStack Query hooks in `src/hooks/`, API client functions in `src/api/`. Wire routing in `src/App.tsx` if a new page is added. All data access must go through TanStack Query hooks or Zustand stores — never call `fetch()` or `ws.send()` directly in components.
7. **Write tests alongside implementation.** Backend tests go in `tests/`. Frontend tests go in `frontend/__tests__/`. Do not defer tests.
8. **Run both test suites before marking a sprint done:**
   - Backend: `cd tequila && .venv\Scripts\python.exe -m pytest tests/ -v --tb=short`
   - Frontend: `cd tequila/frontend && npm test` (Vitest)
9. **Update `docs/module-map.md` and `docs/architecture.md`** in the implementation repo — add an entry for every new module, class, or route introduced in the sprint. If you modified an existing module's public interface, update its entry. If the sprint introduces new packages, changes the startup sequence, or alters the data flow, update `docs/architecture.md` accordingly. Both documents must stay accurate; a stale map is actively misleading.
10. **Update the sprint file** — mark the Definition of Done checklist and set status to ✅ Done.
11. **Update progress trackers** — mark the sprint as ✅ Done in this file's Sprint Overview table and Phase → Sprint Mapping, update the progress counter, and update the Implementation Status table in `docs/README.md`.

---

## Coding Style & Practices

These rules apply to every file written or modified during a sprint. Follow them strictly — consistency matters more than personal preference.

### Naming conventions

| Context | Convention | Example |
|---------|-----------|---------|
| Python modules & packages | `snake_case` | `session_policy.py` |
| Python functions, variables | `snake_case` | `get_write_db()` |
| Python classes | `PascalCase` | `SessionPolicy` |
| Python constants | `UPPER_SNAKE` | `APP_VERSION` |
| React component files | `PascalCase.tsx` | `ChatPanel.tsx` |
| React hook files | `camelCase.ts` | `useSessionList.ts` |
| Zustand store files | `camelCase.ts` | `useUiStore.ts` |
| API client files | `kebab-case.ts` | `sessions-api.ts` |
| React component names | `PascalCase` | `ChatPanel`, `AgentCard` |
| React custom hooks | `use` + `PascalCase` | `useSessionList()` |
| Zustand store actions | `camelCase` | `setActiveSession()` |
| TypeScript interfaces/types | `PascalCase` | `SessionRecord`, `AgentConfig` |
| SQL tables & columns | `snake_case` | `session_key`, `created_at` |
| API URL paths | `kebab-case` | `/api/session-messages` |
| API JSON fields | `snake_case` | `session_key`, `max_tokens` |

### Python version & baseline imports

- **Minimum Python version is 3.12.** Use Python 3.10+ syntax freely: `X | None` unions, `match`/`case`, built-in `list[str]` / `dict[str, Any]` generics.
- Every Python file begins with `from __future__ import annotations` (enables forward references without quoting).
- Import order: stdlib → third-party → local (`app.*`). Keep `from __future__` as the very first import.

### Module docstrings

Every module must have a top-level docstring. It should:
- State what the module is and which spec section it implements, e.g. `"""Session policy model for Tequila v2 (§2.7)."""`
- Briefly explain the key design decisions or patterns used.
- Be written before any imports (i.e., truly the first token in the file).

### Type annotations

- Annotate every function signature (arguments + return type). No unannotated public functions.
- Use `X | None` instead of `Optional[X]`. Never import `Optional` from `typing`.
- Use `Any` from `typing` only when genuinely needed; prefer concrete types.
- Use `Literal["a", "b"]` for constrained string values.

### Pydantic v2

- All data models extend `pydantic.BaseModel`. Do not use dataclasses for structured data.
- Use `Field(default_factory=...)` for mutable defaults (lists, dicts, lambdas).
- Follow each field definition with a triple-quoted docstring explaining its meaning and valid values.
- Use `["*"]` as the sentinel meaning "all allowed" for list fields that gate access (e.g., `allowed_tools`, `allowed_channels`). An empty list `[]` means "nothing allowed". Never use `None` as a sentinel for these.
- Name `extra` fields as `extra: dict[str, Any] = Field(default_factory=dict)` for forward-compatible extension.

### Section dividers

Use the following format for visual section separators inside a module (80-char total width):

```python
# ── Section Name ─────────────────────────────────────────────────────────────
```

Use them consistently to group: model definitions, helper functions, route handlers, constants, preset values, etc. This makes large files scannable at a glance.

### Logging

- Declare `logger = logging.getLogger(__name__)` at module level, immediately after imports.
- **Never use `print()` for diagnostic output.** Use `logger.debug/info/warning/error`.
- Log with context: `logger.warning("write failed", extra={"session": key})` rather than f-string interpolation in the message.

### Async patterns

- All I/O is `async`. Blocking calls (file reads, subprocess, network) must run in an executor or use an async library.
- Use `@asynccontextmanager` + `AsyncGenerator[T, None]` for resource managers (see `app.db.connection`).
- Use `asyncio.Lock` (one per resource path, keyed dict pattern) to prevent concurrent write collisions within the same process, not `threading.Lock`.
- WAL writes: always wrap mutations in `write_transaction(conn)` — it issues `BEGIN IMMEDIATE`, commits on success, rolls back on exception.

### FastAPI conventions

- Each router module defines one `router = APIRouter(tags=["section"])`. The tag matches the feature area (e.g., `"system"`, `"sessions"`, `"memory"`).
- Route functions get their dependencies via `Depends(...)` — never instantiate services or open DB connections inside a handler body.
- Injectable dependencies live in `app.api.deps`. Add new ones there, not inline.
- Input/output shapes use Pydantic models defined in the same router file (or in `app.models` when reused across routers). Do not pass raw dicts as response bodies for structured data.
- Return `dict[str, ...]` only for simple, ad-hoc responses (health, status). Use a Pydantic model when the shape matters.

### SQLite / aiosqlite

#### Connection helpers
- Open connections through `app.db.connection` helpers (`get_db`, `get_write_db`). Never call `aiosqlite.connect()` directly except inside those helpers.
- Read queries: use `get_db()` — no lock acquired (WAL allows concurrent readers).
- Write queries: use `get_write_db()` to acquire the process-level `asyncio.Lock`, then `write_transaction(conn)` to wrap the SQL in `BEGIN IMMEDIATE`.
- Always use parameterised queries — never string-format SQL with user data.
- Schema changes go through Alembic migrations in `alembic/versions/`.

#### WAL pragmas (set once at startup — §20.1)
```sql
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
```

#### `write_transaction` pattern (§20.2)
```python
async with _write_lock:
    await db.execute("BEGIN IMMEDIATE")
    try:
        result = await fn(db)
        await db.commit()
        return result
    except BaseException:
        await db.rollback()
        raise
```
> **Critical rule**: the write lock must **never** be held across an `await` that performs network I/O (LLM call, HTTP request, WebSocket). Only actual DB `.execute()` calls belong inside the lock.

#### Atomic counter rule (§20.3)
Never read a numeric field and then write back an incremented value. Use a single atomic SQL statement:
```sql
UPDATE table SET count = count + 1 WHERE id = ?
```

#### Optimistic concurrency control — OCC (§20.4)
The tables `sessions`, `config`, `agents`, and `memory_extracts` carry a `version INTEGER` column. Always guard updates with the current version and detect conflicts:
```sql
UPDATE sessions
SET    status = 'idle', version = version + 1
WHERE  session_id = ? AND version = ?
```
If `changes() == 0` the row was modified concurrently — retry up to 3 times before raising.

#### State transition guards (§20.4c)
Use conditional `WHERE status = '<expected>'` so that illegal transitions are a no-op (not a silent data corruption):
```sql
UPDATE sessions
SET    status = 'idle', version = version + 1
WHERE  session_id = ? AND status = 'active' AND version = ?
```

#### Background task chunking (§20.5)
Long-running background tasks (extraction, indexing, cleanup) must process rows in batches of **50 per transaction** to keep lock hold-times short. Never process all rows in one write transaction.

### Custom exceptions

- Raise `app.exceptions.*` domain errors rather than generic `ValueError`/`RuntimeError`.
- FastAPI routes should let unhandled domain exceptions propagate to registered exception handlers — do not catch and swallow them in route functions.

### Testing

- Tests live in `tests/`. File name: `test_<module_or_feature>.py`.
- Use `pytest` with `asyncio_mode = "auto"` (configured in `pyproject.toml`). Mark async tests with `@pytest.mark.asyncio` or rely on auto-mode.
- Flat test functions — no test classes unless grouping is genuinely needed for shared fixtures.
- No mock drift: if you change a public interface, update every test that touches it in the same PR/sprint.
- Tests are written **alongside** the implementation, not deferred. A sprint is not done until its tests pass.
- Use `pytest-httpx` for HTTP endpoint tests; use `asgi-lifespan` to run the app with full lifespan in tests.

### File placement

| What | Where |
|------|-------|
| Domain model (Pydantic) | `app/<feature>/models.py` or inline in the main feature module if small |
| API router | `app/api/routers/<feature>.py` |
| Alembic migration | `alembic/versions/NNNN_<slug>.py` |
| Shared constants | `app/constants.py` |
| Path helpers | `app/paths.py` |
| Custom exceptions | `app/exceptions.py` |
| FastAPI dependencies | `app/api/deps.py` |
| Frontend page component | `frontend/src/pages/<PageName>.tsx` |
| Frontend feature component | `frontend/src/components/<feature>/<ComponentName>.tsx` |
| shadcn/ui primitives | `frontend/src/components/ui/` |
| TanStack Query hook | `frontend/src/hooks/use<Feature>.ts` |
| Zustand store | `frontend/src/stores/use<Name>Store.ts` |
| API client functions | `frontend/src/api/<feature>-api.ts` |
| TypeScript types/interfaces | `frontend/src/types/<feature>.ts` |
| Frontend component tests | `frontend/src/components/<feature>/<ComponentName>.test.tsx` |

### Module size and separation of concerns

Keep modules focused. A file that does many different things is harder to test, harder to refactor, and harder for an agent to reason about correctly.

**Hard limits:**
- A Python module should not exceed **~400 lines** of non-trivial code. When it does, split it.
- A React component file should not exceed **~250 lines**. If it does, extract sub-components or move logic into a custom hook.
- A custom hook (`use*.ts`) should handle one concern. If a hook manages data fetching *and* local UI state *and* a side-effect, split it.

**How to split Python modules cleanly:**
- `models.py` — Pydantic data shapes only (no DB calls, no business logic).
- `repository.py` (or `queries.py`) — all DB read/write functions; returns typed Pydantic models or plain dicts.
- `service.py` (or `<feature>.py`) — business logic; calls repository functions; raises domain exceptions.
- `app/api/routers/<feature>.py` — FastAPI route handlers only; calls service functions; translates domain exceptions to HTTP responses.

This four-layer structure means each layer has a single job:

```
routes → service → repository → DB
```

Do not skip layers (e.g., do not put SQL directly in a route handler). Do not leak layers upward (e.g., do not import a router from a service module).

**Red flags that a module needs splitting:**
- It imports from both `fastapi` and `aiosqlite` (mixing transport and storage).
- It contains both Pydantic model definitions and SQL query functions.
- It exceeds 400 lines and has more than one `# ── Section ──` divider covering different concerns.
- A new sprint touches the same file for two unrelated features.

### Avoid code duplication across sprints

Later sprints frequently extend, integrate, or build upon modules created by earlier sprints. Before creating a new file or class, **always check whether an earlier sprint already created it**. If it does, **extend** the existing module — never create a parallel implementation in a different file.

**Cross-sprint rules:**
- Sprint files explicitly state when a deliverable builds on prior work (e.g., "expand the SessionPolicy model created in Sprint 01"). Read these notes carefully.
- Before writing a new class, search the existing codebase for classes with the same or similar name. If one exists, import and extend it.
- If a sprint says "create" a file that already exists from a prior sprint, treat it as "extend" — add the new functionality to the existing file.
- When integrating an earlier sprint's module into a new context (e.g., wiring a circuit breaker into the turn loop), import the existing implementation — do not rewrite it in a new location.
- Shared utilities belong in one canonical location. If two features need the same helper, it lives in the module that introduced it first; the later feature imports it.

**Red flags for cross-sprint duplication:**
- Two files in different packages define the same class name (e.g., `RetryPolicy` in two locations).
- A new sprint's tasks say "create" a module that already exists from a prior sprint.
- Helper functions are copied between modules instead of imported from a shared location.

### What not to do

- Do not add new top-level packages outside `app/` without a spec justification.
- Do not silently swallow exceptions (`except Exception: pass`).
- Do not use `time.sleep` in async code — use `asyncio.sleep`.
- Do not commit dead code, commented-out blocks, or debug `print`s.
- Do not introduce new dependencies without updating `pyproject.toml` (Python) or `package.json` (frontend) and noting the reason in the sprint file.
- Do not put SQL queries inside route handlers or Pydantic models.
- Do not build monolith feature files that mix models, queries, business logic, and routes in one place. Prefer four focused files over one sprawling one.

---

## Frontend (React + Vite SPA)

> **Design-locked** — the library choices in §9.1 are fixed for all sprints. Do not propose alternatives.

### Stack (§9.1)

| Concern | Library | Notes |
|---------|---------|-------|
| Build tool | **Vite** | Dev server + optimised production build |
| Framework | **React** | Component model, concurrent rendering |
| Routing | **React Router v7** | Nested layouts, lazy-loaded routes |
| State management | **Zustand** | Minimal boilerplate, no Provider needed |
| Server data fetching | **TanStack Query** | Declarative caching, stale-while-revalidate, optimistic updates |
| Component primitives | **shadcn/ui** (Radix) | Copied into `src/components/ui/`, accessible WAI-ARIA |
| Styling | **Tailwind CSS v4** | Utility-first; `@theme` layer for design tokens |
| Icons | **Lucide React** | Tree-shakeable, bundled with shadcn/ui |
| Graph visualisation | **react-force-graph-2d** | Knowledge graph (§5.11) |
| Type system | **TypeScript** | Strict mode; all new files are `.tsx` / `.ts` |

### Data flow rules (mandatory — §9.2)

These rules are not stylistic preferences — they are architectural invariants:

- **Components NEVER call `fetch()` or `ws.send()` directly.**
- All REST data read/write → hooks backed by **TanStack Query** (`useQuery` / `useMutation`).
- All real-time data (streaming tokens, tool approvals, notifications) → read from **Zustand WS store**.
- All UI state (sidebar, active session/agent, theme, modal state, approval queue) → **Zustand UI store**.
- API client functions live in `src/api/` and are called only from hooks, never from components.

### Zustand stores (§9.2b)

Create one store per concern. Stores are plain function modules — no class, no Context/Provider:

| Store file | Purpose |
|------------|---------|
| `useSessionStore.ts` | Active session, session list, session search state |
| `useAgentStore.ts` | Agent list, active agent |
| `useWsStore.ts` | WS connection state, event queue, reconnection backoff |
| `useUiStore.ts` | Sidebar open/close, theme, modal state, approval queue |

Store actions mutate state synchronously; async side-effects belong in hooks, not stores.

### TanStack Query patterns (§9.2a)

- `useQuery(['sessions'])` — read; `useMutation` — write with `onSuccess: () => queryClient.invalidateQueries(['sessions'])`.
- Every write mutation that affects a list must invalidate the corresponding query key.
- Optimistic updates: use `onMutate` / `onError` rollback for low-latency interactions (e.g., sending a message, toggling a setting).
- Query keys are arrays of strings matching the REST resource path segments.

### shadcn/ui usage

- Add components with `npx shadcn-ui@latest add <component>` — they are copied into `src/components/ui/`.
- Customise components via Tailwind classes in the caller, not by editing `src/components/ui/` directly.
- Do not import `@shadcn/ui` at runtime — there is no such package; the files are local copies.

### Tailwind CSS v4

- Design tokens (colours, spacing, radii) live in the CSS `@theme` layer, not in `tailwind.config.js`.
- Theme switching: set `data-theme="dark"` or `data-theme="light"` on `<html>`. CSS custom properties swap automatically.
- Anti-flash: a small synchronous `<script>` in `<head>` reads `localStorage.tequila.theme` and sets `data-theme` before React hydrates — no visible flash on load.
- Never add inline CSS styles for theme colours — always use semantic Tailwind classes backed by CSS custom properties.

### Core UI surfaces (§9.3)

| Surface | Key components |
|---------|---------------|
| Chat interface | Message list (streaming tokens), input bar, file attach, tool approval cards |
| Agent management | Agent CRUD list, soul editor, skills panel |
| Workflow management | Workflow list, DAG editor |
| Settings | Provider auth, plugins, scheduler, web/browser/vision config tabs |
| Knowledge & memory | Vault browser, memory explorer, entity explorer, knowledge graph |
| Knowledge graph | react-force-graph-2d force-directed canvas; nodes coloured by type; edges styled by type; filters panel; 4 views (full / ego / orphan / cluster) |

### Keyboard shortcuts (§9.4)

| Shortcut | Action |
|----------|--------|
| `Ctrl+K` | Open command palette |
| `Ctrl+N` | New session |
| `Ctrl+/` | Toggle sidebar |
| `Enter` | Send message |
| `Shift+Enter` | Insert newline |
| `Y` / `N` | Approve / reject pending tool call |

### Testing

- **Vitest** for unit and integration tests; **React Testing Library** for component tests.
- Test files are co-located with the component: `ComponentName.test.tsx` next to `ComponentName.tsx`.
- Test rendered output and user interactions — not implementation details or internal state.
- Run: `cd tequila/frontend && npm test`

### What not to do (frontend)

- Do not call `fetch()` or `ws.send()` inside a component — use a TanStack Query hook or Zustand store action.
- Do not mutate Zustand state outside a store action.
- Do not edit files under `src/components/ui/` to customise appearance — override via Tailwind in the caller.
- Do not use CSS modules or `styled-components` — Tailwind utilities only.
- Do not add browser globals (`window`, `document`, `localStorage`) inside code paths that run on the server side or in tests without mocking.
- Do not use `var` — use `const` and `let` only.

---

## Backend ↔ Frontend Contract

These rules guard the boundary between Python and TypeScript.

### REST conventions (§13.1)

- **All REST endpoints** are under `/api/...` (unversioned). Clients may send an optional `X-API-Version` header; the server logs it but does not reject on mismatch.
- **URL segments** are `kebab-case`, lower-case: `/api/session-messages`, `/api/knowledge-sources`. Never camelCase in paths.
- **CRUD pattern**: `GET /api/{resource}` (list), `POST /api/{resource}` (create), `GET /api/{resource}/{id}` (read), `PATCH /api/{resource}/{id}` (partial update — not `PUT`), `DELETE /api/{resource}/{id}`.
- **Action endpoints**: `POST /api/{resource}/{id}/{action}` (e.g., `/activate`, `/deactivate`, `/test`, `/clone`, `/archive`).
- **JSON field names** are always `snake_case` on both sides. Pydantic uses `snake_case` field names; TanStack Query hooks consume them as-is.

### Key endpoints (§13.2–§13.4)

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `GET /api/health` | None | Lightweight liveness — returns `{status, uptime_s, version}` |
| `GET /api/status` | Required | Full system dashboard (`SystemStatus` model) |
| `GET /api/config` | Required | Config grouped by category |
| `PATCH /api/config` | Required | Partial update; nearly all keys are hot-reloadable (no restart) |
| `POST /api/agent/quick-turn` | Required | One-shot agent call without a persistent session |
| `GET /api/sessions/{id}/export` | Required | Export session as `?format=markdown\|json\|pdf` |

### WebSocket (§2.1, §9.2c)

- Single persistent connection at `WS /api/ws` per client.
- **Backend → Frontend** messages: `{ "event": "<ET constant>", "payload": {...}, "seq": <int> }`. Event type strings mirror the `ET.*` constants in `app/gateway/events.py`.
- **Frontend → Backend** messages: `{ "type": "<action>", ...payload }`.
- The Zustand WS store owns the connection lifecycle: exponential backoff reconnection, replaying events missed during disconnect (by `seq` tracking).
- When adding a new `ET` constant in Python, **also** handle it in the Zustand WS store `handleEvent` function and document the payload shape.

### Error responses

- All errors follow FastAPI's `{"detail": "..."}` shape (or `{"detail": [{...}]}` for validation errors).
- TanStack Query's `onError` and the Zustand WS error handler must surface `detail` to the user.

### Config hot-reload

- Most config keys (`memory.*`, `web.*`, `vision.*`, `browser.*`, `embedding.*`, etc.) take effect immediately after `PATCH /api/config` — no restart required.
- Keys that **require restart**: `server.host`, `server.port`, `server.gateway_token`. The API marks these with `requires_restart: true` in the config response.

### Router registration

- When a new API router is added, register it in `app/api/app.py`. Forgetting this is the most common cause of 404s that look like implementation bugs.

### WebSocket event types mirror `ET.*` constants

- Do not invent new WS event string literals — define them as `ET` class attributes in Python and import the same string on both sides. The TypeScript types file should mirror the Python `ET` constants.

---

## Session Keys (§3.1)

Every session has a deterministic `session_key` string. Use the correct format when creating or referencing sessions:

| Pattern | Meaning |
|---------|---------|
| `user:main` | User's primary chat session |
| `user:agent:<agent_id>` | User chatting directly with a named agent |
| `agent:<agent_id>:sub:<uuid>` | Sub-agent session spawned by a parent turn |
| `channel:telegram:<chat_id>` | Telegram conversation |
| `channel:email:<account>:<thread>` | Email thread |
| `cron:<job_id>` | Scheduler-triggered session |
| `webhook:<uuid>` | Webhook-triggered session |

Session keys are stored in `sessions.session_key` and are used throughout the codebase to look up and route to the correct conversation context. Always derive session keys by this formula — never generate ad-hoc strings.

---

## Conventions

- **Spec references** use `§` notation matching the specification (e.g., `§4.3a` = Prompt Assembly Pipeline).
- **Build sequence items** reference the numbered items in §18 (e.g., `BS-1` = item 1 in the build sequence).
- Each sprint should be independently demoable: at sprint end, the system should be runnable and show meaningful progress.
- Tests are written alongside implementation, not deferred to a later sprint.
