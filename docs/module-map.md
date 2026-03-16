# Module Map

Every Python module under `app/` listed with its responsibility, key public exports, and spec reference.

> **Maintenance rule**: update this file at the end of every sprint (step 9 of the agent workflow). Add an entry for every new module, class, or route. Update existing entries when a public interface changes. A stale module map is worse than no map — keep it accurate.

---

## `app/constants.py`

**Responsibility**: App-wide string literals and numeric defaults. Zero imports from `app/`.

**Key exports:**

| Symbol | Value | Purpose |
|--------|-------|---------|
| `APP_VERSION` | `"0.1.0"` | Returned by health endpoint |
| `DB_FILENAME` | `"tequila.db"` | SQLite file name inside `data/` |
| `DEFAULT_HOST` | `"127.0.0.1"` | ServerSettings default |
| `DEFAULT_PORT` | `8000` | ServerSettings default |
| `GATEWAY_TOKEN_HEADER` | `"X-Gateway-Token"` | Auth header name |
| `MAX_BUFFERED_MESSAGES` | `10` | Turn queue depth (§20.6) |
| `MAX_CONCURRENT_SUBAGENTS` | `3` | Concurrent sub-agent cap (§20.7) |

**Spec ref**: §2.1, §20.6, §28.4

---

## `app/exceptions.py`

**Responsibility**: Domain exception hierarchy. All feature code raises subtypes of these; FastAPI exception handlers convert them to HTTP responses.

**Key exports:**

| Class | HTTP equiv | When raised |
|-------|-----------|-------------|
| `TequilaError` | 500 | Base class |
| `NotFoundError` | 404 | Missing DB row |
| `ConflictError` | 409 | Duplicate key / OCC version mismatch |
| `AccessDeniedError` | 403 | Auth / scope check failed |
| `ValidationError` | 422 | Domain-level validation (not Pydantic) |
| `ConfigKeyNotFoundError` | 404 | `ConfigStore.get()` — key absent and no default |
| `ConfigValidationError` | 422 | Config value fails type/range check |
| `GatewayTokenRequired` | 401 | Missing or wrong gateway token |
| `SessionBusyError` | 429 | Turn queue full |
| `SessionNotFoundError` | 404 | Session key not in DB |

**Rule**: Route handlers do not catch these. They propagate to the registered exception handlers in `app/api/app.py`.

**Spec ref**: §2.3, §3.7, §28

---

## `app/paths.py`

**Responsibility**: Canonical filesystem `Path` objects. All code that needs a path imports from here — never hardcodes a directory string.

**Key exports:**

| Function / constant | Returns | Notes |
|--------------------|---------|-------|
| `data_dir()` | `Path` | `./data/` (or `$TEQUILA_DATA_DIR`) |
| `db_path()` | `Path` | `data/tequila.db` |
| `vault_dir()` | `Path` | `data/vault/` |
| `uploads_dir()` | `Path` | `data/uploads/` |
| `auth_dir()` | `Path` | `data/auth/` |
| `backups_dir()` | `Path` | `data/backups/` |
| `browser_profiles_dir()` | `Path` | `data/browser_profiles/` |
| `plugins_dir()` | `Path` | `app/plugins/custom/` |
| `ensure_dirs()` | `None` | Creates all directories on startup |

**Spec ref**: §14.2, §16.1, §28

---

## `app/config.py`

**Responsibility**: Two-tier configuration system (spec §14.4).

**Tier 1 — `ServerSettings`** (Pydantic-Settings, read-only at runtime):
- Loaded from env vars prefixed `TEQUILA_` or from `.env`.
- Fields: `host`, `port`, `gateway_token`, `debug`.
- Read before the database opens; never written at runtime.

**Tier 2 — `ConfigStore`** (SQLite-backed, hot-reloadable):
- Wraps the `config` table.
- Keys are dot-namespaced strings, e.g. `"memory.extraction.trigger_interval_messages"`.
- Values are JSON-encoded; typed by `value_type` column.
- `requires_restart` keys (`server.host`, `server.port`, `server.gateway_token`) cannot be changed at runtime; all others take effect immediately.

**Key exports:**

| Symbol | Kind | Notes |
|--------|------|-------|
| `ServerSettings` | Pydantic-Settings class | Instantiated once in `create_app()` |
| `ConfigStore` | Class | `get(key)`, `set(key, value)`, `all(category)`, `reload()` |
| `get_settings()` | Function | Returns the cached `ServerSettings` singleton |

**Spec ref**: §14.4, §15, §28.4

---

## `app/db/` package

### `app/db/connection.py`

**Responsibility**: aiosqlite connection lifecycle, WAL pragma application, per-path write lock, `write_transaction` helper.

**Key exports:**

| Symbol | Kind | Notes |
|--------|------|-------|
| `open_db(path)` | `async def` | Opens new connection, applies WAL pragmas, enables `row_factory` |
| `get_db(path)` | `asynccontextmanager` → `Connection` | Read-only context manager (no lock) |
| `write_transaction(conn)` | `asynccontextmanager` | Acquires write lock, `BEGIN IMMEDIATE`, commits or rolls back |
| `get_write_db(path)` | `asynccontextmanager` → `Connection` | Combines lock acquisition + `write_transaction` |
| `startup(path)` | `async def` | Opens DB kept open for the app lifetime; runs at lifespan start |
| `shutdown()` | `async def` | Closes the application-lifetime connection |
| `get_app_db()` | `def` | Returns the already-open application connection (used in deps) |

**WAL pragmas applied on every connection:**
```sql
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
```

**Spec ref**: §20.1, §20.2

---

### `app/db/schema.py`

**Responsibility**: Low-level DB introspection and utility helpers. Used by Alembic `env.py` and runtime code. No SQLAlchemy.

**Key exports:**

| Symbol | Notes |
|--------|-------|
| `table_exists(db, name)` | Queries `sqlite_master` |
| `column_exists(db, table, col)` | Uses `PRAGMA table_info` |
| `execute_script(db, sql)` | Splits on `;`, runs statements individually (respects WAL); use instead of `db.executescript()` |
| `row_to_dict(row)` | Converts `aiosqlite.Row` → `dict` or `None` |

**Spec ref**: §14.1, §20

---

## `app/gateway/` package

The gateway is the event bus for all inbound and outbound interactions. Everything that "enters" the system (user message, webhook, scheduled trigger, channel message) becomes a `GatewayEvent` routed through `GatewayRouter`.

### `app/gateway/events.py`

**Responsibility**: Typed event envelope and the exhaustive `ET` (event type) constant table.

**Key exports:**

| Symbol | Kind | Notes |
|--------|------|-------|
| `GatewayEvent` | Pydantic model | Universal event envelope: `event_id`, `event_type`, `source`, `session_key`, `timestamp`, `payload` |
| `EventSource` | Pydantic model | `kind` + `id` of the emitter |
| `StreamPayload` | Pydantic model | Typed payload for `ET.AGENT_RUN_STREAM` events |
| `ET` | Class of string constants | All 26 event type strings (e.g. `ET.INBOUND_MESSAGE = "inbound.message"`) |
| `EVENT_TYPES` | `frozenset[str]` | All valid event type strings for validation |

**Spec ref**: §2.2, §2.3

---

### `app/gateway/router.py`

**Responsibility**: Pub/sub event bus. Handlers register for event types; `emit()` dispatches to all matching handlers.

**Key exports:**

| Symbol | Notes |
|--------|-------|
| `GatewayRouter` | Class: `on(type, handler)`, `off(type, handler)`, `emit(event)`, `emit_nowait(event)`, `seq` (monotonic counter), `start()`, `stop()` |
| `get_router()` | Returns the process-wide singleton (raises if not initialised) |
| `init_router()` | Creates and starts the singleton; called at app lifespan start |

**Design note**: `emit()` is `async` and runs handlers sequentially. `emit_nowait()` schedules emission as a background task (fire-and-forget, for contexts where `await` is not available).

**Spec ref**: §2.1, §2.2

---

### `app/gateway/buffer.py`

**Responsibility**: Per-session message buffer for turn serialisation. When a session is busy (agent is running), incoming messages are held here rather than dropped.

**Key exports:**

| Symbol | Notes |
|--------|-------|
| `SessionBuffer` | Class: `enqueue(event)` → `bool` (False if full), `dequeue()` → `GatewayEvent | None`, `is_empty()`, `size()` |
| `BufferRegistry` | Class: `get(session_key)` → `SessionBuffer`, `remove(session_key)` |
| `get_buffer_registry()` | Returns process-wide singleton |

**Capacity**: `MAX_BUFFERED_MESSAGES` (10) per session (§20.6).

**Spec ref**: §2.5, §20.6

---

> **Note:** `SessionPolicy` lives in `app/sessions/policy.py` (see Sessions package below), not in the gateway package. The gateway *enforces* policy but the model + presets are defined on the session side (§2.7, §28).

---

## `app/audit/` package

### `app/audit/logger.py`

**Responsibility**: Structured JSON logging (§12.4). Configures per-module log levels, JSON formatters, and log rotation.

**Key exports:**

| Symbol | Notes |
|--------|-------|
| `setup_logging()` | Configures structured JSON logging for the application |

**Spec ref**: §12.4

---

### `app/audit/log.py`

**Responsibility**: Write and query the `audit_log` table. Every security-relevant action (auth, config change, tool execution, file access) is recorded here.

**Key exports:**

| Symbol | Notes |
|--------|-------|
| `AuditEvent` | Pydantic model: `actor`, `action`, `resource_type`, `resource_id`, `outcome`, `detail`, `ip_address` |
| `write_audit_event(db, event)` | Inserts one row; uses `write_transaction` |
| `query_audit_log(db, ...)` | Filtered paginated query; returns `list[AuditEvent]` |

**Spec ref**: §12.1

---

## `app/api/` package

### `app/api/app.py`

**Responsibility**: FastAPI application factory. Creates the app, wires lifespan (DB startup/shutdown, router init), registers all routers, registers exception handlers.

- **Do not add route logic here.** Route functions belong in `app/api/routers/`.
- **Register every new router here** — forgetting is the most common cause of 404s.

**Key exports:**

| Symbol | Notes |
|--------|-------|
| `create_app()` | Returns the configured `FastAPI` instance |

**Spec ref**: §13, §15

---

### `app/api/deps.py`

**Responsibility**: FastAPI `Depends(...)` providers. All injectable dependencies live here — never instantiate connections or services inside route functions.

**Key exports:**

| Symbol | Returns | Notes |
|--------|---------|-------|
| `get_db_dep()` | `aiosqlite.Connection` | Read-only DB connection for a request |
| `get_write_db_dep()` | `aiosqlite.Connection` | Write DB connection (holds lock until handler returns) |
| `get_config_dep()` | `ConfigStore` | App-lifetime config store singleton |
| `require_gateway_token()` | `None` | Raises `GatewayTokenRequired` if header missing/wrong |

**Spec ref**: §2.1, §13.1

---

### `app/api/routers/system.py`

**Responsibility**: System-level endpoints — health check and full status. Updated in S03 to return uptime, provider status, DB stats, and scheduler status.

**Routes:**

| Method | Path | Auth | Response |
|--------|------|------|----------|
| `GET` | `/api/health` | None | `{status, app, version, uptime_s}` |
| `GET` | `/api/status` | Gateway token | `SystemStatus` (uptime, setup, provider, db, scheduler) |

**Spec ref**: §13.2, §13.3

---

### `app/api/routers/setup.py` *(S03)*

**Responsibility**: First-run setup wizard API. Validates provider credentials, persists config, and creates the main agent.

**Routes:**

| Method | Path | Auth | Response |
|--------|------|------|----------|
| `GET` | `/api/setup/status` | None | `{setup_complete, has_agents, provider, model}` |
| `POST` | `/api/setup` | None | `SetupResult` |

**Spec ref**: §15.1–15.2

---

### `app/providers/` *(S03)*

**Responsibility**: Lightweight LLM provider abstraction used for title generation and API-key validation before the full agent provider system (S04) is built.

| Module | Exports |
|--------|---------|
| `lite.py` | `call_lite(prompt, ...)`, `validate_api_key(provider, api_key, ...)` |

Supports: `openai`, `anthropic`, `ollama`. All I/O via `httpx`.

**Spec ref**: §4.3a (light usage until S04)

---

### `app/sessions/titles.py` *(S03)*

**Responsibility**: Automatic session title generation using the lite LLM provider.

**Key function**: `maybe_generate_title(db, session, ...)` — safe to call after every message; no-ops if trigger conditions are not met.

**Trigger rules**: first title generated when `message_count >= trigger_count` (default 2); regenerated every `regen_every` messages (default 20).

**Spec ref**: §3.2

---

### `app/api/routers/logs.py`

**Responsibility**: Audit log query endpoint.

**Routes:**

| Method | Path | Auth | Response |
|--------|------|------|---------|
| `GET` | `/api/logs` | Gateway token | Paginated audit log entries |

**Spec ref**: §12.4, §13.4

---

## Alembic migrations (`alembic/versions/`)

| Migration file | Tables created / altered |
|----------------|--------------------------|
| `0001_baseline.py` | Creates `sessions`, `messages`, `config`, `audit_log` tables || `0002_*.py` | Gateway token seed, session indexes |
| `0003_setup_and_fts.py` *(S03)* | Adds `agents` table; adds `title_generated_at` to sessions; creates `sessions_fts` FTS5 virtual table + 3 sync triggers; seeds 16 config keys for setup/provider settings || `0002_sessions_ws.py` | Adds `version`, `idle_at`, `archived_at` to `sessions`; seeds WS config rows |

New migrations follow the naming pattern `NNNN_<slug>.py` where `NNNN` is the four-digit sequence number. Run `alembic upgrade head` to apply all pending migrations (done automatically at startup).

---

## `app/sessions/` package *(Sprint 02)*

### `app/sessions/policy.py` *(Sprint 01)*

**Responsibility**: Session-level capability policy — defines what an agent can and cannot do within a session. Data model + presets. Enforcement wiring added in Sprint 07.

**Key exports:**

| Symbol | Kind | Notes |
|--------|------|-------|
| `SessionPolicy` | Pydantic `BaseModel` | `allowed_channels`, `allowed_tools`, `allowed_paths`, `can_spawn_agents`, `can_send_inter_session`, `max_tokens_per_run`, `max_tool_rounds`, `require_confirmation`, `auto_approve` |
| `SessionPolicyPresets` | Class | `ADMIN`, `STANDARD` (default), `WORKER`, `CODE_RUNNER`, `READ_ONLY`, `CHAT_ONLY` |

**Spec ref**: §2.7

---

### `app/sessions/models.py`

**Responsibility**: Pydantic models and enums for sessions and messages.

**Key exports:**

| Symbol | Kind | Notes |
|--------|------|-------|
| `Session` | Pydantic model | Full session record (§3.2): key, kind, status, policy, timestamps, version |
| `SessionCreate` | Pydantic model | Input for `POST /api/sessions` |
| `SessionUpdate` | Pydantic model | Input for `PATCH /api/sessions/{id}` (partial) |
| `Message` | Pydantic model | Stub message record (§3.4): id, session_id, role, content, timestamps |
| `MessageCreate` | Pydantic model | Input for `POST /api/sessions/{id}/messages` |
| `SessionKind` | `str` Enum | `user`, `agent_sub`, `channel`, `cron`, `webhook` |
| `SessionStatus` | `str` Enum | `active`, `idle`, `archived` |
| `MessageRole` | `str` Enum | `user`, `assistant`, `tool_result`, `system` |
| `make_user_key(agent_id?)` | `def` | Returns deterministic session key |
| `make_sub_key(agent_id)` | `def` | Returns unique sub-agent key |
| `make_channel_key(channel, id)` | `def` | Returns channel-scoped key |
| `make_cron_key(job_id)` | `def` | Returns cron-scoped key |
| `make_webhook_key()` | `def` | Returns webhook-scoped key (UUID) |

**Session key format** (§3.1): `user:main`, `user:agent:<id>`, `channel:telegram:<chat_id>`, `cron:<job_id>`, `webhook:<uuid>`

**Spec ref**: §3.1, §3.2, §3.4

---

### `app/sessions/store.py`

**Responsibility**: Session and message CRUD with OCC (optimistic concurrency control) and lifecycle state machine.

**Key exports:**

| Function | Notes |
|----------|-------|
| `get_session(db, id)` | Returns `Session | None` |
| `get_session_by_key(db, key)` | Returns `Session | None` |
| `list_sessions(db, status?, agent_id?, kind?, limit, offset)` | Paginated, ordered by `updated_at DESC` |
| `create_session(db, payload)` | INSERT; returns created `Session`; raises if key is duplicate |
| `update_session(db, id, payload, current_version)` | OCC update — retries up to 3×; raises `ConflictError` on exhaustion |
| `set_session_status(db, id, new_status, expected_status?)` | Conditional `WHERE status = ?` guard; raises `NotFoundError` if no row matched |
| `delete_session(db, id)` | Hard DELETE |
| `increment_message_count(db, id)` | Atomic `UPDATE … SET message_count = message_count + 1` |
| `list_messages(db, session_id, limit?, offset?)` | Ordered by `created_at ASC` |
| `create_message(db, session_id, payload)` | INSERT + atomic counter increment |

**OCC pattern**: `UPDATE … WHERE session_id = ? AND version = ?`; if `changes() == 0`, re-fetch and retry up to `_MAX_OCC_RETRIES = 3`.

**Spec ref**: §3.2, §3.7, §20.3, §20.4

---

### `app/sessions/queue.py`

**Responsibility**: Per-session async turn queue for depth-1 message serialisation (§20.6). Prevents concurrent agent runs for the same session.

**Key exports:**

| Symbol | Notes |
|--------|-------|
| `TurnQueue` | Class: `enqueue(item)` → `bool`  (False if full), `dequeue()` → `item | None`, `done()`, `is_busy: bool`, `depth: int` |
| `TurnQueueRegistry` | Class: `get(session_key)` → `TurnQueue`, `remove(session_key)` |
| `get_turn_registry()` | Returns process-wide singleton |

**Capacity**: `MAX_TURN_QUEUE_DEPTH = 10` (from `app/constants.py`).

**Spec ref**: §20.6

---

## `app/api/routers/sessions.py` *(Sprint 02)*

**Responsibility**: Session CRUD and lifecycle endpoints.

**Routes:**

| Method | Path | Status | Response |
|--------|------|--------|---------|
| `GET` | `/api/sessions` | 200 | `list[Session]` — filters: `status`, `agent_id`, `kind` |
| `POST` | `/api/sessions` | 201 | `Session` |
| `GET` | `/api/sessions/{id}` | 200 / 404 | `Session` |
| `PATCH` | `/api/sessions/{id}` | 200 / 404 / 409 | `Session` (OCC — 409 on version conflict) |
| `DELETE` | `/api/sessions/{id}` | 204 / 404 | — |
| `POST` | `/api/sessions/{id}/archive` | 200 / 404 | `Session` (status → archived) |
| `POST` | `/api/sessions/{id}/activate` | 200 / 404 | `Session` (status → active) |

**Spec ref**: §3.2, §3.7, §13.2

---

## `app/api/routers/messages.py` *(Sprint 02)*

**Responsibility**: Per-session message list and create.

**Routes:**

| Method | Path | Status | Response |
|--------|------|--------|---------|
| `GET` | `/api/sessions/{id}/messages` | 200 | `list[Message]` |
| `POST` | `/api/sessions/{id}/messages` | 201 / 404 | `Message` |

**Spec ref**: §3.4, §13.2

---

## `app/api/ws.py` *(Sprint 02)*

**Responsibility**: Persistent WebSocket endpoint at `WS /api/ws`.

**Wire protocol** (§2.5):
- Client → Server: `{ "id": str, "method": str, "params": {...} }`
- Server → Client response: `{ "id": str, "ok": bool, "payload": {...}, "error": str | null }`
- Server → Client event: `{ "event": str, "payload": {...}, "seq": int }`

**Supported methods:**

| Method | Description |
|--------|-------------|
| `connect` | Handshake (must be first frame); creates/resumes session; optional `last_seq` for replay |
| `pong` | Heartbeat acknowledgement |
| `send_message` | Persist + echo message; emits `inbound.message` gateway event |
| `switch_session` | Change active session for this connection |

**Heartbeat**: server sends `{ event: "ping", seq: 0 }` every 30 s.

**Reconnection** (§2.5a): client sends `last_seq` in `connect.params`; server calls `EventBuffer.since(last_seq)`; if too old → `resync_required` event.

**Spec ref**: §2.4, §2.5, §2.5a, §13.2

---

## Sprint 08 — Multi-Agent additions

### `app/agent/sub_agent.py` *(Sprint 08)*

**Responsibility**: Sub-agent spawning, lifecycle management, and per-parent concurrency enforcement (§3.3, §20.7).

**Key exports:**

| Symbol | Notes |
|--------|-------|
| `spawn_sub_agent(agent_id, initial_message?, policy_preset?, parent_session_key?, auto_archive_minutes?)` | Creates a sub-agent session, applies policy preset, optionally emits an `INBOUND_MESSAGE` event, schedules auto-archive. Returns the new `session_key`. |
| `active_sub_agent_count(parent_session_key)` | Returns the current count of tracked sub-agent sessions for the given parent. |
| `_active` | `dict[str, set[str]]` — module-level concurrency tracker, keyed by parent session key. |

**Concurrency**: Enforces `MAX_CONCURRENT_SUBAGENTS` (3) per parent; raises `RuntimeError` if limit reached.

**Spec ref**: §3.3, §20.7

---

### `app/tools/builtin/sessions.py` *(Sprint 08)*

**Responsibility**: Four session-interaction tools for agent-to-agent communication (§3.3).

**Key exports (all `@tool` decorated):**

| Tool | Safety | Notes |
|------|--------|-------|
| `sessions_list(kind?, agent_id?, limit?)` | `read_only` | Lists accessible sessions with key, kind, agent_id, title, status. |
| `sessions_history(session_key, limit?)` | `read_only` | Returns recent messages from another session (resolves key → UUID internally). |
| `sessions_send(session_key, message, timeout_s?)` | `side_effect` | Fire-and-forget or wait-for-reply message injection. |
| `sessions_spawn(agent_id, initial_message?, policy_preset?)` | `side_effect` | Creates a sub-agent session via `spawn_sub_agent`. |

**Spec ref**: §3.3

---

### `app/workflows/__init__.py` *(Sprint 08)*

Package marker.

---

### `app/workflows/models.py` *(Sprint 08)*

**Responsibility**: Pydantic domain models for workflow definitions and run state (§10.1–10.3).

**Key exports:**

| Symbol | Kind | Notes |
|--------|------|-------|
| `WorkflowStep` | Pydantic model | `id`, `agent_id`, `prompt_template`, `timeout_s`, `retry` |
| `Workflow` | Pydantic model | `id`, `name`, `description`, `mode`, `steps`, `created_at`, `updated_at` + `from_row()` |
| `WorkflowRun` | Pydantic model | `id`, `workflow_id`, `status`, `step_results`, `current_step`, `error`, `started_at`, `completed_at`, `created_at` + `from_row()` |

**Spec ref**: §10.1, §10.2, §10.3

---

### `app/workflows/store.py` *(Sprint 08)*

**Responsibility**: DB CRUD for `workflows` and `workflow_runs` tables.

**Key exports:**

| Symbol | Notes |
|--------|-------|
| `WorkflowStore` | Class: `create_workflow`, `get_workflow`, `list_workflows`, `update_workflow`, `delete_workflow`, `create_run`, `get_run`, `list_runs`, `update_run_status` |
| `init_workflow_store(db)` | Initialises the process-wide singleton. |
| `get_workflow_store()` | Returns the singleton. |

**Spec ref**: §10.3

---

### `app/workflows/runtime.py` *(Sprint 08)*

**Responsibility**: Workflow execution engine — pipeline (sequential) and parallel (fan-out) modes.

**Key exports:**

| Symbol | Notes |
|--------|-------|
| `execute_workflow(workflow, run, parent_session_key?)` | Top-level dispatch — calls `run_pipeline` or `run_parallel`. |
| `run_pipeline(workflow, run, parent_session_key?)` | Sequential step execution; each step's output becomes `{context}` for the next. |
| `run_parallel(workflow, run, parent_session_key?)` | Concurrent `asyncio.gather` over all steps; bounded by `MAX_CONCURRENT_SUBAGENTS` semaphore. |
| `_run_step(step, context, parent_session_key?)` | Spawns a sub-agent, waits for `AGENT_RUN_COMPLETE`, returns last assistant message. |
| `_run_step_with_retry(step, context, parent_session_key?)` | Wraps `_run_step` with `step.retry + 1` attempts. |

**Spec ref**: §10.1, §10.2

---

### `app/workflows/api.py` *(Sprint 08)*

**Responsibility**: REST API for workflow CRUD and run management (§10.3).

**Routes:**

| Method | Path | Status | Notes |
|--------|------|--------|-------|
| `POST` | `/api/workflows` | 201 | Create workflow definition |
| `GET` | `/api/workflows` | 200 | List workflows (limit, offset) |
| `GET` | `/api/workflows/{id}` | 200/404 | Workflow detail |
| `PUT` | `/api/workflows/{id}` | 200/404 | Update workflow |
| `DELETE` | `/api/workflows/{id}` | 204/404 | Delete workflow |
| `POST` | `/api/workflows/{id}/run` | 202 | Trigger execution (background task) |
| `GET` | `/api/workflows/{id}/runs` | 200 | List runs |
| `GET` | `/api/workflows/{id}/runs/{run_id}` | 200/404 | Run detail + status |
| `POST` | `/api/workflows/{id}/runs/{run_id}/cancel` | 200/409 | Cancel non-terminal run |

**Spec ref**: §10.3

---

### `alembic/versions/0008_sprint08_workflows.py` *(Sprint 08)*

| Table | Columns |
|-------|---------|
| `workflows` | `id`, `name`, `description`, `mode`, `steps_json`, `created_at`, `updated_at` |
| `workflow_runs` | `id`, `workflow_id`, `status`, `step_results_json`, `current_step`, `error`, `started_at`, `completed_at`, `created_at` |

---

## Sprint 09 — Memory I: Vault, Embeddings, Memory Data Model, Entity Model *(§5.1–§5.4, §5.10, §5.13)*

### `app/knowledge/vault.py` *(Sprint 09)*

**Responsibility**: Markdown note CRUD backed by disk (`.md` files) + SQLite metadata. Supports wiki-links, hashtag tags, full-text search, graph generation, and disk-sync.

**Key exports:**

| Symbol | Kind | Notes |
|--------|------|-------|
| `VaultNote` | Pydantic model | id, title, slug, filename, content, content_hash, wikilinks, tags, timestamps |
| `VaultGraph` | Pydantic model | nodes `[{id, title, slug}]`, edges `[{from_id, to_id}]` |
| `SyncResult` | Pydantic model | added, updated, deleted counts |
| `VaultStore` | Class | `create_note()`, `get_note()`, `get_note_by_slug()`, `list_notes()`, `update_note()`, `delete_note()`, `get_graph()`, `sync_from_disk()` |
| `init_vault_store(db, vault_path)` | Function | Singleton initialiser |
| `get_vault_store()` | Function | Singleton accessor |

**Spec ref**: §5.1, §5.10

---

### `app/knowledge/embeddings.py` *(Sprint 09)*

**Responsibility**: Provider-agnostic vector embedding engine with SQLite storage and cosine similarity search.

**Key exports:**

| Symbol | Kind | Notes |
|--------|------|-------|
| `EmbeddingProvider` | ABC | `embed(texts)`, `dimensions()`, `model_id()` |
| `LocalEmbeddingProvider` | Class | `all-MiniLM-L6-v2` (384 dims); sentence-transformers lazy-loaded on first call |
| `EmbeddingStore` | ABC | `add()`, `add_batch()`, `search()`, `delete()`, `reindex()` |
| `SQLiteEmbeddingStore` | Class | BLOB vector storage; numpy brute-force cosine similarity; in-memory cache; upsert via `ON CONFLICT` |
| `EmbeddingItem` | Pydantic model | source_type, source_id, model_id, vector, dimensions |
| `EmbeddingSearchResult` | Pydantic model | item + score |
| `ReindexResult` | Pydantic model | indexed_count, duration_s, model_id |
| `init_embedding_store(db, provider)` | Function | Singleton initialiser |
| `get_embedding_store()` | Function | Singleton accessor |

**Spec ref**: §5.2, §5.13

---

### `app/memory/models.py` *(Sprint 09)*

**Responsibility**: `MemoryExtract` Pydantic model for all seven memory types with per-type defaults, OCC versioning field, and provenance tracking.

**Key exports:**

| Symbol | Kind | Notes |
|--------|------|-------|
| `MEMORY_TYPES` | Literal | `"identity"`, `"preference"`, `"fact"`, `"experience"`, `"task"`, `"relationship"`, `"skill"` |
| `MemoryExtract` | Pydantic model | All §5.3 fields; validators clamp confidence/decay to [0,1]; `version` for OCC |
| `with_type_defaults(**kwargs)` | classmethod | Applies per-type `always_recall` and `recall_weight` defaults |
| `from_row(row)` | classmethod | Deserialises aiosqlite `Row` |
| `_TYPE_DEFAULTS` | dict | Per-type defaults: identity→`{always_recall:True, recall_weight:1.5}`, etc. |

**Spec ref**: §5.3

---

### `app/memory/store.py` *(Sprint 09)*

**Responsibility**: CRUD operations for `memory_extracts` table; OCC update guard with 3-retry; entity link management.

**Key exports:**

| Symbol | Kind | Notes |
|--------|------|-------|
| `MemoryStore` | Class | `create()`, `get()` (touches last_accessed), `list()`, `update()` (OCC 3-retry), `delete()`, `soft_delete()`, `link_entity()`, `unlink_entity()` |
| `init_memory_store(db)` | Function | Singleton initialiser |
| `get_memory_store()` | Function | Singleton accessor |

**Spec ref**: §5.3, §20.3b

---

### `app/memory/entities.py` *(Sprint 09)*

**Responsibility**: `Entity` Pydantic model and regex-based NER for extracting entity mentions from text.

**Key exports:**

| Symbol | Kind | Notes |
|--------|------|-------|
| `ENTITY_TYPES` | Literal | `"person"`, `"organization"`, `"project"`, `"location"`, `"tool"`, `"concept"`, `"event"`, `"date"` |
| `Entity` | Pydantic model | id, name, entity_type, aliases, summary, properties, reference_count, status, merged_into, timestamps; `matches(name)` method |
| `extract_entity_mentions(text)` | Function | Regex NER; strips code blocks; returns `[{name, entity_type}]`; heuristic types (Inc/Ltd → organization, Dr/Mr → person) |
| `_NER_STOPWORDS` | frozenset | Common English words excluded from NER |

**Spec ref**: §5.4

---

### `app/memory/entity_store.py` *(Sprint 09)*

**Responsibility**: CRUD for the `entities` table; alias resolution; entity–memory linking; NER-to-DB pipeline.

**Key exports:**

| Symbol | Kind | Notes |
|--------|------|-------|
| `EntityStore` | Class | `create()`, `get()`, `list()`, `resolve(name)` (canonical + alias scan), `update()`, `add_alias()`, `delete()`, `soft_delete()`, `increment_reference()`, `get_memories(entity_id)`, `extract_and_link(text, memory_id)` |
| `init_entity_store(db)` | Function | Singleton initialiser |
| `get_entity_store()` | Function | Singleton accessor |

**Spec ref**: §5.4

---

### `app/api/routers/vault.py` *(Sprint 09)*

**Responsibility**: REST API for vault note management and disk sync (§5.1).

**Routes:**

| Method | Path | Status | Notes |
|--------|------|--------|-------|
| `GET` | `/api/vault/notes` | 200 | List notes (search, limit, offset) |
| `POST` | `/api/vault/notes` | 201 | Create note → writes .md to disk |
| `GET` | `/api/vault/notes/{note_id}` | 200/404 | Note detail |
| `PUT` | `/api/vault/notes/{note_id}` | 200/404 | Update title/content/tags |
| `DELETE` | `/api/vault/notes/{note_id}` | 204/404 | Delete note + disk file |
| `GET` | `/api/vault/graph` | 200 | Wiki-link graph `{nodes, edges}` |
| `POST` | `/api/vault/sync` | 200 | Scan disk for external adds/edits/deletes |

**Spec ref**: §5.1

---

### `app/api/routers/memory.py` *(Sprint 09)*

**Responsibility**: REST API for memory extract CRUD and reindex trigger (§5.3).

**Routes:**

| Method | Path | Status | Notes |
|--------|------|--------|-------|
| `GET` | `/api/memory` | 200 | List extracts (type, scope, agent_id, always_recall_only) |
| `POST` | `/api/memory` | 201 | Create memory extract |
| `GET` | `/api/memory/{memory_id}` | 200/404 | Extract detail |
| `PATCH` | `/api/memory/{memory_id}` | 200/404 | Partial update (OCC guard) |
| `DELETE` | `/api/memory/{memory_id}` | 204/404 | Hard delete |
| `POST` | `/api/memory/reindex` | 200 | Trigger embedding reindex |

**Spec ref**: §5.3

---

### `app/api/routers/entities.py` *(Sprint 09)*

**Responsibility**: REST API for entity CRUD, alias management, memory graph, and NER extraction (§5.4).

**Routes:**

| Method | Path | Status | Notes |
|--------|------|--------|-------|
| `GET` | `/api/entities` | 200 | List entities (type, status, search) |
| `POST` | `/api/entities` | 201 | Create entity |
| `GET` | `/api/entities/{entity_id}` | 200/404 | Entity detail |
| `PATCH` | `/api/entities/{entity_id}` | 200/404 | Partial update |
| `DELETE` | `/api/entities/{entity_id}` | 204/404 | Hard delete |
| `POST` | `/api/entities/{entity_id}/aliases` | 200/404 | Add alias |
| `GET` | `/api/entities/{entity_id}/memories` | 200/404 | Memory IDs linked to entity |
| `POST` | `/api/entities/ner` | 200 | NER extraction → `{mentions: [{name, entity_type}]}` |

**Spec ref**: §5.4

---

### `alembic/versions/0009_sprint09_memory.py` *(Sprint 09)*

| Table | Key Columns |
|-------|------------|
| `vault_notes` | `id`, `title`, `slug` (UNIQUE), `filename` (UNIQUE), `content_hash`, `wikilinks` JSON, `tags` JSON, timestamps |
| `embeddings` | `id`, `source_type`, `source_id` (UNIQUE pair), `model_id`, `vector` BLOB, `dimensions`, `text_hash` |
| `memory_extracts` | `id`, `content`, `memory_type`, `always_recall`, `recall_weight`, `pinned`, `version` (OCC), `entity_ids` JSON, `scope`, `agent_id`, `status`, `confidence`, `decay_rate`, timestamps |
| `entities` | `id`, `name`, `entity_type`, `aliases` JSON, `summary`, `properties` JSON, `reference_count`, `status`, `merged_into`, timestamps |
| `memory_entity_links` | (`memory_id` FK, `entity_id` FK) composite PK, cascade delete |

---

## Sprint 10 — Memory II: Extraction, Recall & Knowledge Sources *(§5.5–§5.7, §5.14)*

### `app/memory/extraction.py` *(Sprint 10)*

**Responsibility**: Background extraction pipeline — periodically scans recent session messages and extracts `MemoryExtract` records via LLM structured output.

**Key exports:**

| Symbol | Type | Purpose |
|--------|------|---------|
| `ExtractionConfig` | Pydantic model | `trigger_interval_messages`, `max_messages_per_run`, `model_override` |
| `ExtractionPipeline` | class | `run(session_id, messages)` — async extraction job |
| `init_extraction_pipeline(config?)` | fn | Creates and stores singleton |
| `get_extraction_pipeline()` | fn | Returns singleton; raises `RuntimeError` if not init |

**Spec ref**: §5.5

---

### `app/memory/recall.py` *(Sprint 10)*

**Responsibility**: Three-stage recall pipeline — loads always-recall memories (Stage 1), runs similarity + FTS + entity-expansion + KB federation search per turn (Stage 2), prefetches candidates in background (Stage 3).

**Key exports:**

| Symbol | Type | Purpose |
|--------|------|---------|
| `RecallConfig` | Pydantic model | Budget + threshold + entity bonus + KB top-k settings |
| `RecallPipeline` | class | `load_always_recall()`, `recall_for_turn()`, `prefetch_background()` |
| `init_recall_pipeline(config?)` | fn | Creates singleton |
| `get_recall_pipeline()` | fn | Returns singleton; raises `RuntimeError` if not init |

**Spec ref**: §5.6

---

### `app/knowledge/sources/` *(Sprint 10)*

Package containing knowledge source models, adapters, and registry.

#### `app/knowledge/sources/models.py`

| Symbol | Purpose |
|--------|---------|
| `QueryMode` | Enum: `text`, `vector`, `hybrid` |
| `KnowledgeSource` | Pydantic model; `source_id`, `name`, `backend`, `status`, `auto_recall`, `connection`, `allowed_agents` etc. |
| `KnowledgeChunk` | Retrieved chunk: `source_id`, `content`, `score`, `metadata` |

#### `app/knowledge/sources/adapters/`

| Module | Adapter | Backend |
|--------|---------|---------|
| `base.py` | `KnowledgeSourceAdapter` (ABC) | Base class |
| `chroma.py` | `ChromaAdapter` | ChromaDB |
| `pgvector.py` | `PgVectorAdapter` | PostgreSQL + pgvector |
| `faiss.py` | `FAISSAdapter` | FAISS index |
| `http.py` | `HTTPAdapter` | Generic HTTP JSON API |

#### `app/knowledge/sources/registry.py`

| Symbol | Purpose |
|--------|---------|
| `KnowledgeSourceRegistry` | CRUD + activate/deactivate + search + federation; background health-check loop |
| `init_knowledge_source_registry(db)` | Creates singleton |
| `get_knowledge_source_registry()` | Returns singleton; raises `RuntimeError` if not init |

**Spec ref**: §5.14

---

### `app/api/routers/knowledge_sources.py` *(Sprint 10)*

**Responsibility**: REST CRUD + federation for knowledge sources.

**Routes** (prefix `/api/knowledge-sources`):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | List sources (filter by status, backend, auto_recall) |
| `POST` | `/` | Register new source [201] |
| `GET` | `/{id}` | Get by ID |
| `PATCH` | `/{id}` | Update fields |
| `DELETE` | `/{id}` | Delete [204] |
| `POST` | `/{id}/activate` | Health-check → set active |
| `POST` | `/{id}/deactivate` | Set disabled |
| `POST` | `/{id}/test` | Health-check only |
| `GET` | `/{id}/stats` | Count + status |
| `POST` | `/search` | Federated search across sources |

**Spec ref**: §5.14

---

### `app/tools/builtin/knowledge.py` *(Sprint 10)*

**Responsibility**: Agent-callable tools for knowledge base queries.

| Tool | Signature | Description |
|------|-----------|-------------|
| `kb_search` | `(query, source_ids?, top_k=10)` | Search KB sources, returns formatted markdown |
| `kb_list_sources` | `(status_filter?)` | List KB sources, returns formatted markdown |

Both tools have `safety="read_only"` and degrade gracefully when registry is not initialized.

**Spec ref**: §5.7

---

### `alembic/versions/0010_sprint10_knowledge_sources.py` *(Sprint 10)*

| Table | Key Columns |
|-------|------------|
| `knowledge_sources` | `id`, `name`, `backend`, `query_mode`, `embedding_provider`, `auto_recall`, `priority`, `max_results`, `similarity_threshold`, `connection_json`, `allowed_agents_json`, `status`, `error_message`, `consecutive_failures`, `last_health_check`, timestamps |

---

| File | What it covers |
|------|----------------|
| `test_budget.py` | Budget tracker (stub — Sprint 14) |
| `test_config.py` | `ConfigStore` get/set/hot-reload, `ServerSettings` env loading |
| `test_routes_sessions.py` | Session API routes (stub — Sprint 02) |
| `test_vault.py` | Vault file helper (stub — Sprint 09) |
| `test_session_store.py` | Session CRUD, lifecycle states, OCC guard, atomic counter *(Sprint 02)* |
| `test_api_sessions.py` | REST endpoints for sessions and messages *(Sprint 02)* |
| `test_websocket.py` | WS connect, send_message, switch_session, pong, reconnect guard *(Sprint 02)* |
| `test_health_status.py` | `/api/health` and `/api/status` response structure and uptime *(Sprint 03)* |
| `test_setup_wizard.py` | Setup wizard status + run flow, conflict guard, force re-run *(Sprint 03)* |
| `test_session_search.py` | FTS5 search, status filter, sort/order params, pagination *(Sprint 03)* |
| `unit/test_session_tools.py` | `sessions_list`, `sessions_history`, `sessions_send`, `sessions_spawn` tools *(Sprint 08)* |
| `unit/test_sub_agent.py` | `spawn_sub_agent` — session creation, WORKER policy, concurrency enforcement, active tracking *(Sprint 08)* |
| `unit/test_workflow_runtime.py` | Pipeline/parallel runtime — step execution, context passing, failure handling, dispatch *(Sprint 08)* |
| `integration/test_workflow_e2e.py` | Full workflow REST API: create → run → status → cancel → delete *(Sprint 08)* |
| `integration/test_multi_agent.py` | Session tool integration: list, history, spawn visibility, concurrency limit *(Sprint 08)* |
| `unit/test_vault.py` | VaultStore CRUD, wikilinks, hashtag extraction, slug uniqueness, graph, disk sync *(Sprint 09)* |
| `unit/test_embeddings.py` | SQLiteEmbeddingStore add/upsert/delete/batch/search/reindex with FakeEmbeddingProvider *(Sprint 09)* |
| `unit/test_memory_model.py` | MemoryExtract model defaults, OCC versioning, store CRUD, type filtering *(Sprint 09)* |
| `unit/test_entities.py` | Entity model, NER extraction, EntityStore CRUD, alias resolution, extract_and_link *(Sprint 09)* |
| `integration/test_vault_embeddings.py` | Full API integration: vault CRUD, graph, sync, memory CRUD, entity CRUD, NER endpoint *(Sprint 09)* |
| `unit/test_extraction.py` | ExtractionPipeline trigger config, run flow with mocked stores, entity linking, error isolation *(Sprint 10)* |
| `unit/test_recall.py` | RecallPipeline Stage 1 (always_recall), Stage 2 (embedding+FTS+entity+KB), Stage 3 prefetch, singleton guards *(Sprint 10)* |
| `unit/test_knowledge_sources.py` | KnowledgeSource model, QueryMode, KnowledgeChunk, HTTP adapter, registry CRUD, singleton *(Sprint 10)* |
| `integration/test_extraction_recall.py` | Extraction + recall end-to-end via test app: KB registration, source CRUD, activate/deactivate, stats *(Sprint 10)* |
| `integration/test_federation.py` | Federation search, mock adapter injection, agent tool registration *(Sprint 10)* |

All tests use `pytest` with `asyncio_mode = "auto"`. Run: `.venv\Scripts\python.exe -m pytest tests/ -v --tb=short`

---

## Frontend (`frontend/src/`) *(Sprint 02)*

React 18 + Vite 6 + TypeScript + Tailwind CSS v4 + Zustand + TanStack Query.

### `frontend/src/api/`

| File | Responsibility |
|------|----------------|
| `client.ts` | Typed `fetch` wrapper (`api.get/post/patch/delete`); throws `ApiError` on non-2xx |
| `sessions.ts` | `sessionsApi.*` + `messagesApi.*` REST bindings; `Session` / `Message` TypeScript types; `q/sort/order/status` params on `list()` *(S03)* |
| `ws.ts` | `TequilaWs` class — reconnecting WS client with seq tracking; `wsClient` singleton |
| `setup.ts` | `setupApi.status()` / `setupApi.run()` — setup wizard REST bindings *(S03)* |
| `system.ts` | `systemApi.health()` / `systemApi.status()` — health/status REST bindings *(S03)* |

### `frontend/src/stores/`

| File | Responsibility |
|------|----------------|
| `uiStore.ts` | Sidebar open/close, theme mode, shortcut overlay flag — persisted to `localStorage` |
| `wsStore.ts` | WS connection status, last event; wires singleton `wsClient` to Zustand |
| `chatStore.ts` | Active session + local message list; optimistic appends |
| `sessionFilterStore.ts` | Search query, status filter, sort field, order — drives `useSessions` query key *(S03)* |

### `frontend/src/hooks/`

| File | Responsibility |
|------|----------------|
| `useSessions.ts` | `useSessions` (reads `sessionFilterStore`), `useSession`, `useCreateSession`, `useUpdateSession`, `useDeleteSession`, `useArchiveSession` |
| `useMessages.ts` | `useMessages`, `useSendMessage` |
| `useSetup.ts` | `useSetupStatus`, `useRunSetup` — wraps setup API *(S03)* |

### `frontend/src/lib/`

| File | Responsibility |
|------|----------------|
| `theme.ts` | Theme init / get / set; resolves system preference; anti-flash; `localStorage` key `tequila.theme` |
| `shortcuts.ts` | Global keyboard shortcut handler (`useShortcuts` hook); shortcut registry |
| `utils.ts` | `cn()` — clsx + tailwind-merge helper |

### `frontend/src/components/`

| Component | Responsibility |
|-----------|----------------|
| `layout/AppLayout.tsx` | Root layout: Sidebar + main content; starts WS on mount |
| `layout/Sidebar.tsx` | Session list sidebar with WS status dot; theme toggle footer; Diagnostics link *(S03)* |
| `sessions/SessionList.tsx` | Session list with search bar (debounced), status filter, sort/order controls *(S03)* |
| `chat/ChatPanel.tsx` | Full chat panel — header, message list, input; WS echo integration |
| `chat/MessageList.tsx` | Scrollable message list with auto-scroll; user/assistant bubble styling |
| `chat/MessageInput.tsx` | Auto-resizing textarea; Enter to send, Shift+Enter for newline |
| `ui/button.tsx` | CVA-based `Button` primitive (default / outline / ghost / danger) |
| `ui/input.tsx` | Styled `Input` primitive |
| `ui/ThemeToggle.tsx` | Three-way toggle (light / dark / system) |
| `ui/ShortcutsHelp.tsx` | Keyboard shortcuts overlay (Ctrl+Shift+?) |

### `frontend/src/pages/` *(S03)*

| Page | Route | Responsibility |
|------|-------|----------------|
| `SetupWizard.tsx` | `/setup` | Multi-step first-run wizard (6 steps: welcome, provider, credentials, model, agent name, done) |
| `DiagnosticsPage.tsx` | `/diagnostics` | Live system status panel (uptime, provider, DB stats, scheduler); auto-refreshes every 15 s |
