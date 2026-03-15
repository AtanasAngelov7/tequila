# Tech Debt Audit v2 — Sprints 01–07

**Audited**: Sprints 01 through 07 (second pass after v1 fixes)
**Test baseline at audit time**: 401 passing, 0 failures
**Audit scope**: Backend source code, API security, error handling patterns, type safety

---

## Executive Summary

Fifteen new areas of technical debt were identified in the second-pass audit.
The v1 audit (TD-01 through TD-15) addressed schema bugs, naming issues,
deprecations, and encapsulation. This v2 pass focuses on **security gaps**,
**silent error swallowing**, **dead code**, and **type/config inconsistencies**.

Two items are **high** severity (security), five are **medium**, and eight are
**low-priority** quality items.

| ID | Title | Severity | Category |
|----|-------|----------|----------|
| [TD-16](#td-16-gateway-token-comparison-vulnerable-to-timing-attack) | Gateway token comparison vulnerable to timing attack | **High** | Security |
| [TD-17](#td-17-agents-and-providers-api-routers-missing-authentication) | Agents and providers API routers missing authentication | **High** | Security |
| [TD-18](#td-18-hardcoded-placeholder-api-keys-in-provider-constructors) | Hardcoded placeholder API keys in provider constructors | **Medium** | Security / Config |
| [TD-19](#td-19-configstoreset-bypasses-global-write-lock) | `ConfigStore.set()` bypasses global write lock | **Medium** | Concurrency |
| [TD-20](#td-20-_run_full_turn-god-method-220-lines) | `_run_full_turn` god method (~220 lines) | **Medium** | Design |
| [TD-21](#td-21-hardcoded-model-fallback-in-turn-loop) | Hardcoded model fallback in turn loop | **Medium** | Configuration |
| [TD-22](#td-22-dead-pre_message_id-parameter-threaded-through-3-methods) | Dead `pre_message_id` parameter threaded through 3 methods | **Medium** | Dead Code |
| [TD-23](#td-23-silent-except-exception-pass-in-system-status) | Silent `except Exception: pass` in system status | **Low** | Error Handling |
| [TD-24](#td-24-silent-except-exception-pass-in-messages-turn-trigger) | Silent `except Exception: pass` in messages turn trigger | **Low** | Error Handling |
| [TD-25](#td-25-websocket-send_json-silently-swallows-all-exceptions) | WebSocket `send_json` silently swallows all exceptions | **Low** | Error Handling |
| [TD-26](#td-26-get_session_approvals-returns-frozenset-annotated-as-set) | `get_session_approvals` returns `frozenset` annotated as `set` | **Low** | Type Safety |
| [TD-27](#td-27-redundant-except-notfounderror-exception-catch) | Redundant `except (NotFoundError, Exception)` catch | **Low** | Code Quality |
| [TD-28](#td-28-lazy-evict_budget-imports-have-no-error-protection) | Lazy `evict_budget` imports have no error protection | **Low** | Robustness |
| [TD-29](#td-29-websocket-endpoint-has-no-authentication) | WebSocket endpoint has no authentication | **Low** | Security (Tracking) |
| [TD-30](#td-30-cors-origins-hardcoded-to-localhost-ports) | CORS origins hardcoded to localhost ports | **Low** | Configuration |

---

## TD-16: Gateway Token Comparison Vulnerable to Timing Attack

**Severity**: High
**Category**: Security — timing side-channel
**Effort to fix**: ~15 minutes

### Problem

`app/api/deps.py` line 92 compares the gateway token using Python's `!=` operator:

```python
if x_gateway_token != expected:
    raise GatewayTokenRequired()
```

String `!=` short-circuits on the first differing byte, leaking information about
how many leading characters of the token are correct. An attacker can brute-force
the token one character at a time by measuring response latency.

### Fix

```python
import hmac

if not hmac.compare_digest(x_gateway_token, expected):
    raise GatewayTokenRequired()
```

`hmac.compare_digest()` runs in constant time regardless of where the strings
differ. Both arguments must be non-`None`; add a guard for the `None` case
before comparing.

---

## TD-17: Agents and Providers API Routers Missing Authentication

**Severity**: High
**Category**: Security — unauthenticated endpoints
**Effort to fix**: ~30 minutes

### Problem

Two routers have **zero** `require_gateway_token` guards:

| File | Endpoints | Risk |
|------|-----------|------|
| `app/api/routers/agents.py` | 10 endpoints (`GET /api/agents`, `POST`, `PATCH`, `DELETE`, clone, soul, export, import) | Unauthenticated CRUD allows anyone to create, modify, delete, or export agents |
| `app/api/routers/providers.py` | 3 endpoints (`GET /api/providers`, `GET /{id}`, `GET /{id}/models`) | Leaks provider infrastructure: keys in use, model lists, health status |

Every other data-mutating router (`sessions`, `messages`, `system`, `logs`) uses
`Depends(require_gateway_token)`. The agents and providers routers are the only
exceptions.

### Fix

**Option A — Router-level dependency** (preferred): Add the dependency globally
to the `APIRouter` constructor so every endpoint inherits it:

```python
router = APIRouter(
    prefix="/api/agents",
    tags=["agents"],
    dependencies=[Depends(require_gateway_token)],
)
```

**Option B — Per-endpoint**: Add `_token: None = Depends(require_gateway_token)`
to each endpoint signature (more verbose, same effect).

---

## TD-18: Hardcoded Placeholder API Keys in Provider Constructors

**Severity**: Medium
**Category**: Security / Configuration
**Effort to fix**: ~30 minutes

### Problem

Both LLM provider constructors fall back to hardcoded placeholder strings when
no API key is provided and the environment variable is unset:

| File | Line | Fallback |
|------|------|----------|
| `app/providers/anthropic.py` | 159 | `"sk-ant-placeholder"` |
| `app/providers/openai.py` | 137 | `"sk-placeholder"` |

```python
resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "sk-ant-placeholder")
```

This means a misconfigured deployment will make API calls with an obviously-invalid
key, producing confusing 401 errors from the upstream provider. Worse, if a real
key starts with `"sk-ant-placeholder"` (unlikely but possible), the fallback masks
a missing environment variable.

### Fix

Raise `ConfigValidationError` (or a new `ProviderConfigError`) immediately if no
key is available, instead of silently falling back:

```python
resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
if not resolved_key:
    raise ProviderConfigError("ANTHROPIC_API_KEY not set and no api_key provided")
```

---

## TD-19: `ConfigStore.set()` Bypasses Global Write Lock

**Severity**: Medium
**Category**: Concurrency — deadlock / race risk
**Effort to fix**: ~30 minutes

### Problem

Every other write path in the codebase uses `write_transaction()` from
`app/db/connection`, which acquires the per-database asyncio `Lock` before
issuing `BEGIN IMMEDIATE`. The `ConfigStore.set()` method (line 225) calls
`BEGIN IMMEDIATE` directly:

```python
await self._db.execute("BEGIN IMMEDIATE")
try:
    await self._db.execute("UPDATE config ...", ...)
    await self._db.commit()
except Exception:
    await self._db.rollback()
    raise
```

If another coroutine holds the write lock and is mid-transaction, `BEGIN
IMMEDIATE` will raise `OperationalError: database is locked` instead of waiting.
Under high concurrency, this can cause spurious failures on config updates.

### Fix

Replace the manual `BEGIN IMMEDIATE` / `commit` / `rollback` block with:

```python
async with write_transaction(self._db):
    await self._db.execute(
        "UPDATE config SET value = ?, ...",
        (encoded, key, current_version),
    )
```

---

## TD-20: `_run_full_turn` God Method (~220 lines)

**Severity**: Medium
**Category**: Design — excessive method complexity
**Effort to fix**: ~3 hours

### Problem

`app/agent/turn_loop.py` `_run_full_turn()` (lines 125–343) is a ~220-line
method with 7 conceptual steps, deep nesting, and multiple responsibilities:

1. Load session + agent config (with inline fallback construction)
2. Resolve provider from model ID
3. Persist user message
4. Emit run-start event
5. Multi-round tool loop (assemble → compress → stream → execute tools → persist)
6. Persist final message
7. Post-turn hooks + state cleanup

The method has 4 levels of `try/except` nesting and embeds fallback
`AgentConfig` construction inline. This makes it difficult to test individual
steps in isolation and increases the risk of regressions.

### Fix

Extract each step into a private helper:

```python
async def _load_session_and_agent(self, session_id: str) -> tuple[Session, AgentConfig]: ...
async def _resolve_provider(self, model: str) -> tuple[LLMProvider, str]: ...
async def _run_tool_loop(self, ...) -> tuple[str, int, int]: ...
async def _persist_final_response(self, ...) -> Message: ...
```

The main `_run_full_turn` becomes an orchestrator of 5–10 lines, calling
these named sub-steps in sequence.

---

## TD-21: Hardcoded Model Fallback in Turn Loop

**Severity**: Medium
**Category**: Configuration — hardcoded constant
**Effort to fix**: ~15 minutes

### Problem

`app/agent/turn_loop.py` line 155 hardcodes a model fallback:

```python
qualified_model = getattr(agent_config, "default_model", "") or "anthropic:claude-sonnet-4-5"
```

If a deployment uses only OpenAI or Ollama (no Anthropic key configured), any
agent that doesn't explicitly set `default_model` will attempt to call the
Anthropic provider, fail, and produce a confusing provider-unavailable error.

### Fix

Move the default to a named constant in `app/constants.py`:

```python
DEFAULT_MODEL = "anthropic:claude-sonnet-4-5"
```

Better yet, make it a config key in the `config` table so operators can change
the system-wide default model via the API without restarting.

---

## TD-22: Dead `pre_message_id` Parameter Threaded Through 3 Methods

**Severity**: Medium
**Category**: Dead code
**Effort to fix**: ~15 minutes

### Problem

`_run_full_turn()` accepts `pre_message_id: str | None = None` (line 132),
which is also passed through `run_turn_from_api()` (line 112) and
`handle_inbound()` (line 86). However, the parameter is never used:

```python
**({} if not pre_message_id else {}),  # id not injectable via insert
```

Both branches of the conditional produce an empty dict. The comment confirms
the original intent was abandoned. This dead parameter adds noise to three
method signatures and misleads readers into thinking message-id pre-assignment
is supported.

### Fix

Remove `pre_message_id` from all three method signatures and delete the
unused conditional on line 170. If message-id pre-assignment is needed in the
future, it should be implemented properly, not left as dead plumbing.

---

## TD-23: Silent `except Exception: pass` in System Status

**Severity**: Low
**Category**: Error handling — silent failures
**Effort to fix**: ~20 minutes

### Problem

`app/api/routers/system.py` `system_status()` has four bare `except Exception`
blocks (lines 197, 209, 216, 254) that silently swallow errors with `pass`:

```python
try:
    active_session_count = ...
except Exception:
    pass   # ← no log, no metric, no trace
```

While a status endpoint should be resilient, silently hiding failures makes it
impossible to diagnose why the status page shows `0` active sessions when the
database is actually accessible but the query is malformed.

### Fix

Log at `WARNING` level in each catch block:

```python
except Exception:
    logger.warning("Failed to fetch active session count", exc_info=True)
```

---

## TD-24: Silent `except Exception: pass` in Messages Turn Trigger

**Severity**: Low
**Category**: Error handling — silent failures
**Effort to fix**: ~10 minutes

### Problem

`app/api/routers/messages.py` line 180 catches *all* exceptions during turn-loop
triggering and discards them silently:

```python
try:
    turn_loop = get_turn_loop()
    asyncio.create_task(turn_loop.run_turn_from_api(...))
except Exception:
    # Turn loop not yet wired — ignore for backward compat
    pass
```

The comment says "not yet wired", but this also swallows genuine bugs: import
errors, attribute errors, or configuration mistakes. If the turn loop fails to
start, the user's message is persisted but no response is ever generated —
the conversation silently stalls.

### Fix

```python
except Exception:
    logger.warning("Turn loop trigger failed — message persisted but turn not started", exc_info=True)
```

---

## TD-25: WebSocket `send_json` Silently Swallows All Exceptions

**Severity**: Low
**Category**: Error handling — silent failures
**Effort to fix**: ~10 minutes

### Problem

`app/api/ws.py` line 97:

```python
async def send_json(data: dict[str, Any]) -> None:
    try:
        await ws.send_text(json.dumps(data))
    except Exception:
        pass  # Connection already closed
```

The comment says "connection already closed", but `except Exception` also
catches `TypeError` (non-serialisable data), `UnicodeEncodeError`, and other
bugs unrelated to connection state. These are silently hidden.

### Fix

Narrow the catch to `ConnectionError` / `WebSocketDisconnect` (the actual
closed-connection exceptions), and log or re-raise anything else:

```python
except (ConnectionError, WebSocketDisconnect):
    pass  # Expected when client disconnects
except Exception:
    logger.warning("Unexpected error in send_json", exc_info=True)
```

---

## TD-26: `get_session_approvals` Returns `frozenset` Annotated as `set`

**Severity**: Low
**Category**: Type safety
**Effort to fix**: ~5 minutes

### Problem

`app/tools/executor.py` line 261:

```python
def get_session_approvals(self, session_key: str) -> set[str]:
    """Return the set of tools permanently approved for *session_key*."""
    return frozenset(self._session_approvals.get(session_key, set()))  # type: ignore[return-value]
```

The return type annotation says `set[str]` but the body returns a `frozenset`.
The `# type: ignore[return-value]` suppresses the mismatch. `frozenset` is not
a subtype of `set` — callers expecting `.add()` or `.discard()` would get an
`AttributeError` at runtime.

### Fix

Change the return annotation to match the actual return type:

```python
def get_session_approvals(self, session_key: str) -> frozenset[str]:
```

Remove the `# type: ignore[return-value]` suppression.

---

## TD-27: Redundant `except (NotFoundError, Exception)` Catch

**Severity**: Low
**Category**: Code quality
**Effort to fix**: ~10 minutes

### Problem

`app/agent/turn_loop.py` line 143:

```python
try:
    agent_config = await self._agent_store.get_by_id(session.agent_id)
except (NotFoundError, Exception):
    from app.agent.models import AgentConfig, SoulConfig
    agent_config = AgentConfig(...)
```

`Exception` is a superclass of `NotFoundError`, so listing both in the tuple is
redundant — `except Exception` alone catches everything. This obscures the
developer's intent: was the goal to handle "agent not found" specifically and
fall back, while letting other errors propagate? The current code hides that
distinction.

### Fix

Split into two `except` clauses:

```python
except NotFoundError:
    logger.info("Agent %r not found, using default config", session.agent_id)
    agent_config = AgentConfig(...)
except Exception:
    logger.warning("Unexpected error loading agent %r, using default config", session.agent_id, exc_info=True)
    agent_config = AgentConfig(...)
```

---

## TD-28: Lazy `evict_budget` Imports Have No Error Protection

**Severity**: Low
**Category**: Robustness
**Effort to fix**: ~10 minutes

### Problem

`app/sessions/store.py` lines 410–411 and 454–455 contain lazy imports added
by the v1 tech debt fix (TD-12):

```python
from app.agent.context import evict_budget
evict_budget(session_id)
```

These are placed after the database transaction completes. If
`app.agent.context` fails to import (broken module, missing dependency), the
entire `archive()` or `delete()` call crashes — even though the database
operation already succeeded. Budget eviction is a cleanup side-effect and
should not cause the primary operation to fail.

### Fix

Wrap in a protective `try/except`:

```python
try:
    from app.agent.context import evict_budget
    evict_budget(session_id)
except Exception:
    logger.warning("Failed to evict budget for session %s", session_id, exc_info=True)
```

---

## TD-29: WebSocket Endpoint Has No Authentication

**Severity**: Low (Tracking)
**Category**: Security
**Effort to fix**: ~1 hour

### Problem

The `websocket_endpoint` at `/api/ws` (`app/api/ws.py` line 84) has no
authentication. The HTTP-upgrade request does not check `X-Gateway-Token` or
any other credential. Any client that can reach the server can open a WebSocket,
create sessions, send messages, and trigger agent turns.

This is partially by design for the local-dev use case (where `gateway_token`
is empty), but in production deployments it means the WebSocket is a
fully-open backdoor even when the REST API is token-protected.

### Fix

Add token validation during the WebSocket handshake. FastAPI supports
dependency injection on WebSocket routes:

```python
@router.websocket("/api/ws")
async def websocket_endpoint(
    ws: WebSocket,
    _token: None = Depends(require_gateway_token_ws),  # new WS-aware variant
) -> None:
```

The WS-aware variant should read the token from a query parameter
(`?token=...`) or from the `Sec-WebSocket-Protocol` header, since browsers
cannot set custom headers on WebSocket upgrade requests.

---

## TD-30: CORS Origins Hardcoded to Localhost Ports

**Severity**: Low
**Category**: Configuration
**Effort to fix**: ~15 minutes

### Problem

`app/api/app.py` lines 233–238 hardcode CORS allowed origins:

```python
allow_origins=[
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
],
```

If the frontend runs on a different port, or if Tequila is deployed behind a
reverse proxy with a real domain, CORS will block all requests. Changing this
requires editing source code and restarting.

### Fix

Read CORS origins from an environment variable or config key:

```python
import os

cors_origins_raw = os.environ.get("TEQUILA_CORS_ORIGINS", "http://localhost:5173,http://localhost:5174")
allow_origins = [o.strip() for o in cors_origins_raw.split(",")]
```

---

## Appendix: Broad `except Exception` Inventory

The following locations use `except Exception` with varying degrees of
handling. Not all are bugs — some are intentional resilience patterns — but
they should be reviewed for appropriate granularity:

| File | Line | Handling | Concern |
|------|------|----------|---------|
| `app/config.py` | 128 | `logger.warning(...)` | OK — hydration resilience |
| `app/config.py` | 236 | `rollback()` + re-raise | OK — transaction safety |
| `app/gateway/router.py` | 131 | `logger.exception(...)` | OK — handler isolation |
| `app/audit/log.py` | 174 | Fallback JSON wrapping | OK — read resilience |
| `app/api/routers/system.py` | 197, 209, 216, 254 | `pass` | **TD-23** |
| `app/api/routers/messages.py` | 180 | `pass` | **TD-24** |
| `app/api/ws.py` | 97 | `pass` | **TD-25** |
| `app/api/ws.py` | 109, 325 | `break` / `logger.exception` | OK |
| `app/sessions/store.py` | 550 | Needs review | Swallowed during cleanup |
| `app/sessions/messages.py` | 126 | Needs review | Swallowed during cleanup |
| `app/providers/base.py` | 289 | Needs review | Provider error boundary |
| `app/providers/registry.py` | 136 | Needs review | Registry init resilience |
| `app/providers/ollama.py` | 212, 285 | Needs review | Ollama-specific error handling |
| `app/agent/turn_loop.py` | 157, 235 | `_emit_error` / `cb.record_failure` | Partially OK |
| `app/db/web_cache.py` | 172 | Marks entries stale (no log) | Minor |
| `app/tools/builtin/web_fetch.py` | 244 | Needs review | Fetch error boundary |

---

## Appendix: `# type: ignore` Inventory

| File | Line | Suppression | Assessment |
|------|------|-------------|------------|
| `app/paths.py` | 37 | `[attr-defined]` — `sys._MEIPASS` | OK (PyInstaller) |
| `app/api/app.py` | 245 | `[arg-type]` — exception handler | OK (FastAPI typing) |
| `app/providers/base.py` | 242 | `[misc]` — yield type | Needs review |
| `app/agent/soul.py` | 46 | `[override]` — `__str__` | Needs review |
| `app/providers/anthropic.py` | 156 | `[import]` — optional dep | OK |
| `app/providers/openai.py` | 134, 230 | `[import]` — optional deps | OK |
| `app/providers/ollama.py` | 203 | `[import]` — optional dep | OK |
| `app/agent/prompt_assembly.py` | 213 | `[arg-type]` — Message role | Needs review |
| `app/tools/registry.py` | 220 | `[attr-defined]` — monkey-patch | Design smell |
| `app/tools/executor.py` | 261 | `[return-value]` — frozenset | **TD-26** |
| `app/agent/context.py` | 73 | `[return]` — tiktoken | Needs review |
