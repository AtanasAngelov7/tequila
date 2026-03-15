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

## Tests (`tests/`)

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
