# Post-Batch 8 Tech Debt Assessment

**Date**: 2025-01-20  
**Baseline**: 935 passed · 8 skipped · all 67 prior items (TD-270 – TD-336) resolved  
**Scope**: Full codebase scan (~60 source files across all modules)  
**New IDs**: TD-337 – TD-390 (54 issues)

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 2     |
| High     | 9     |
| Medium   | 18    |
| Low      | 25    |
| **Total**| **54**|

Two issues are **regressions introduced by Batch 8** (marked with ⚠️).

---

## CRITICAL (2)

### TD-337 · `lifecycle.py` L157 — `_compute_decay` ZeroDivisionError

```python
score = 0.5 ** (days / half_life_days)  # half_life_days=0 → ZeroDivisionError
```

`MemoryDecayConfig` has no lower-bound guard. If a caller passes `half_life_days=0`
(or the config is misconstrued), the entire decay run crashes.

**Fix**: Guard with `if half_life_days <= 0: return 1.0` (no decay).

---

### TD-338 · `system.py` L306 — `list_plugins()` AttributeError + type mismatch ⚠️

**Regression from T8.20.** Two bugs in one block:

1. `preg.list_plugins()` — method does not exist; correct name is `preg.list_records()`.
2. `plugins=plugin_list` passes `list[str]` but `SystemStatus.plugins` expects `list[PluginStatus]`.

The `except Exception: pass` silences the `AttributeError` so the endpoint returns an
empty `plugins` list instead of crashing, but the type mismatch would cause a Pydantic
`ValidationError` if the code ever reaches assignment.

**Fix**: Call `list_records()`, map each `PluginRecord` to `PluginStatus`.

---

## HIGH (9)

### TD-339 · `anthropic.py` L194 — `budget_tokens == max_tokens` API violation ⚠️

**Regression from T8.23.**

```python
kwargs["thinking"] = {"type": "enabled", "budget_tokens": min(_max_tokens, 10_000)}
```

Anthropic requires `budget_tokens < max_tokens`. When `max_tokens ≤ 10_000`, the
constraint is violated (`budget_tokens == max_tokens`), returning a 400 error.

**Fix**: `budget_tokens = min(_max_tokens - 1, 10_000)` with a floor of 1.

---

### TD-340 · `connection.py` L134 — Re-entrant `write_transaction` crashes

```python
async with lock:
    await conn.execute("BEGIN IMMEDIATE")
```

If any code path calls `write_transaction` from inside an already-open
`write_transaction`, the inner `BEGIN IMMEDIATE` raises
`OperationalError: cannot start a transaction within a transaction`.
The asyncio lock prevents *concurrent* re-entrance but not *nested* re-entrance
in the same coroutine.

**Fix**: Track nesting depth or use `SAVEPOINT` for inner transactions.

---

### TD-341 · `circuit_breaker.py` L205-227 — Stream retry duplicates already-yielded events

When a mid-stream error triggers retry, the `while True` loop re-calls `fn()` and
re-yields from the start. Events already consumed by the caller are duplicated.

**Fix**: Either disallow mid-stream retry (re-raise immediately) or buffer events
and replay only un-consumed ones.

---

### TD-342 · `schema.py` L30 — SQL injection via f-string in `column_exists`

```python
cursor = await db.execute(f"PRAGMA table_info({table})")
```

`table` is interpolated directly. Although callers are internal (migrations), this
is a dangerous pattern — any future caller could inject SQL.

**Fix**: Validate `table` against `^[a-zA-Z_][a-zA-Z0-9_]*$` or use the
`PRAGMA` with quoted identifier.

---

### TD-343 · `turn_loop.py` L92 — Lock eviction can evict a held lock

```python
if len(self._session_locks) >= self._max_session_locks:
    oldest = next(iter(self._session_locks))
    del self._session_locks[oldest]
```

The evicted lock may currently be held by another coroutine. Deleting it from the
dict doesn't release the lock — the coroutine holding it will exit normally — but
the *next* request for that session will allocate a *new* lock, allowing two
concurrent turns on the same session.

**Fix**: Only evict locks whose `.locked()` returns `False`.

---

### TD-344 · `embeddings.py` L249-258 — `_load_vectors` loads all rows into memory

```python
rows = await cur.fetchall()  # potentially millions of rows
```

For large embedding tables this causes OOM. There is no pagination, no streaming,
and the result is cached (compounding the problem).

**Fix**: Stream with server-side cursor + batch processing, or limit cache size.

---

### TD-345 · `openai.py` L197 — First tool-call chunk's arguments dropped

```python
tool_call_buf[idx] = {"id": tc_id, "name": tc_name, "args_raw": ""}
```

When a new tool-call index appears, the first chunk's `function.arguments` is
discarded — only subsequent delta chunks are appended to `args_raw`.

**Fix**: Initialize `args_raw` from `tc_delta.function.arguments or ""`.

---

### TD-346 · `runtime.py` L84-100 — Workflow handler registered after sub-agent spawn

```python
sub_key = await spawn_sub_agent(...)   # can complete instantly
_router.on(ET.AGENT_RUN_COMPLETE, _on_complete)  # too late
```

If the sub-agent completes before the handler is registered, the workflow step
hangs forever (or times out).

**Fix**: Register the handler *before* spawning, or use a shared result dict.

---

### TD-347 · `store.py` (memory) L131 — `get_batch` unbounded IN clause

```python
placeholders = ",".join("?" * len(memory_ids))
```

SQLite enforces a max of 999 parameters by default. A caller passing >999 IDs
causes `OperationalError`.

**Fix**: Chunk into batches of 900 and merge results.

---

## MEDIUM (18)

### TD-348 · `recall.py` L295 — `_last_recalled_ids` race condition

`_last_recalled_ids` is set as a plain instance attribute. Concurrent `recall()`
calls overwrite each other's IDs, so `prefetch_background` touches a stale set.

**Fix**: Use an asyncio-safe queue or return recalled IDs from `recall()`.

---

### TD-349 · `graph.py` L491-499 — N+1 queries in `_rebuild_semantic_edges`

Each node in a batch issues a separate `SELECT content` query. For N nodes,
this is N round-trips.

**Fix**: Batch-fetch content in a single `IN (?)` query per chunk (respecting
the 999-param limit per TD-347).

---

### TD-350 · `store.py` (memory) L314-335 — `link_entity`/`unlink_entity` split transaction

The write (INSERT/DELETE) runs inside `write_transaction`, but
`_sync_entity_ids_json` runs *outside* it. A crash between the two leaves
`entity_ids` JSON stale.

**Fix**: Move `_sync_entity_ids_json` inside the same `write_transaction` block.

---

### TD-351 · `sessions/store.py` L393-397 — `total_changes` unreliable for OCC

```python
before = self._db.total_changes
async with write_transaction(self._db):
    await self._db.execute(sql, params)
after = self._db.total_changes
```

`total_changes` counts *all* changes on the connection, not just the last statement.
If `write_transaction` runs triggers or other statements, the delta can exceed 1
even when the target row wasn't updated.

**Fix**: Use `cursor.rowcount` from the execute result, or `SELECT changes()`.

---

### TD-352 · `policy.py` L110 — `allows_path` partial directory match

```python
norm.startswith(os.path.normpath(allowed))
```

`/tmp/safe` matches `/tmp/safety-bypass`. Trailing separator is not enforced.

**Fix**: Compare with `allowed + os.sep` or use `PurePath.is_relative_to()`.

---

### TD-353 · `prompt_assembly.py` L180-194 — `min_recent_messages` can blow budget

The assembly loop always includes `min_recent_messages` even if they exceed the
remaining token budget. This can push total tokens over the model's context window.

**Fix**: If inserting min-recent messages exceeds budget, log a warning and cap.

---

### TD-354 · `sub_agent.py` L42 — `_MAX_TRACKED_PARENTS` defined but never enforced

The constant `_MAX_TRACKED_PARENTS = 500` is declared but no code evicts entries
from `_active` or `_spawn_locks`, so both dicts grow without bound.

**Fix**: Add LRU eviction or periodic cleanup of idle parent entries.

---

### TD-355 · `web_cache.py` L164 — `purge_expired` doesn't handle 'Z' suffix

```sql
REPLACE(REPLACE(fetched_at, 'T', ' '), '+00:00', '')
```

ISO-8601 timestamps ending with `Z` (instead of `+00:00`) are not stripped,
causing `julianday()` to return NULL and the row to never expire.

**Fix**: Add `REPLACE(..., 'Z', '')` to the chain.

---

### TD-356 · `messages.py` (router) L31 — `CreateMessageRequest.role` unvalidated

```python
role: str = "user"
```

Accepts any string. Invalid roles (e.g. `"admin"`) are persisted to the database
and may confuse downstream logic.

**Fix**: Change to `Literal["user", "system"]` or validate against allowed set.

---

### TD-357 · `budget/__init__.py` L346 — `$0` budget cap never blocks

```python
ratio = current / cap.limit_usd if cap.limit_usd > 0 else 0.0
```

When `limit_usd == 0`, ratio is always 0.0, so the 80% alert threshold is never
reached and no warning or block is issued. A $0 cap should mean "no spending".

**Fix**: If `limit_usd == 0` and `current > 0`, treat as exceeded.

---

### TD-358 · `gateway/router.py` L137 — `emit()` sequential handler dispatch

Handlers are awaited one at a time. A slow handler (e.g. network call) blocks
all subsequent handlers for the same event.

**Fix**: Use `asyncio.gather(*coros, return_exceptions=True)` or `create_task`.

---

### TD-359 · `tools/executor.py` L306-308 — Audit logging with `router=None`

When `ToolExecutor` is constructed without a router, audit logging silently
skips the gateway event but still hits the DB write path, which can fail if
the DB isn't initialized.

**Fix**: Guard the full audit block on `self._router is not None` or
separate DB audit from event emission.

---

### TD-360 · `soul.py` L31 — `Environment` return type not imported

```python
def _make_env(strict: bool = False) -> Environment:
```

`Environment` is not in the imports. `from __future__ import annotations` defers
evaluation so no `NameError` at runtime, but `typing.get_type_hints()` and
IDE inspections fail.

**Fix**: Import `Environment` from `jinja2` or change annotation to
`SandboxedEnvironment`.

---

### TD-361 · `anthropic.py` — No API key validation before first request

The Anthropic client is constructed without checking if `ANTHROPIC_API_KEY` is
set. The first `stream_completion` call produces a cryptic 401 instead of a
clear startup error.

**Fix**: Validate key presence in `__init__` or register-time.

---

### TD-362 · `openai.py` — `AsyncOpenAI` client never closed

The `AsyncOpenAI` client is created in `__init__` but `close()` or
`__aexit__` is never called, leaking HTTP connection pools.

**Fix**: Add `async def close()` method, call from provider teardown.

---

### TD-363 · `providers/registry.py` — `_lock` attribute is dead code

An asyncio Lock is created but never acquired anywhere in the registry.

**Fix**: Either use it to guard concurrent `list_all_models` calls or remove it.

---

### TD-364 · `agent/store.py` L72 — `clone()` extra dict can inject arbitrary columns

```python
extra = {k: v for k, v in agent.__dict__.items() if k not in ...}
```

No allow-list. A future `AgentConfig` field with a DB-column name could
silently overwrite core columns in the INSERT.

**Fix**: Use an explicit allow-list of known extra fields.

---

### TD-365 · `lifecycle.py` L153-175 — `run_decay` one UPDATE per memory

Each memory's decay score is updated with a separate `UPDATE` statement.
For N memories this is N round-trips.

**Fix**: Batch with `executemany` or `CASE WHEN` in a single statement.

---

## LOW (25)

| ID | File | Issue |
|----|------|-------|
| TD-366 | `mock.py` L91 | `async def stream_completion` returns generator — callers must `await` then iterate (type confusion) |
| TD-367 | `anthropic.py` | `_convert_messages` silently drops unknown `content_block.type` values |
| TD-368 | `openai.py` | No explicit `timeout` on API calls; defaults to httpx global (300s) |
| TD-369 | `circuit_breaker.py` | `_state`/`_failure_count` modified without asyncio Lock guard |
| TD-370 | `providers/base.py` | `ToolDef.parameters` is `dict[str, Any]` — no JSON Schema validation |
| TD-371 | `turn_loop.py` | `MAX_TOOL_ROUNDS = 10` module constant, not per-agent configurable |
| TD-372 | `context.py` | `AssemblyContext.remaining()` can return negative if overbudget |
| TD-373 | `escalation.py` | Escalation policy values are raw strings with no enum validation |
| TD-374 | `sessions/branching.py` | Branch copies entire message list in-memory without pagination |
| TD-375 | `sessions/models.py` | `Session.metadata` is `dict[str, Any]` with no size limit |
| TD-376 | `vault.py` | `_slugify` can produce empty string for non-ASCII-only titles |
| TD-377 | `vault.py` | `sync_from_disk` reads file content synchronously per file in thread |
| TD-378 | `entities.py` | Entity merge doesn't guard against self-merge (`a.merge(a)`) |
| TD-379 | `extraction.py` | `_step1_classify` returns indices without verifying message list bounds (guard exists but can be bypassed by non-int values) |
| TD-380 | `models.py` (memory) | `MemoryExtract.from_row` doesn't validate `importance` ∈ [0, 1] |
| TD-381 | `ws.py` | No rate-limiting or max payload size on WebSocket connections |
| TD-382 | `deps.py` | `get_db` dependency returns shared connection — no per-request isolation |
| TD-383 | `audit/logger.py` | `_JSONFormatter` allocates a dummy `LogRecord` on every `format()` call |
| TD-384 | `gateway/events.py` | `GatewayEvent` is frozen dataclass but `data` dict is mutable |
| TD-385 | `knowledge/sources/` | Source registry not cleaned up on app shutdown |
| TD-386 | `budget/__init__.py` | `_last_alert_times` uses `hasattr` check instead of `__init__` initialization |
| TD-387 | `workflows/api.py` | Workflow step timeout unbounded; can be set to extremely large values |
| TD-388 | `plugins/discovery.py` | `sys.modules` cleanup only removes exact module name, not submodules |
| TD-389 | `db/schema.py` | `execute_script` splits on `;` — breaks if `;` appears in string literals |
| TD-390 | `providers/registry.py` | `list_all_models` uses `asyncio.gather` without `return_exceptions=True` |

---

## Recommended Batch Plan

| Batch | Items | Focus | Priority |
|-------|-------|-------|----------|
| **B1** | TD-337, TD-338, TD-339 | **Regressions + Critical** — fix immediately | Critical/High |
| **B2** | TD-340, TD-341, TD-342, TD-343 | Connection safety, streaming, SQL injection, lock eviction | High |
| **B3** | TD-344, TD-345, TD-346, TD-347 | OOM, tool args, workflow race, batch limits | High |
| **B4** | TD-348 – TD-353 | Recall race, N+1 queries, OCC fix, path matching, budget assembly | Medium |
| **B5** | TD-354 – TD-359 | Cleanup: sub-agent caps, cache, validation, gateway, executor | Medium |
| **B6** | TD-360 – TD-365 | Types, API keys, client close, dead code, extra-dict, batch update | Medium |
| **B7** | TD-366 – TD-378 | Low-severity provider/agent/session cleanups | Low |
| **B8** | TD-379 – TD-390 | Low-severity memory/API/infra cleanups | Low |

---

## Notes

- The two ⚠️ regressions (TD-338, TD-339) were introduced by Batch 8 tasks T8.20 and T8.23. **Batch B1 should be executed first.**
- Items involving SQLite parameter limits (TD-347, TD-349) share a common chunking pattern — implement a shared `_chunked_in_query()` helper.
- The `total_changes` OCC issue (TD-351) interacts with `write_transaction` nesting (TD-340); fixing one may uncover the other.
- Test count must remain ≥ 935 passed after each batch.
