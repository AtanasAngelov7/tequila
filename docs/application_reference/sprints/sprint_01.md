# Sprint 01 — App Skeleton, Gateway & Data Layer

**Phase**: 1 – Foundation
**Duration**: 2 weeks
**Status**: ✅ Done
**Build Sequence Items**: BS-1, BS-2, BS-3

> **📖 Spec reference**: For full design context, data models, and acceptance details, consult [tequila_v2_specification.md](../tequila_v2_specification.md) at the §-sections listed in the Spec References table below.

---

## Goal

Stand up the core backend: FastAPI application, SQLite database with Alembic migrations, the gateway event router, configuration system, and structured logging. By sprint end, the server starts, routes events internally, persists config, and writes structured logs.

---

## Spec References

| Section | Topic |
|---------|-------|
| §2.1–2.3 | Gateway architecture, event model, routing |
| §12.4 | Structured JSON logging |
| §14.1 | SQLite tables (core schema) |
| §14.2 | Filesystem layout |
| §14.3 | Alembic migrations |
| §14.4 | Configuration table + config model |
| §20.1 | SQLite WAL mode, pragmas |
| §20.2 | Write transaction helper (`write_transaction`) |
| §28 | Project file structure |
| §28.4 | Runtime path resolution (`app/paths.py`) |

---

## Prerequisites

- None (this is the first sprint).
- Dev environment: Python 3.12, Node.js (for later sprints), `.venv` set up.

---

## Deliverables

### D1: FastAPI Application Shell
- `main.py` entry point with `uvicorn` startup
- `app/api/app.py` — FastAPI app factory with lifespan (startup/shutdown hooks)
- `app/api/deps.py` — dependency injection stubs (DB connection, gateway)
- Static file mount for `frontend/dist/` (placeholder)
- CORS middleware configured for local development

**Acceptance**: `python main.py` starts the server on `http://localhost:8000`, returns 200 on `/api/health`.

### D2: Runtime Path Resolution
- `app/paths.py` — `is_frozen()`, `app_dir()`, `data_dir()`, `frontend_dir()`, `custom_plugins_dir()`, `alembic_dir()`
- Correct behavior in dev mode (repo-relative paths)
- Frozen-mode paths implemented but not yet testable (no packaging this sprint)

**Acceptance**: Unit tests verify dev-mode paths resolve correctly.

### D3: SQLite Database + Alembic
- `app/db/connection.py` — async SQLite connection factory, WAL mode, `busy_timeout`, `foreign_keys`
- `app/db/schema.py` — shared utilities
- Alembic configured (`alembic.ini`, `alembic/env.py`)
- Baseline migration (`0001_baseline.py`) creating core tables: `sessions`, `messages`, `config`
- WAL pragmas applied at startup (§20.1)

**Acceptance**: `alembic upgrade head` creates the database. Tables verified via SQL.

### D4: Configuration System
- `app/config.py` — `AppConfig` loader
- `config` SQLite table with namespaced keys, types, defaults, hot-reload flags (§14.4)
- `GET /api/config` and `PATCH /api/config` endpoints
- Config namespace resolution: `session.*`, `agent.*`, `web.*`, etc.

**Acceptance**: Config values can be read/written via API. Defaults populated on first run.

### D5: Gateway Event Router
- `app/gateway/events.py` — `GatewayEvent` Pydantic model + all event type definitions
- `app/gateway/router.py` — in-process async event dispatch, event sequencing
- `app/sessions/policy.py` — `SessionPolicy` model + presets (ADMIN, STANDARD, WORKER, CODE_RUNNER, READ_ONLY, CHAT_ONLY per §2.7)
- Event routing: events dispatched to registered handlers by type

**Acceptance**: Unit tests demonstrate event dispatch (emit → handler receives). Policy model validates correctly.

### D6: Structured Logging
- `app/audit/logger.py` — JSON structured logging with per-module levels
- Log rotation configuration
- `GET /api/logs` endpoint (query structured logs)
- Startup logging: version, config summary, DB path

**Acceptance**: Server startup produces structured JSON log entries. Log level configurable via config.

### D7: Audit Log Foundation
- `app/audit/log.py` — audit event recording
- `audit_log` database table
- `GET /api/audit` endpoint (basic query)

**Acceptance**: Audit events can be written and queried via API.

---

## Tasks

### Backend Core
- [x] Create `app/paths.py` with path resolution functions
- [x] Create `app/constants.py` with version string and app-wide constants
- [x] Create `app/exceptions.py` with base exception hierarchy (`TequilaError`)
- [x] Create `app/db/connection.py` with async SQLite connection, WAL pragmas
- [x] Create `app/db/schema.py` with shared DB utilities
- [x] Configure Alembic: `alembic.ini`, `alembic/env.py`
- [x] Write baseline migration: `sessions`, `messages`, `config`, `audit_log` tables
- [x] Create `app/config.py` — config loader, defaults, namespace resolution

### Gateway
- [x] Create `app/gateway/events.py` — GatewayEvent model + event type catalog
- [x] Create `app/gateway/router.py` — event dispatch engine
- [x] Create `app/sessions/policy.py` — SessionPolicy model + presets (§2.7)
- [x] Wire gateway to app lifespan (start/stop)

### API
- [x] Create `app/api/app.py` — FastAPI factory, lifespan, middleware
- [x] Create `app/api/deps.py` — dependency injection
- [x] Create `app/api/routers/system.py` — `/api/health`, `/api/status` (stub), `/api/config`
- [x] Create `app/api/routers/logs.py` — `/api/logs`, `/api/audit`
- [x] Create `main.py` entry point

### Logging & Audit
- [x] Create `app/audit/logger.py` — structured JSON logging
- [x] Create `app/audit/log.py` — audit event persistence
- [x] Configure log rotation

### Tests
- [x] `tests/unit/test_paths.py` — path resolution (dev mode)
- [x] `tests/unit/test_gateway_router.py` — event dispatch, handler registration
- [x] `tests/unit/test_session_policy.py` — policy presets, validation
- [x] `tests/unit/test_config.py` — config read/write, defaults, namespaces
- [x] `tests/integration/test_api_system.py` — health endpoint, config CRUD

---

## Testing Requirements

- All unit tests pass.
- Integration tests verify API endpoints return correct responses.
- Server starts and responds to health check.
- Database created via migration with expected schema.

---

## Definition of Done

- [x] `python main.py` starts server, `/api/health` returns `200 OK`
- [x] Alembic migration creates all tables
- [x] Config CRUD works via `/api/config`
- [x] Gateway dispatches events to registered handlers (unit test)
- [x] Structured JSON logs written on startup
- [x] All tests pass, no type errors (`pyright`)
- [x] Code committed with proper module structure matching §28

---

## Risks & Notes

- **SQLite async**: Use `aiosqlite` for async access. Single-writer lock + `write_transaction` helper needed (§20.1–20.2).
- **Config hot-reload**: Mark which config keys are hot-reloadable vs restart-required. Implement the flag now; actual hot-reload wiring comes when subsystems consume config.
- **Event type catalog**: Define all ~23 event types in the model now even though most handlers aren't implemented yet. This prevents refactoring later.

---

