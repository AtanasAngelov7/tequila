# Architecture

**Spec refs**: §2 (Gateway), §14 (Data Persistence), §15 (Startup Lifecycle), §20 (Concurrency Model)

---

## High-level module graph

```
                        ┌─────────────┐
                        │   main.py   │  uvicorn entry point
                        └──────┬──────┘
                               │ creates
                        ┌──────▼──────────────────────────┐
                        │         app/api/app.py           │  FastAPI application
                        │  lifespan: db.startup → db.shutdown │
                        │  registers all routers           │
                        └──────┬──────────────────────────┘
                               │ depends on
          ┌────────────────────┼─────────────────────┐
          │                    │                     │
   ┌──────▼──────┐    ┌────────▼───────┐    ┌───────▼────────┐
   │  app/db/    │    │  app/gateway/  │    │  app/config.py │
   │ connection  │    │    router      │    │  ConfigStore   │
   │ (WAL, lock) │    │  (event bus)   │    │ (SQLite-backed)│
   └──────┬──────┘    └────────┬───────┘    └───────┬────────┘
          │                    │                     │
          └────────────────────▼─────────────────────┘
                               │ all write to / read from
                        ┌──────▼──────┐
                        │  SQLite DB  │  data/tequila.db  (WAL mode)
                        └─────────────┘
```

Supporting modules (no external callers at Sprint 01 level):

```
app/audit/log.py      ─── writes AuditEvent rows; queried by /api/logs
app/exceptions.py     ─── domain exception hierarchy; caught by API exception handlers
app/constants.py      ─── string literals and numeric defaults
app/paths.py          ─── canonical filesystem Path objects (data/, vault/, uploads/, …)
app/db/schema.py      ─── schema introspection helpers used by Alembic env.py
```

---

## Startup sequence (§15)

`main.py` calls `create_app()` which wires the FastAPI lifespan:

```
1. ServerSettings loaded from env / .env
2. Filesystem paths created (data/, data/vault/, data/uploads/, …)  [app.paths]
3. Database opened with WAL pragmas                                  [app.db.connection.startup]
4. Alembic migrations run (alembic upgrade head)                     [alembic/]
5. GatewayRouter initialised and started                             [app.gateway.router.init_router]
6. ConfigStore hydrated from `config` table                          [app.config.ConfigStore]
6b. Encryption key initialised (Fernet); generated if absent         [app.auth.encryption.init_encryption]
7. FastAPI routers registered                                        [app.api.app]
8. HTTP server ready — uvicorn accepts connections
8r. PluginRegistry created; built-in plugins registered; health loop started [app.plugins.registry.init_plugin_registry]
```

On shutdown (SIGTERM / KeyboardInterrupt):

```
1. PluginRegistry stopped (deactivate all active plugins)
2. GatewayRouter stopped (drain in-flight events)
3. Database connection closed cleanly
```

---

## Concurrency model (§20)

Single process, single asyncio event loop.

```
┌─────────────────────────────────────────────┐
│ event loop                                  │
│                                             │
│  ┌──────────────┐   ┌──────────────────┐   │
│  │ HTTP handler │   │  background task │   │
│  └──────┬───────┘   └────────┬─────────┘   │
│         │ write              │ write        │
│         └──────────┬─────────┘             │
│                    ▼                        │
│           asyncio.Lock (per DB path)        │
│                    │                        │
│                    ▼                        │
│           BEGIN IMMEDIATE → SQL → COMMIT    │
│           (write_transaction helper)        │
└─────────────────────────────────────────────┘
```

**Rules enforced by `write_transaction`:**
- Lock acquired → `BEGIN IMMEDIATE` → execute SQL → `COMMIT` (or `ROLLBACK` on exception).
- Lock is **never** held across an `await` that does network I/O.
- Reads bypass the lock entirely (WAL allows concurrent readers).

**Optimistic concurrency control (OCC):**  
Tables `sessions`, `config`, `agents`, `memory_extracts` carry a `version INTEGER` column.  
Updates always include `WHERE id = ? AND version = ?` and increment `version`.  
If `changes() == 0`, the row was modified concurrently — retry up to 3×.

---

## Data flow: inbound message (future Sprint 02+)

```
WebSocket frame arrives
        │
        ▼
app/api/ws.py  ─── parse frame ──► GatewayEvent(event_type="inbound.message")
        │
        ▼
GatewayRouter.emit()
        │
        ├─► SessionBuffer  (buffer if session is busy)
        │
        └─► SessionPolicy.check()  (validate session state / rate limits)
                │
                ▼
           AgentRuntime.handle_turn()  [Sprint 04+]
```

---

## Plugin System *(Sprint 12, §8.0–§8.9)*

All connectors inherit from `PluginBase` and are managed by a singleton `PluginRegistry`.

```
PluginRegistry  (app/plugins/registry.py)
      │
      ├─ register(plugin_id, PluginBase instance)
      │
      ├─ install()  → PluginStore.save_plugin()
      ├─ activate() → plugin.configure() → plugin.activate(gateway)
      ├─ deactivate() → plugin.deactivate()
      └─ health loop (every 300 s) → plugin.health()
                │ 3 consecutive failures
                └─────► auto-deactivate + status = "error"

Built-in plugins auto-registered at startup:
  webhooks, telegram, smtp_imap, gmail, google_calendar
```

**Encryption layer** (`app/auth/encryption.py`):

```
Fernet(key)  ←  init_encryption(b64_key) called in lifespan step 6b
      │
      ├─ encrypt_credential(plain_text) → base64 token  (stored in plugin_credentials)
      └─ decrypt_credential(token)      → plain_text    (never returned via API)
```

**Auth provider keys** (`app/auth/providers.py`):

```
POST /api/auth/providers/{provider}/key
      │
      ├─ encrypt_credential(key)
      └─ PluginStore.save_credential(plugin_id="__auth__", key="api_key:{provider}", ...)

GET /api/auth/providers  → list configured providers (no plaintext exposure)
```

---

## Filesystem layout

Managed by `app/paths.py`. All paths are relative to the project root unless an env override is set.

```
data/
├── tequila.db          ← SQLite database (WAL)
├── vault/              ← user notes and documents
├── uploads/            ← file attachments from chat
├── auth/               ← OAuth tokens (encrypted at rest, Sprint 06)
├── backups/            ← automatic database backups (Sprint 14)
└── browser_profiles/   ← Playwright browser profile dirs (Sprint 13)

app/plugins/custom/     ← user-installed plugins (Sprint 12)
```
