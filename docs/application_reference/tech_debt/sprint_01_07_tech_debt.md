# Tech Debt Audit — Sprints 01–07

**Audited**: Sprints 01 through 07 (Phase 1 + Phase 2 Agent Core)
**Test baseline at audit time**: 401 passing, 0 failures
**Audit scope**: Backend source code, Alembic migrations, sprint deliverables vs. actual implementation

---

## Executive Summary

Fifteen areas of technical debt were identified across the entire codebase.
One is a **critical bug** that will cause runtime failures in production,
five are **high** severity issues, six are **medium** design/quality issues,
and three are **low-priority** tracking items.

| ID | Title | Severity | Category |
|----|-------|----------|----------|
| [TD-01](#td-01-audit_log-schema-split--critical-bug) | `audit_log` schema split | **Critical** | Bug |
| [TD-02](#td-02-duplicate-sessionpolicy-class) | Duplicate `SessionPolicy` class | **High** | Design |
| [TD-03](#td-03-datetimeutcnow-deprecation) | `datetime.utcnow()` deprecation | **High** | Code Quality |
| [TD-04](#td-04-migration-0007-revision-id-inconsistency) | Migration 0007 revision ID | **High** | Infrastructure |
| [TD-05](#td-05-duplicate-contextbudget-class-name) | Duplicate `ContextBudget` name | **Medium** | Design |
| [TD-06](#td-06-test-reset-functions-in-production-modules) | Test reset functions in production | **Medium** | Code Quality |
| [TD-07](#td-07-module-level-singletons-accumulate-state) | Singleton state accumulation | **Medium** | Design |
| [TD-08](#td-08-deferred-features-not-tracked) | Deferred features untracked | **Low** | Tracking |
| [TD-09](#td-09-permissionerror-shadows-builtin) | `PermissionError` shadows builtin | **High** | Bug Risk |
| [TD-10](#td-10-private-_turn_queues-accessed-from-system-router) | `_turn_queues` private import in system router | **High** | Encapsulation |
| [TD-11](#td-11-sessionresponse-omits-policy-field) | `SessionResponse` omits `policy` field | **Medium** | API |
| [TD-12](#td-12-no-context-budget-eviction-on-session-close) | No context budget eviction on session close | **Medium** | Memory Leak |
| [TD-13](#td-13-prompt-assembly-uses-s04-contextbudget-not-s07) | Prompt assembly uses S04 `ContextBudget`, not S07 | **Medium** | Design |
| [TD-14](#td-14-gatewayrouter-seq-property-consumes-counter) | `GatewayRouter.seq` property consumes counter | **Low** | Bug Risk |
| [TD-15](#td-15-duplicate-database-errors-section-in-exceptionspy) | Duplicate section header in `exceptions.py` | **Low** | Code Quality |

---

## TD-01: `audit_log` Schema Split — Critical Bug

**Severity**: Critical  
**Category**: Bug — data loss / runtime failure  
**Effort to fix**: ~2 hours

### Problem

The `audit_log` database table is created by migration `0001_baseline.py` (Sprint 01)
but a second, **incompatible** schema is attempted in `0007_sprint07_audit_log.py`
(Sprint 07). Because both migrations use `CREATE TABLE IF NOT EXISTS`, in any
fresh database the 0001 version wins and 0007 is silently skipped. The two
schemas have completely different columns:

| 0001 schema (wins) | 0007 schema (skipped) |
|--------------------|-----------------------|
| `id` | `id` |
| `actor` | `actor` |
| `action` | `event_type` ← different name |
| `resource_type` | — |
| `resource_id` | — |
| `outcome` | `decision` ← different name |
| `detail` (JSON text) | `details_json` ← different name |
| `ip_address` | — |
| `session_key` | `session_key` |
| `created_at` | `created_at` |
| — | `tool_name` ← new column |

`app/audit/log.py` (`write_audit_event`) writes using the **0001 column names**.  
`app/tools/executor.py` (`_audit()`) writes using the **0007 column names**
(`event_type`, `tool_name`, `decision`, `details_json`).

**On a fresh database the executor's approval-audit writes will fail at
runtime** with `table audit_log has no column named event_type`.

### Root Cause

Sprint 07 added approval-decision auditing with a purpose-built, narrower schema
instead of reusing the general-purpose `AuditEvent` model from Sprint 01.

### Fix

Two options:

**Option A — Extend the 0001 schema (preferred)**: Add a new migration (`0008`)
that `ALTER TABLE audit_log ADD COLUMN` for `tool_name`, `decision`, and
`event_type` (as an alias or additional column). Update `executor._audit()` to
write using the existing 0001 column names (`action` instead of `event_type`,
`outcome` instead of `decision`, etc.) and use `detail` for the JSON blob. Drop
migration `0007` entirely.

**Option B — Separate table**: Rename the Sprint 07 table to `approval_log` with
its own focused schema. Update the 0007 migration and the executor accordingly.
The `GET /api/audit` endpoint stays on `audit_log`; a new `GET /api/audit/approvals`
or similar serves the approval log.

---

## TD-02: Duplicate `SessionPolicy` Class

**Severity**: High  
**Category**: Design — class duplication  
**Effort to fix**: ~1 hour

### Problem

`SessionPolicy` is defined in two different modules with different field counts
and no import relationship between them:

| Location | Fields | Used by |
|----------|--------|---------|
| `app/sessions/policy.py` | Full set + `check_policy()` enforcement function + `SessionPolicyPresets` | `sessions/models.py`, `sessions/store.py`, `api/routers/sessions.py` |
| `app/agent/models.py` | Identical fields but **no enforcement logic**, no presets | `AgentConfig.default_policy` only |

`app/agent/models.py` defines `SessionPolicy` locally and uses it as
`AgentConfig.default_policy`. The rest of the system uses the authoritative
version from `app/sessions/policy.py`. If a field is added to one and not the
other, silent divergence will occur.

### Fix

Remove the `SessionPolicy` definition from `app/agent/models.py`. Import and
re-export from `app/sessions/policy.py`:

```python
# app/agent/models.py
from app.sessions.policy import SessionPolicy  # canonical definition
```

`AgentConfig.default_policy` continues to work unchanged. Single source of truth.

---

## TD-03: `datetime.utcnow()` Deprecation

**Severity**: High  
**Category**: Code quality — deprecation warnings  
**Effort to fix**: ~30 minutes

### Problem

Python 3.12 deprecated `datetime.datetime.utcnow()`. There are **17 occurrences**
across 5 files, all generating `DeprecationWarning` in tests and at runtime:

| File | Line(s) |
|------|---------|
| `app/sessions/store.py` | 118, 289, 340, 363, 388, 411 |
| `app/sessions/models.py` | 54, 55, 244, 283 |
| `app/sessions/messages.py` | 68, 191, 200, 226 |
| `app/agent/store.py` | 51, 162 |
| `app/tools/registry.py` | 11 (in docstring example) |

### Fix

Replace all occurrences with the timezone-aware equivalent:

```python
# Before
datetime.utcnow()
# After
datetime.now(timezone.utc)
```

`datetime` and `timezone` are already imported in most of these files. The
`app/tools/registry.py` docstring example also needs updating.

---

## TD-04: Migration 0007 Revision ID Inconsistency

**Severity**: High  
**Category**: Infrastructure — migration chain fragility  
**Effort to fix**: ~15 minutes

### Problem

All migrations use short numeric revision IDs except 0007:

| Migration file | `revision` value |
|----------------|-----------------|
| `0001_baseline.py` | `"0001"` |
| `0002_sprint02_indexes.py` | `"0002"` |
| `0003_sprint03_agents.py` | `"0003"` |
| `0004_sprint04_agent_full.py` | `"0004"` |
| `0005_sprint05_messages_full.py` | `"0005"` |
| `0006_sprint06_web_cache.py` | `"0006"` |
| `0007_sprint07_audit_log.py` | **`"0007_sprint07_audit_log"`** ← inconsistent |

The `down_revision` in 0007 correctly points to `"0006"`, so the chain is not
broken. However the long-form revision ID breaks the convention and previously
caused a `KeyError` when migration utilities expected `"0007"` as the key.

### Fix

Change `revision` in `0007_sprint07_audit_log.py` from
`"0007_sprint07_audit_log"` to `"0007"`. If the database already has a
`alembic_version` row with the old value, include a data-fix migration or
update the row manually. All subsequent migrations should use `"0008"`, etc.

---

## TD-05: Duplicate `ContextBudget` Class Name

**Severity**: Medium  
**Category**: Design — name collision  
**Effort to fix**: ~1–2 hours

### Problem

Two unrelated classes share the name `ContextBudget`:

| Location | Type | Purpose |
|----------|------|---------|
| `app/agent/models.py` (Sprint 04) | `pydantic.BaseModel` | Declarative slot allocation config — e.g. `system_prompt_tokens: int = 2000` |
| `app/agent/context.py` (Sprint 07) | Plain Python class | Runtime engine — token counting, compression, budget enforcement |

The `tests/unit/test_context_budget.py` file contains tests for *both* classes
appended into the same file. Any future code that does `from app.agent import ContextBudget`
will be ambiguous.

### Fix

Rename one of the classes to avoid the collision:

- **`app/agent/models.py`**: rename to `ContextBudgetConfig` (it is a
  configuration model, not an execution engine). Update `AgentConfig` field
  `context_budget: ContextBudget` → `context_budget: ContextBudgetConfig`.
- **`app/agent/context.py`**: keep as `ContextBudget` (the primary runtime class).

Update all imports and test file section headings accordingly.

---

## TD-06: Test Reset Functions in Production Modules

**Severity**: Medium  
**Category**: Code quality — test isolation bleed  
**Effort to fix**: ~1 hour

### Problem

Two production modules expose test-only reset functions as public module-level
symbols:

| Function | Module |
|----------|--------|
| `reset_tool_executor()` | `app/tools/executor.py` (line 438) |
| `reset_circuit_registry()` | `app/providers/circuit_breaker.py` (line 363) |

These functions exist solely to clear module-level singleton state between tests.
Exposing them in production code:
- Pollutes the public API of the module
- Makes it easy to accidentally call in non-test code
- Signals that the singleton design is fragile

### Fix

Move these functions to `tests/conftest.py` or a `tests/utils/reset_helpers.py`
module. Alternatively, expose them in a `__test_only__` namespace or gate them
behind an `if TYPE_CHECKING` import block so they are excluded from production
imports. As a longer-term fix, see TD-07 below which addresses the root cause.

---

## TD-07: Module-Level Singletons Accumulate State

**Severity**: Medium  
**Category**: Design — singleton fragility  
**Effort to fix**: 3–5 hours (refactor)

### Problem

Several module-level singletons accumulate in-process state that leaks between
tests and can cause subtle production bugs:

| Singleton | Module | State accumulated |
|-----------|--------|-------------------|
| `_tool_registry` | `app/tools/registry.py` | All registered tools (appended at import time) |
| `_provider_registry` | `app/providers/registry.py` | All registered providers |
| `_circuit_registry` | `app/providers/circuit_breaker.py` | CircuitBreaker instances keyed by provider |
| `_turn_queues` | `app/sessions/store.py` | Per-session asyncio.Queue instances |
| `_write_locks` | `app/db/connection.py` | Per-path asyncio.Lock instances |

`_turn_queues` and `_write_locks` grow indefinitely — there is no eviction.  
`_circuit_registry` and `_tool_registry` require explicit `reset_*()` calls in
tests to avoid cross-test pollution.

The `WebCache` class (`app/db/web_cache.py`) is also a singleton that can hold
a stale `aiosqlite.Connection` after the test database is closed, causing
`ValueError: no active connection` in subsequent tests (worked around with a
try/except in tests).

### Fix

Short-term: add proper `conftest.py` teardown fixtures that call all reset
functions symmetrically after every test.

Long-term: move toward dependency injection. Pass registry/executor instances
through FastAPI's `Depends()` mechanism so state is scoped to the request
lifecycle rather than the module lifecycle. The `_turn_queues` and
`_write_locks` dicts should have LRU eviction or TTL cleanup tied to session
lifecycle events (session close/archive).

---

## TD-08: Deferred Features Not Tracked

**Severity**: Low  
**Category**: Tracking — deferred deliverables  
**Effort to fix**: N/A (documentation only)

### Problem

Multiple sprint deliverables were explicitly deferred and are not tracked in any
backlog. Current state:

| Item | Originally Planned | Deferred From | Current Status |
|------|--------------------|---------------|----------------|
| LLM session title auto-generation | Sprint 03 D3 | → Sprint 04 D8 | → **still deferred** |
| Session summary generation (periodic + on archive) | Sprint 04 D8 | — | **not implemented** |
| Title re-generation on topic shift | Sprint 04 D8 | — | **not implemented** |
| Escalation gateway event + `POST /api/sessions/{id}/escalate` | Sprint 04 D6 | — | **not implemented** |
| Agent model selector dropdown in chat | Sprint 04 D7 | — | **not implemented** |
| Frontend: tool result display (file, code, search, web, vision) | Sprint 06 | → frontend sprint | **not implemented** |
| Frontend: context budget indicator | Sprint 07 | → frontend sprint | **not implemented** |
| Frontend: error state display + retry button | Sprint 07 | → frontend sprint | **not implemented** |
| Frontend: approval timeout countdown | Sprint 07 | → frontend sprint | **not implemented** |
| Frontend: session policy display | Sprint 07 | → frontend sprint | **not implemented** |

The frontend items are by design deferred to a dedicated frontend sprint, which
is acceptable. The backend items (LLM title, session summary, escalation
endpoint) were deferred sprint-to-sprint and are now untracked.

### Fix

Add these items to the sprint backlog before Sprint 08 planning so they are not
forgotten. Recommend:
- LLM title + summary generation: add to Sprint 08 or 09 (requires provider + turn loop, both now available)
- Escalation endpoint: add to Sprint 08 (all prerequisites exist in Sprint 04's `escalation.py`)
- Frontend deferred items: schedule a dedicated frontend integration sprint

---

## TD-09: `PermissionError` Shadows Builtin

**Severity**: High  
**Category**: Bug risk — builtin name collision  
**Effort to fix**: ~30 minutes

### Problem

`app/exceptions.py` line 56 defines:

```python
class PermissionError(TequilaError):  # noqa: A001 — intentional shadow of builtin
```

This **shadows Python's own `PermissionError`** (a subclass of `OSError` raised
by the OS for file-permission failures). The `# noqa` suppression shows this was
deliberate, but it creates two risks:

1. **Any code that writes `except PermissionError`** in the Tequila codebase—even
   to handle an OS-level file-system error—will silently catch the Tequila
   HTTP-403 exception instead, or vice versa.
2. **Library/framework code** (e.g. `asyncio`, `aiosqlite`, `pathlib`) can raise
   the builtin `PermissionError`. If a handler catches the Tequila version, it
   will miss those OS errors because `TequilaError` and `OSError` share no
   inheritance chain.

Currently used in:
- `app/tools/builtin/filesystem.py` (lines 60, 70)
- `app/sessions/policy.py` (line 263)

### Fix

Rename to `AccessDeniedError` (or `PolicyForbiddenError`) to avoid shadowing.
Update all raise and except sites:

```python
# app/exceptions.py
class AccessDeniedError(TequilaError):
    """Authentication or scope check failed. HTTP 403."""
    http_status = 403
```

Update the exception handler in `app/api/app.py` to map `AccessDeniedError` → 403.
Search for all `PermissionError` references and update imports.

---

## TD-10: Private `_turn_queues` Accessed from System Router

**Severity**: High  
**Category**: Encapsulation — accessing private state  
**Effort to fix**: ~20 minutes

### Problem

`app/api/routers/system.py` lines 214-216 import and iterate over a **private**
module-level dict from the session store:

```python
from app.sessions.store import _turn_queues
active_turn_count = sum(1 for q in _turn_queues.values() if not q.empty())
```

Line 280 similarly accesses a private attribute of `ConfigStore`:

```python
config_keys=len(config._cache),
```

These violate encapsulation boundaries. If the store internals change (e.g.
`_turn_queues` is renamed or replaced with a `dict[str, asyncio.Event]`), the
health endpoint will silently break.

### Fix

Add public accessor methods to the owning modules:

```python
# app/sessions/store.py
def active_turn_count(self) -> int:
    """Return count of non-empty turn queues."""
    return sum(1 for q in _turn_queues.values() if not q.empty())
```

```python
# app/config/store.py  (or wherever ConfigStore lives)
def key_count(self) -> int:
    """Return number of cached config keys."""
    return len(self._cache)
```

Update `system.py` to call these methods instead of importing private symbols.

---

## TD-11: `SessionResponse` Omits `policy` Field

**Severity**: Medium  
**Category**: API completeness  
**Effort to fix**: ~15 minutes

### Problem

`app/api/routers/sessions.py` defines `SessionResponse` (line 49) with 14
fields, but **does not include the session's active policy**:

```python
class SessionResponse(BaseModel):
    session_id: str
    session_key: str
    kind: str
    agent_id: str
    # ... title, summary, message_count, etc.
    metadata: dict[str, Any]
    # ← no policy field
```

The `Session` model in `sessions/models.py` carries a `policy` field
(a `SessionPolicy` dict), but it is never serialised into API responses.
Frontend or API consumers cannot see what policy is governing a session.

### Fix

Add `policy` to `SessionResponse` and to the mapping function:

```python
class SessionResponse(BaseModel):
    # ... existing fields ...
    policy: dict[str, Any] | None = None

def _session_to_response(s: Session) -> SessionResponse:
    return SessionResponse(
        # ... existing fields ...
        policy=s.policy.model_dump() if s.policy else None,
    )
```

---

## TD-12: No Context Budget Eviction on Session Close

**Severity**: Medium  
**Category**: Memory leak — unbounded cache  
**Effort to fix**: ~15 minutes

### Problem

`app/agent/context.py` line 452 maintains a module-level cache of runtime
`ContextBudget` instances keyed by `session_id`:

```python
_budgets: dict[str, ContextBudget] = {}
```

A convenience function `evict_budget(session_id)` exists at line 466, but it is
**never called** anywhere in the codebase. As sessions accumulate (each running
at least one turn), `_budgets` grows without bound.

Each `ContextBudget` holds a `tiktoken.Encoding` instance, token-count caches,
and compression state—so memory per entry is non-trivial.

### Fix

Wire `evict_budget()` into session lifecycle events:

```python
# app/sessions/store.py — in archive() and delete() methods
from app.agent.context import evict_budget

async def archive(self, session_id: str, ...) -> Session:
    # ... existing logic ...
    evict_budget(session_id)
    return session

async def delete(self, session_id: str) -> None:
    # ... existing logic ...
    evict_budget(session_id)
```

Also consider adding a periodic sweep that evicts budgets for sessions whose
`status != 'active'`.

---

## TD-13: Prompt Assembly Uses S04 `ContextBudget`, Not S07

**Severity**: Medium  
**Category**: Design — stale import  
**Effort to fix**: ~30 minutes (after TD-05 rename)

### Problem

`app/agent/prompt_assembly.py` line 27 imports:

```python
from app.agent.models import AgentConfig, ContextBudget
```

This is the Sprint 04 **Pydantic config model** (`max_context_tokens`,
`system_prompt_budget`, etc.). The Sprint 07 **runtime engine**
(`app.agent.context.ContextBudget`) is a completely different class that
performs actual token counting, compression, and budget enforcement.

`prompt_assembly.py` uses only static slot sizes from the config model,
meaning prompt assembly has **no integration with the runtime budget engine**
— real-time token tracking in `turn_loop.py` and budget decisions in
`context.py` are invisible to it.

### Fix

After completing TD-05 (renaming the config model to `ContextBudgetConfig`):

1. The import in `prompt_assembly.py` will naturally update to
   `ContextBudgetConfig` — this is correct if it only needs static limits.
2. If prompt assembly should also honour the runtime budget, inject the runtime
   `ContextBudget` from `turn_loop.py` at call time so compression state is
   shared. This is a design decision for Sprint 08 planning.

---

## TD-14: `GatewayRouter.seq` Property Consumes Counter

**Severity**: Low  
**Category**: Bug risk — read with side effect  
**Effort to fix**: ~10 minutes

### Problem

`app/gateway/router.py` line 93 defines a `seq` property:

```python
@property
def seq(self) -> int:
    """Peek at the next sequence number without consuming it."""
    return next(self._seq_counter) - 0  # see note — callers use _next_seq()
```

Despite the docstring saying "Peek … without consuming", `next()` **does
consume** the counter. Every call to `.seq` advances the sequence, creating
gaps. The `_next_seq()` method on line 96 also calls `next()`, so the two
methods compete.

### Fix

Track a separate `_seq_value: int` attribute:

```python
def __init__(self) -> None:
    self._seq_value = 0

@property
def seq(self) -> int:
    """Return the last-emitted sequence number (read-only)."""
    return self._seq_value

def _next_seq(self) -> int:
    self._seq_value += 1
    return self._seq_value
```

Remove `self._seq_counter` entirely. Update `emit()` to use `_next_seq()`.

---

## TD-15: Duplicate "Database errors" Section in `exceptions.py`

**Severity**: Low  
**Category**: Code quality — copy-paste artifact  
**Effort to fix**: ~5 minutes

### Problem

`app/exceptions.py` has two identical section headers:

```python
# ── Database errors ───────────────────────────────────────    (line ~140)
class AgentNotFoundError(NotFoundError): ...

# ── Database errors ───────────────────────────────────────    (line ~153)
class DatabaseError(TequilaError): ...
```

`AgentNotFoundError` is semantically an **Agent error**, not a generic database
error. The duplicate header likely came from a copy-paste when Sprint 03 added
the agent store.

### Fix

Rename the first section:

```python
# ── Agent errors ──────────────────────────────────────────
class AgentNotFoundError(NotFoundError): ...

# ── Database errors ───────────────────────────────────────
class DatabaseError(TequilaError): ...
```

---

## Prioritised Fix Order

| Priority | ID | Action |
|----------|----|--------|
| 1 | TD-01 | Fix `audit_log` schema split — Sprint 07 approval auditing is broken in production |
| 2 | TD-04 | Normalise migration 0007 revision ID — prevents migration tooling issues |
| 3 | TD-09 | Rename `PermissionError` → `AccessDeniedError` — avoid shadowing Python builtin |
| 4 | TD-02 | Remove duplicate `SessionPolicy` from `agent/models.py` |
| 5 | TD-03 | Replace all `datetime.utcnow()` calls — eliminate deprecation warnings |
| 6 | TD-10 | Add public accessors to `SessionStore`/`ConfigStore` — stop importing `_turn_queues` |
| 7 | TD-05 | Rename `ContextBudget` in `agent/models.py` to `ContextBudgetConfig` |
| 8 | TD-13 | Decide on prompt-assembly ↔ runtime budget integration after TD-05 |
| 9 | TD-12 | Wire `evict_budget()` into session archive/delete |
| 10 | TD-11 | Add `policy` field to `SessionResponse` |
| 11 | TD-14 | Fix `GatewayRouter.seq` property side effect |
| 12 | TD-06 | Move test reset functions out of production modules |
| 13 | TD-07 | Add conftest teardown fixtures; plan singleton refactor |
| 14 | TD-15 | Fix duplicate section header in `exceptions.py` |
| 15 | TD-08 | Add deferred backend items to sprint backlog |

---

*Document created after Sprint 07. Revisit after Sprint 08 to record fixes.*
