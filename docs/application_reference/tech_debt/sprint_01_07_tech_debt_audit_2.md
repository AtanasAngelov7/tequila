# Tequila v2 — Tech Debt Audit (Pass 2)

**Date:** 2026-03-15  
**Scope:** `app/` tree, `alembic/versions/`, public API surface  
**Previous fixes:** TD-01 through TD-15 (confirmed resolved; not re-reported)

---

## Critical Severity

### TD-16: Gateway token comparison vulnerable to timing attack
- **File:** `app/api/deps.py` line 92
- **Problem:** `if x_gateway_token != expected` uses plain string equality, which is vulnerable to timing side-channel attacks. An attacker could progressively deduce the token byte by byte by measuring response time differences.
- **Category:** Security
- **Suggested fix:** Use `hmac.compare_digest(x_gateway_token, expected)` from the `hmac` stdlib module for constant-time comparison. Guard the `None` case before calling.

### TD-17: Placeholder API keys shipped in provider constructors
- **File:** `app/providers/anthropic.py` line 159, `app/providers/openai.py` line 138
- **Problem:** Both providers fall back to hardcoded placeholder keys (`"sk-ant-placeholder"`, `"sk-placeholder"`) when no environment variable is set. This means the SDK client is always instantiated — even with a fake key — and will send authenticated requests to the real API with an invalid credential, leaking the fact that the app exists and potentially triggering rate-limit counters on the vendor side.
- **Category:** Security / Design
- **Suggested fix:** Fall back to `""` or `None`, and have `health_check()` / `stream_completion()` raise a clear `ProviderNotConfigured` error early instead of letting the SDK hit the network.

### TD-18: `ConfigStore.set()` bypasses `write_transaction` — manual `BEGIN IMMEDIATE`
- **File:** `app/config.py` lines 226–237
- **Problem:** `ConfigStore.set()` calls `await self._db.execute("BEGIN IMMEDIATE")` and `await self._db.commit()` / `rollback()` manually instead of using the project's `write_transaction()` context manager. This bypasses the global write lock in `app/db/connection.py`, so concurrent config writes can deadlock or produce `SQLITE_BUSY` errors under async concurrency.
- **Category:** Bug / Concurrency
- **Suggested fix:** Replace the manual transaction with `async with write_transaction(self._db):`.

---

## High Severity

### TD-19: Agents API endpoints have no gateway-token authentication
- **File:** `app/api/routers/agents.py` (all routes)
- **Problem:** None of the agent CRUD endpoints (`GET /api/agents`, `POST /api/agents`, `PATCH /api/agents/{id}`, `DELETE /api/agents/{id}`, etc.) require `Depends(require_gateway_token)`. Every other data-modifying router (sessions, messages, config, logs) enforces the token. This means agent creation, deletion, cloning, soul updates, and import/export are unauthenticated when a gateway token is configured.
- **Category:** Security / API
- **Suggested fix:** Add `_token: None = Depends(require_gateway_token)` to every route handler, or add `dependencies=[Depends(require_gateway_token)]` at the router level.

### TD-20: Provider listing endpoints have no gateway-token authentication
- **File:** `app/api/routers/providers.py` (all routes)
- **Problem:** `GET /api/providers`, `GET /api/providers/{id}`, and `GET /api/providers/{id}/models` are all unprotected. While they are read-only, they leak internal infrastructure details (which providers are configured, health status, model lists) to unauthenticated callers.
- **Category:** Security / API
- **Suggested fix:** Add `dependencies=[Depends(require_gateway_token)]` to the router or individual endpoints.

### TD-21: `_run_full_turn` is 180+ lines — excessive cyclomatic complexity
- **File:** `app/agent/turn_loop.py` lines 122–340
- **Problem:** The core `_run_full_turn` method is over 180 lines with deeply nested try/except/while/if blocks. This makes it difficult to test individual steps, review for correctness, or extend safely.
- **Category:** Code Quality / Design
- **Suggested fix:** Extract inner steps into private methods: `_persist_user_message()`, `_run_tool_loop()`, `_persist_final_message()`, `_handle_tool_round()`. Each should be independently testable.

### TD-22: `system_status` endpoint catches bare `except Exception: pass` — silently hides failures
- **File:** `app/api/routers/system.py` lines 209, 216, 254
- **Problem:** Three consecutive `except Exception: pass` blocks swallow errors without logging when querying active session count, active turn count, and provider statuses. If any of these silently fail, the status endpoint returns stale zero values with no indication that data is missing.
- **Category:** Code Quality / Observability
- **Suggested fix:** Replace `pass` with `logger.warning(...)` calls so silent failures are at least observable in logs.

### TD-23: WebSocket `send_json` swallows all exceptions silently
- **File:** `app/api/ws.py` lines 97–98
- **Problem:** `except Exception: pass` on the `send_json` helper means any serialisation bug, encoding error, or unexpected exception type is silently swallowed — not just the expected "connection closed" case.
- **Category:** Code Quality / Observability
- **Suggested fix:** Catch only `ConnectionError`, `WebSocketDisconnect`, and `RuntimeError` (starlette raises this for closed connections). Log unexpected exceptions at DEBUG level.

---

## Medium Severity

### TD-24: CORS `allow_origins` is hardcoded to localhost dev ports
- **File:** `app/api/app.py` lines 233–238
- **Problem:** The CORS allowed origins list is hardcoded to `localhost:5173` and `localhost:5174`. In any non-local deployment this will block legitimate frontend requests or require code changes to deploy.
- **Category:** Design / Configuration
- **Suggested fix:** Read allowed origins from `ServerSettings` (e.g. `TEQUILA_CORS_ORIGINS` env var), with the current localhost values as defaults.

### TD-25: `setup.py` `_create_agent` does raw SQL INSERT bypassing `AgentStore`
- **File:** `app/api/routers/setup.py` lines 147–158
- **Problem:** `_create_agent()` writes directly to the `agents` table with a raw `INSERT` that only populates 7 of 15+ columns and doesn't go through `AgentStore.create()`. If the agents schema evolves, this helper will silently produce incomplete rows. It also lacks `write_transaction` wrapping.
- **Category:** Design / Bug risk
- **Suggested fix:** Use `AgentStore.create()` (already available after step 8b of lifespan). If setup runs before store init, move store init earlier or refactor.

### TD-26: `agent/store.py` dynamic SQL uses f-strings for column names without sanitisation
- **File:** `app/agent/store.py` lines 142, 183
- **Problem:** `f"SELECT * FROM agents {where}"` and `f"UPDATE agents SET {full_set}"` build SQL from runtime-generated strings. While the current callers are safe (column names come from code, not user input), the pattern is fragile: any future refactor that passes user-controlled field names into `update()` would enable SQL injection.
- **Category:** Security (latent) / Code Quality
- **Suggested fix:** Validate `fields` keys against an allow-list of known column names before interpolation. Add an assertion like `assert set(fields) <= _ALLOWED_UPDATE_COLUMNS`.

### TD-27: `ToolExecutor.get_session_approvals` returns `frozenset` but is annotated `set[str]`
- **File:** `app/tools/executor.py` line 261
- **Problem:** The return type annotation says `set[str]` but the implementation returns `frozenset(...)` with a `# type: ignore[return-value]` to suppress the mismatch. This masks a real type inconsistency.
- **Category:** Code Quality
- **Suggested fix:** Change the return annotation to `frozenset[str]` and remove the `# type: ignore`.

### TD-28: `prompt_assembly.py` line 213 — `# type: ignore[arg-type]` masks potential role type error
- **File:** `app/agent/prompt_assembly.py` line 213
- **Problem:** `Message(role=role, content=content)  # type: ignore[arg-type]` — the `role` variable comes from DB rows and can be any string (e.g. `"tool_result"`). If the `Message` model restricts `role` to a `Literal`, this suppression hides invalid roles being injected into the prompt.
- **Category:** Bug risk / Code Quality
- **Suggested fix:** Validate or remap `role` before constructing `Message`. Remove the `type: ignore` after the fix.

### TD-29: `context.py` `_tiktoken_encoding_for_model` has `# type: ignore[return]` — can return `None` implicitly
- **File:** `app/agent/context.py` line 73
- **Problem:** The function signature has no return-type annotation and uses `# type: ignore[return]` to suppress the fact that it can return `None` (when tiktoken is not installed). The caller in `TokenCounter.__init__` does handle `None`, but the suppressed annotation means no static tool will ever flag a regression.
- **Category:** Code Quality
- **Suggested fix:** Add an explicit return type: `-> tiktoken.Encoding | None` (with a `TYPE_CHECKING` guard for the tiktoken import) and remove the `# type: ignore`.

### TD-30: `_app_db_path` imported as private symbol in `deps.py`
- **File:** `app/api/deps.py` line 56
- **Problem:** `from app.db.connection import get_write_db, _app_db_path` imports a private module-level variable. If the connection module is refactored, this will silently break.
- **Category:** Code Quality / Coupling
- **Suggested fix:** Expose a public `get_db_path() -> Path | None` function in `connection.py` and use that instead.

### TD-31: Hardcoded model context windows will become stale
- **File:** `app/agent/context.py` lines 39–62
- **Problem:** `_MODEL_CONTEXT_WINDOWS` is a hardcoded dict mapping model names to context window sizes. As vendors update models or new models are added, this will silently use the `_DEFAULT_CONTEXT_WINDOW` (128k) fallback. This already misses newer models like `gpt-4.1`, Claude 4 variants, etc.
- **Category:** Design
- **Suggested fix:** Prefer reading context window from `ModelCapabilities` returned by the provider's `get_model_capabilities()` method at runtime. Fall back to this table only when the provider doesn't report it.

### TD-32: `TurnLoop._run_full_turn` — dead code: `pre_message_id` is accepted but never used
- **File:** `app/agent/turn_loop.py` line 170
- **Problem:** The `pre_message_id` parameter is threaded through `handle_inbound` → `run_turn_from_api` → `_run_full_turn` but is never actually used in the `insert()` call (line 170 explicitly builds `**({} if not pre_message_id else {})`  which always evaluates to `{}`). The comment says "id not injectable via insert".
- **Category:** Code Quality / Dead code
- **Suggested fix:** Either implement message ID pre-assignment in `MessageStore.insert()` or remove the parameter from the call chain.

---

## Low Severity

### TD-33: No `__all__` exports in any `app/` package `__init__.py`
- **Files:** `app/__init__.py`, `app/api/__init__.py`, `app/db/__init__.py`, `app/sessions/__init__.py`, `app/providers/__init__.py`, `app/agent/__init__.py`, `app/gateway/__init__.py`, `app/tools/__init__.py`, `app/audit/__init__.py`
- **Problem:** No package defines `__all__`, so `from app.X import *` exports everything, and tools like PyCharm's auto-import don't know the public surface.
- **Category:** Code Quality
- **Suggested fix:** Add `__all__` to at least the top-level packages with explicit public names.

### TD-34: `soul.py` `_SilentUndefined.__str__` suppresses override warning
- **File:** `app/agent/soul.py` line 46
- **Problem:** `def __str__(self) -> str:  # type: ignore[override]` — the Jinja2 `Undefined.__str__` has a different signature expectation. This works but the suppression could mask future breakage if Jinja2 changes its `Undefined` base.
- **Category:** Code Quality
- **Suggested fix:** Consider using `jinja2.ChainableUndefined` (Jinja2 3.1+) which has built-in silent behaviour, eliminating the need for a custom subclass.

### TD-35: `app/api/routers/providers.py` calls `health_check_all()` + `list_models()` per provider — N+1 performance
- **File:** `app/api/routers/providers.py` lines 24–43
- **Problem:** `list_providers()` first awaits `health_check_all()` (which calls each provider's `list_models()` internally in `health_check()`), then iterates every provider calling `list_models()` again. This means each provider's `list_models()` is called twice per request.
- **Category:** Code Quality / Performance
- **Suggested fix:** Call `list_models()` once per provider and derive health from whether the call succeeded, or cache the health check result.

### TD-36: `setup.py` still ships stub model catalog — should use live provider listing
- **File:** `app/api/routers/setup.py` lines 39–57
- **Problem:** `_STUB_MODELS` is a static dict of models per provider, documented as "replaced in Sprint 04". The provider registry with `list_models()` was implemented in Sprint 04, but the setup wizard still uses the stub. Models like `o3-mini` and `gemma3` may not match actual available model IDs.
- **Category:** Design / Stale code
- **Suggested fix:** Use `ProviderRegistry.list_all_models()` when the registry is available, falling back to the stub only during first-run before providers are initialised.

### TD-37: `messages.py` `list_by_session` builds SQL with f-string for `active_clause`
- **File:** `app/sessions/messages.py` lines 155–166
- **Problem:** `active_clause = "AND active = 1" if active_only else ""` is interpolated into the SQL query via f-string. While currently safe (the value is a constant), this pattern could mislead future developers into interpolating variables the same way.
- **Category:** Code Quality
- **Suggested fix:** Use two separate query strings (one with the clause, one without) or a query builder.

### TD-38: `sessions/branching.py` — local imports of stdlib modules inside route handlers
- **File:** `app/api/routers/sessions.py` lines 309, 325
- **Problem:** `import asyncio` and `from fastapi import HTTPException` are imported inside the route handler functions `regenerate_response` and `edit_and_resubmit`. These are standard library / framework imports that should be at the top of the module.
- **Category:** Code Quality
- **Suggested fix:** Move imports to module level.

### TD-39: `create_message` in `messages.py` swallows turn-loop failure silently
- **File:** `app/api/routers/messages.py` lines 176–180
- **Problem:** When `trigger_turn=True`, if the turn loop import or task creation fails, the `except Exception: pass` block silently swallows the error. The user's message is persisted but no agent response will ever come, with no indication of failure.
- **Category:** Code Quality / Observability
- **Suggested fix:** Log the exception at WARNING level so operators can diagnose missing responses.

### TD-40: `_SilentUndefined` lambda methods lack type annotations
- **File:** `app/agent/soul.py` lines 49–50
- **Problem:** `__iter__ = lambda self: iter([])` and `__bool__ = lambda self: False` are untyped lambda assignments. Mypy will flag these.
- **Category:** Code Quality
- **Suggested fix:** Convert to proper `def` methods with type annotations.

### TD-41: `web_cache.py` purge uses f-string for SQL placeholder list — correct but fragile
- **File:** `app/db/web_cache.py` line 179
- **Problem:** `f"DELETE FROM web_cache WHERE url IN ({placeholders})"` — `placeholders` is `",".join("?" * len(stale_urls))`, which is the standard parameterised pattern. This is technically safe but the f-string wrapping makes it look like a SQL injection risk at first glance.
- **Category:** Code Quality
- **Suggested fix:** Add a comment clarifying the pattern, or extract into a helper like `_in_clause(n) -> str`.

### TD-42: `Ollama.count_tokens` fallback uses char/4 without logging
- **File:** `app/providers/ollama.py` lines 212–216
- **Problem:** When tiktoken fails to import or encode, the fallback `total_chars // 4` estimation is used without any log message. Users won't know their token counting is approximate.
- **Category:** Code Quality / Observability
- **Suggested fix:** Add `logger.debug("tiktoken unavailable — using char/4 estimate")` in the `except` branch.

---

## Summary

| Severity | Count | IDs |
|----------|-------|-----|
| Critical | 3     | TD-16, TD-17, TD-18 |
| High     | 5     | TD-19, TD-20, TD-21, TD-22, TD-23 |
| Medium   | 9     | TD-24 – TD-32 |
| Low      | 10    | TD-33 – TD-42 |
| **Total**| **27**|     |
