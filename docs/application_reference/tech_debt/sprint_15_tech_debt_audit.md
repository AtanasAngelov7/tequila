# Tech Debt Audit — Post-Cleanup Deep Dive (March 2026)

**Audited**: Full codebase — all modules, providers, sessions, memory, knowledge, tools, API routers, frontend, DB, config, infrastructure
**Extends**: Previous audits (TD-001 through TD-269, mostly resolved)
**New issues**: TD-270 through TD-336 (67 findings)
**Audit date**: March 17, 2026

---

## Executive Summary

A comprehensive post-cleanup audit covering every layer of the application uncovered **67 new issues**. The most critical cluster is **silently broken error reporting**: provider stream errors use a non-existent field name, causing all Anthropic/OpenAI error messages to be lost (TD-270). A second critical cluster is **dead reliability infrastructure**: the circuit breaker retry logic never fires because it wraps async generators at creation time rather than iteration time (TD-271), the fallback system in `GracefulDegradation` has the same issue (TD-272), and the `AgentStore` OCC retry loop raises unconditionally on first conflict (TD-278).

The third cluster is **persistent memory leaks**: turn queues for archived/deleted sessions are never cleaned up because `remove_turn_queue` is called with `session_id` instead of `session_key` (TD-275), session locks and sub-agent tracking dicts grow unboundedly (TD-283, TD-287), and tool executor state accumulates per-session entries with no eviction (TD-296).

The fourth cluster is **incomplete prior fixes**: LIKE-based timestamp queries remain in 4 budget methods despite TD-160 converting only `_check_caps` (TD-303, TD-304), the offset-based pagination anti-pattern persists in `run_decay` despite other lifecycle methods being converted (TD-293), and `set_cap` still returns the wrong ID on upsert conflict (TD-305).

| Severity | Count | Description |
|----------|-------|-------------|
| **Critical** | 3 | Provider errors lost, memory merge crashes, graph rebuild dead |
| **High** | 8 | Dead retry/fallback logic, setup key discarded, wrong cleanup keys, OCC bugs |
| **Medium** | 25 | N+1 queries, unbounded caches, concurrency gaps, incomplete LIKE fixes, security |
| **Low** | 31 | Code quality, edge cases, minor performance, UX polish |
| **Total** | **67** | |

---

## Quick Reference

| ID | Title | Sev | Category |
|----|-------|-----|----------|
| [TD-270](#td-270) | Anthropic & OpenAI error events use wrong field name — errors lost | **Crit** | Bug |
| [TD-271](#td-271) | CircuitBreaker `call()` retry/failure-recording is dead code | **High** | Bug |
| [TD-272](#td-272) | GracefulDegradation fallback never catches streaming errors | **High** | Bug |
| [TD-273](#td-273) | Anthropic provider silently drops thinking/reasoning blocks | **Med** | Bug |
| [TD-274](#td-274) | Anthropic provider never sends API params for extended thinking | **Med** | Design |
| [TD-275](#td-275) | `remove_turn_queue` called with `session_id` instead of `session_key` | **High** | Bug |
| [TD-276](#td-276) | Prompt corruption on multi-round tool execution | **High** | Bug |
| [TD-277](#td-277) | History messages lose `tool_calls` and `tool_call_id` in prompt assembly | **Med** | Bug |
| [TD-278](#td-278) | `AgentStore.update()` OCC retry loop never retries | **High** | Bug |
| [TD-279](#td-279) | `AgentStore.clone()` drops most agent configuration | **Med** | Bug |
| [TD-280](#td-280) | Multiple system messages silently overwritten in Anthropic adapter | **Low** | Bug |
| [TD-281](#td-281) | ProviderRegistry double-checked locking allocates new Lock each time | **Med** | Concurrency |
| [TD-282](#td-282) | OllamaProvider httpx client has no lifecycle cleanup | **Med** | Resource Leak |
| [TD-283](#td-283) | `_session_locks` dict in TurnLoop grows unbounded | **Med** | Performance |
| [TD-284](#td-284) | ProviderRegistry capability cache grows unbounded | **Low** | Performance |
| [TD-285](#td-285) | `ProviderRegistry.list_all_models` concurrent mutation of shared list | **Low** | Concurrency |
| [TD-286](#td-286) | OpenAI provider marks o1/o3-mini `supports_thinking` but never handles it | **Low** | Design |
| [TD-287](#td-287) | `sub_agent._active` and `_spawn_locks` grow unbounded | **Med** | Performance |
| [TD-288](#td-288) | `query_audit_log` LIKE wildcards not escaped | **Low** | Security |
| [TD-289](#td-289) | `_circuit_registry` global dict has no cleanup mechanism | **Low** | Resource Leak |
| [TD-290](#td-290) | Anthropic provider imports `json` inside hot streaming loop | **Low** | Performance |
| [TD-291](#td-291) | MockProvider emits duplicate usage events | **Low** | Bug |
| [TD-292](#td-292) | CircuitBreaker `is_available()` reads state without lock | **Low** | Concurrency |
| [TD-293](#td-293) | `run_decay` uses offset-based pagination — skips/double-processes rows | **High** | Bug |
| [TD-294](#td-294) | `hit.score` should be `hit.similarity` in memory merge — runtime crash | **Crit** | Bug |
| [TD-295](#td-295) | `rebuild_semantic_edges()` queries non-existent `graph_nodes` table | **Crit** | Bug |
| [TD-296](#td-296) | Unbounded in-memory state dicts in `ToolExecutor` | **Med** | Resource Leak |
| [TD-297](#td-297) | SQL LIKE wildcard injection in memory/entity/vault search | **Med** | Security |
| [TD-298](#td-298) | N+1 queries in `recall_for_turn` semantic search | **Med** | Performance |
| [TD-299](#td-299) | N+1 queries in `_entity_expand` | **Med** | Performance |
| [TD-300](#td-300) | `EntityStore.update` OCC uses timestamp instead of version counter | **Med** | Concurrency |
| [TD-301](#td-301) | `EntityStore.update` silently succeeds on OCC exhaustion | **High** | Bug |
| [TD-302](#td-302) | `prefetch_background` touches LIKE-matched, not actually recalled memories | **Med** | Bug |
| [TD-303](#td-303) | `is_blocked()` still uses LIKE — TD-160 incomplete | **Med** | Performance |
| [TD-304](#td-304) | `get_summary`, `get_by_agent`, `get_by_provider` also use LIKE | **Med** | Performance |
| [TD-305](#td-305) | `set_cap()` returns wrong ID on upsert conflict | **High** | Bug |
| [TD-306](#td-306) | Budget alert fires every turn with no de-duplication | **Med** | UX/Bug |
| [TD-307](#td-307) | `_sync_entity_ids_json` SELECT outside write transaction — race | **Med** | Concurrency |
| [TD-308](#td-308) | `sync_from_disk` reads ALL file contents unconditionally | **Med** | Performance |
| [TD-309](#td-309) | `MemoryExtract.from_row` uncaught `json.JSONDecodeError` | **Med** | Bug |
| [TD-310](#td-310) | `_parse_json_response` regex fails on nested brackets | **Low** | Bug |
| [TD-311](#td-311) | Embedding cache invalidation clears ALL filter variants | **Low** | Performance |
| [TD-312](#td-312) | `run_orphan_report` uses offset-based pagination (inconsistency) | **Low** | Performance |
| [TD-313](#td-313) | `_step1_classify` doesn't filter negative LLM indices | **Low** | Bug |
| [TD-314](#td-314) | `_build_json_schema` includes `self` parameter for methods | **Low** | Bug |
| [TD-315](#td-315) | `recall_for_turn` FTS fallback passes raw user message to LIKE | **Med** | Bug |
| [TD-316](#td-316) | `shortest_path` copies entire path list per BFS step | **Low** | Performance |
| [TD-317](#td-317) | `create_note` TOCTOU race on file existence check | **Low** | Concurrency |
| [TD-318](#td-318) | Hardcoded merge confidence bump (0.05) | **Low** | Design |
| [TD-319](#td-319) | Branching operations not atomic with turn execution | **Med** | Concurrency |
| [TD-320](#td-320) | `allows_path` does no path normalization — traversal risk | **Med** | Security |
| [TD-321](#td-321) | `compress_trim_oldest` still O(n²) despite TD-261 fix | **Med** | Performance |
| [TD-322](#td-322) | `_JSONFormatter` leaks internal LogRecord attributes | **Low** | Code Quality |
| [TD-323](#td-323) | Tool token budget double-counted in prompt assembly | **Med** | Bug |
| [TD-324](#td-324) | Setup wizard discards API key — never persisted | **High** | Bug |
| [TD-325](#td-325) | Messages pagination `total` reflects page size, not true total | **Med** | Bug |
| [TD-326](#td-326) | Fire-and-forget turn tasks — unhandled exception warnings | **Med** | Reliability |
| [TD-327](#td-327) | `system_status` queries providers sequentially — slow endpoint | **Med** | Performance |
| [TD-328](#td-328) | `system_status` returns hardcoded stubs for initialized stores | **Med** | Stale Code |
| [TD-329](#td-329) | `shutdown()` doesn't reset `_app_db_path` or `_write_locks` | **Med** | Resource Mgmt |
| [TD-330](#td-330) | `purge_expired()` loads entire `web_cache` table into memory | **Med** | Performance |
| [TD-331](#td-331) | Parallel workflow mode ignores `cancel_event` during execution | **Med** | Concurrency |
| [TD-332](#td-332) | `install_dependencies` allows pip argument injection via spec | **Med** | Security |
| [TD-333](#td-333) | `SessionPolicyPresets.by_name()` returns shared mutable instances | **Low** | Design |
| [TD-334](#td-334) | `Message.role` Literal missing `"tool"` vs `_VALID_ROLES` | **Low** | Code Quality |
| [TD-335](#td-335) | `_register_builtins` silently swallows real ImportErrors | **Low** | Error Handling |
| [TD-336](#td-336) | Failed plugin loads pollute `sys.modules` | **Low** | Resource Mgmt |

---

## Critical Severity

### TD-270

**Anthropic & OpenAI error events use wrong field name — errors lost**

- **File**: `app/providers/anthropic.py` ~L270, `app/providers/openai.py` ~L207
- **Category**: Bug

Both providers emit `ProviderStreamEvent(kind="error", error=str(exc))` but `ProviderStreamEvent` has fields `error_message` and `error_code` — there is no `error` field. Pydantic silently drops the unknown kwarg. Every Anthropic/OpenAI error results in `error_message=None`, and the turn loop displays "Unknown provider error".

**Fix**: Change to `ProviderStreamEvent(kind="error", error_message=str(exc), error_code="stream_error")`.

---

### TD-294

**`hit.score` should be `hit.similarity` in memory merge — runtime crash**

- **File**: `app/memory/lifecycle.py` ~L404–L408
- **Category**: Bug

`run_merge()` references `hit.score` in two places, but `EmbeddingSearchResult` has field `similarity`, not `score`. Raises `AttributeError` at runtime, completely breaking memory merge consolidation.

**Fix**: Replace `hit.score` with `hit.similarity`.

---

### TD-295

**`rebuild_semantic_edges()` queries non-existent `graph_nodes` table**

- **File**: `app/knowledge/graph.py` ~L487–L493
- **Category**: Bug

Queries `SELECT content FROM graph_nodes WHERE id = ?` but no `graph_nodes` table exists in the schema. The class docstring says "Nodes are not stored here — resolved from source tables." The `except Exception: pass` silently swallows the OperationalError, making the entire function dead code.

**Fix**: Resolve content from source tables based on `source_type` (e.g., `memory_extracts.content`, `entities.name`).

---

## High Severity

### TD-271

**CircuitBreaker `call()` retry/failure-recording is dead code**

- **File**: `app/providers/circuit_breaker.py` ~L180–L219
- **Category**: Bug

`call()` wraps `fn()` inside `_streaming_wrapper()` (an async generator). Calling `_streaming_wrapper()` returns immediately without executing body code. The `except` clause never fires, so `record_failure()` is never called from this path and the retry loop always exits on first iteration. The turn loop works around this by calling `record_success`/`record_failure` manually.

**Fix**: Restructure to intercept errors during iteration, not at construction time.

---

### TD-272

**GracefulDegradation fallback never catches streaming errors**

- **File**: `app/providers/circuit_breaker.py` ~L292–L313
- **Category**: Bug

`stream_completion()` calls `provider.stream_completion(...)` which returns an async generator immediately (never raises). The `try/except` never catches anything — errors occur when the consumer iterates, at which point `GracefulDegradation` has already returned.

**Fix**: Peek/prefetch the first event inside the try block before returning the generator.

---

### TD-275

**`remove_turn_queue` called with `session_id` instead of `session_key`**

- **File**: `app/sessions/store.py` ~L453, L476, L508
- **Category**: Bug

`mark_idle()`, `archive()`, and `delete()` all call `remove_turn_queue(session_id)`. But turn queues are keyed by `session_key`. UUID ≠ session_key, so the pop always misses. Turn queues for idle/archived/deleted sessions are never cleaned up — unbounded memory leak.

**Fix**: Fetch the session's `session_key` and pass it to `remove_turn_queue()`.

---

### TD-276

**Prompt corruption on multi-round tool execution**

- **File**: `app/agent/turn_loop.py` ~L393–L414, `app/agent/prompt_assembly.py` ~L243
- **Category**: Bug

After tool execution, the last messages in the active chain are `tool_result` messages — not user messages. But `_assemble()` treats the last message as the current user message. On second+ tool rounds, tool results are injected as user messages. Additionally, `tool_calls` on assistant messages and `tool_call_id` on tool messages are discarded during history assembly.

**Fix**: Detect continuation case in `_assemble` and properly include tool_calls/tool_call_id.

---

### TD-278

**`AgentStore.update()` OCC retry loop never retries**

- **File**: `app/agent/store.py` ~L192–L218
- **Category**: Bug

The `raise ConflictError(...)` is unconditional inside the loop body — fires on first version mismatch. The loop never retries. Compare with `SessionStore.update()` which properly gates the raise.

**Fix**: Add `if attempt >= MAX_OCC_RETRIES` guard.

---

### TD-293

**`run_decay` uses offset-based pagination — skips/double-processes rows**

- **File**: `app/memory/lifecycle.py` ~L175–L188
- **Category**: Bug / Performance

`run_decay()` paginates with `offset += batch`, but updating `decay_score` changes `updated_at`, shifting row ordering. `run_archive` and `run_expire_tasks` already use cursor-based `after_id` — `run_decay` was missed.

**Fix**: Switch to cursor-based pagination.

---

### TD-301

**`EntityStore.update` silently succeeds on OCC exhaustion**

- **File**: `app/memory/entity_store.py` ~L224–L228
- **Category**: Bug

After 3 failed OCC retries, returns `await self.get(entity_id)` — caller gets stale data with no indication the update failed. `MemoryStore.update()` raises `ConflictError`.

**Fix**: Raise `ConflictError` after retry exhaustion.

---

### TD-305

**`set_cap()` returns wrong ID on upsert conflict**

- **File**: `app/budget/__init__.py` ~L259–L277
- **Category**: Bug

Generates new UUID, does `INSERT … ON CONFLICT DO UPDATE`, returns the new UUID. On conflict, the existing row keeps its original ID. Clients using the returned ID get 404s.

**Fix**: Read back the actual ID after upsert.

---

### TD-324

**Setup wizard discards API key — never persisted**

- **File**: `app/api/routers/setup.py` ~L202–L279
- **Category**: Bug

The setup endpoint accepts `api_key`, validates it structurally, then never persists it. The provider will fail on first use unless the key is set in the environment.

**Fix**: Store in credential vault (encrypted) via `VaultStore` or `ConfigStore`.

---

## Medium Severity

### TD-273

**Anthropic provider silently drops thinking/reasoning content blocks**

- **File**: `app/providers/anthropic.py` ~L210–L230
- **Category**: Bug

Stream handler only matches `block.type == "text"` and `"tool_use"`. Anthropic extended thinking sends `"thinking"` and `"thinking_delta"` — silently ignored.

---

### TD-274

**Anthropic provider never sends API parameters for extended thinking**

- **File**: `app/providers/anthropic.py` ~L174–L192
- **Category**: Design

Extended thinking requires `thinking={"type": "enabled", "budget_tokens": N}` and `temperature=1.0`. Neither is sent. `supports_thinking=True` on claude-opus-4-5 is misleading.

---

### TD-277

**History messages lose `tool_calls` and `tool_call_id` in prompt assembly**

- **File**: `app/agent/prompt_assembly.py` ~L229–L239
- **Category**: Bug

Step 7 creates `Message(role=role, content=content)` without `tool_call_id` or `tool_calls`. Multi-turn tool conversations degrade.

---

### TD-279

**`AgentStore.clone()` drops most agent configuration**

- **File**: `app/agent/store.py` ~L243–L252
- **Category**: Bug

Only copies 7 fields. Silently drops `tools`, `skills`, `default_policy`, `memory_scope`, `escalation`, `context_budget`, `status`.

---

### TD-281

**ProviderRegistry double-checked locking allocates new Lock each time**

- **File**: `app/providers/registry.py` ~L51–L58
- **Category**: Concurrency

Creates `threading.Lock()` inside the outer `if _instance is None` — two threads could each create their own lock.

**Fix**: Use module-level Lock.

---

### TD-282

**OllamaProvider httpx client has no lifecycle cleanup**

- **File**: `app/providers/ollama.py` ~L82–L83
- **Category**: Resource Leak

`close()` method exists but nothing in the app lifecycle calls it. Connections leak on GC.

---

### TD-283

**`_session_locks` dict in TurnLoop grows unbounded**

- **File**: `app/agent/turn_loop.py` ~L79
- **Category**: Performance

Creates new `asyncio.Lock` per session key, never evicted.

---

### TD-287

**`sub_agent._active` and `_spawn_locks` grow unbounded**

- **File**: `app/agent/sub_agent.py` ~L43–L44
- **Category**: Performance

Neither dict has eviction logic.

---

### TD-296

**Unbounded in-memory state dicts in `ToolExecutor`**

- **File**: `app/tools/executor.py` ~L92–L97
- **Category**: Resource Leak

`_pending`, `_allow_all`, `_session_approvals` keyed by `session_key`, no eviction on disconnect.

---

### TD-297

**SQL LIKE wildcard injection in memory/entity/vault search**

- **File**: `app/memory/store.py` ~L155, `app/memory/entity_store.py` ~L116, `app/knowledge/vault.py` ~L302
- **Category**: Security

`f"%{search}%"` without escaping `%` and `_`. User-supplied `%` matches everything.

---

### TD-298

**N+1 queries in `recall_for_turn` semantic search**

- **File**: `app/memory/recall.py` ~L159–L175
- **Category**: Performance

15 individual `mem_store.get(source_id)` calls after embedding search. Should batch-fetch.

---

### TD-299

**N+1 queries in `_entity_expand`**

- **File**: `app/memory/recall.py` ~L240–L270
- **Category**: Performance

Up to 65 individual DB queries (5 mentions × 3 entities × 3 memories + overhead).

---

### TD-300

**`EntityStore.update` OCC uses timestamp instead of version counter**

- **File**: `app/memory/entity_store.py` ~L179–L228
- **Category**: Concurrency

Two updates within same millisecond can both succeed, silently overwriting.

---

### TD-302

**`prefetch_background` touches LIKE-matched, not actually recalled memories**

- **File**: `app/memory/recall.py` ~L348–L365
- **Category**: Bug

Runs a separate LIKE query and `touch()`es those results — not the memories actually recalled and shown to the user. Corrupts decay signal.

---

### TD-303

**`is_blocked()` still uses LIKE — TD-160 incomplete**

- **File**: `app/budget/__init__.py` ~L338–L354
- **Category**: Performance

Uses `WHERE timestamp LIKE ?` with `"2026-03-17%"`. Forces full table scan.

---

### TD-304

**`get_summary`, `get_by_agent`, `get_by_provider` also use LIKE**

- **File**: `app/budget/__init__.py` ~L370–L430
- **Category**: Performance

Same LIKE pattern issue in 3 more reporting methods.

---

### TD-306

**Budget alert fires every turn with no de-duplication**

- **File**: `app/budget/__init__.py` ~L313–L337
- **Category**: UX/Bug

`_maybe_alert()` fires on every turn above 80%. Burst of 5 parallel steps → 5 identical notifications.

---

### TD-307

**`_sync_entity_ids_json` SELECT outside write transaction — race**

- **File**: `app/memory/store.py` ~L272–L280
- **Category**: Concurrency

SELECT and UPDATE in separate transaction scopes.

---

### TD-308

**`sync_from_disk` reads ALL file contents unconditionally**

- **File**: `app/knowledge/vault.py` ~L440–L480
- **Category**: Performance

Reads every `.md` file to hash, even if mtime unchanged.

---

### TD-309

**`MemoryExtract.from_row` uncaught `json.JSONDecodeError`**

- **File**: `app/memory/models.py` ~L207–L209
- **Category**: Bug

One corrupt JSON row crashes listing for all results.

---

### TD-315

**`recall_for_turn` FTS fallback passes raw user message to LIKE**

- **File**: `app/memory/recall.py` ~L197
- **Category**: Bug

200 chars of raw user message as LIKE pattern — semantically meaningless.

---

### TD-319

**Branching operations not atomic with turn execution**

- **File**: `app/sessions/branching.py` ~L60–L95
- **Category**: Concurrency

`deactivate_from` and `run_turn_from_api` are separate operations outside the session lock.

---

### TD-320

**`allows_path` does no path normalization — traversal risk**

- **File**: `app/sessions/policy.py` ~L98–L101
- **Category**: Security

Raw `path.startswith(allowed)` with no normalization. `../` traversal bypasses restrictions.

---

### TD-321

**`compress_trim_oldest` still O(n²) despite TD-261 fix**

- **File**: `app/agent/context.py` ~L278–L290
- **Category**: Performance

Loop calls `usage_ratio()` with full list slice per iteration.

---

### TD-323

**Tool token budget double-counted in prompt assembly**

- **File**: `app/agent/prompt_assembly.py` ~L142 and ~L199
- **Category**: Bug

Tool text tokens counted in system prompt AND again in Step 5. Premature history truncation.

---

### TD-325

**Messages pagination `total` reflects page size, not true total**

- **File**: `app/api/routers/messages.py` ~L140
- **Category**: Bug

`total=len(messages)` returns current page count. Client can't paginate.

---

### TD-326

**Fire-and-forget turn tasks — unhandled exception warnings**

- **File**: `app/api/ws.py` ~L231, `app/api/routers/messages.py` ~L168, `app/api/routers/sessions.py` ~L325
- **Category**: Reliability

`asyncio.create_task` references not stored. Unhandled exceptions produce warnings.

---

### TD-327

**`system_status` queries providers sequentially — slow endpoint**

- **File**: `app/api/routers/system.py` ~L227–L261
- **Category**: Performance

Calls `await provider.list_models()` sequentially for every provider. One slow provider blocks `/api/status`.

---

### TD-328

**`system_status` returns hardcoded stubs for initialized stores**

- **File**: `app/api/routers/system.py` ~L264–L274
- **Category**: Stale Code

Returns `memory_extract_count=0`, `entity_count=0`, `scheduler_status="stopped"`, `plugins=[]`. These stores are initialized since Sprint 09–13.

---

### TD-329

**`shutdown()` doesn't reset `_app_db_path` or `_write_locks`**

- **File**: `app/db/connection.py` ~L204
- **Category**: Resource Mgmt

Stale locks from previous lifecycle can cause test deadlocks.

---

### TD-330

**`purge_expired()` loads entire `web_cache` table into memory**

- **File**: `app/db/web_cache.py` ~L156–L168
- **Category**: Performance

Should use SQL-only `DELETE ... WHERE` with datetime arithmetic.

---

### TD-331

**Parallel workflow mode ignores `cancel_event` during execution**

- **File**: `app/workflows/runtime.py` ~L152–L195
- **Category**: Concurrency

Once `asyncio.gather` launches, `cancel_event` has no effect.

---

### TD-332

**`install_dependencies` allows pip argument injection via spec**

- **File**: `app/plugins/api.py` ~L270–L293
- **Category**: Security

Name-only regex validates `pkg_name`, but full spec with `--index-url` etc. passes through.

---

## Low Severity

### TD-280 — Multiple system messages silently overwritten in Anthropic adapter
`app/providers/anthropic.py` ~L99. Only last system message survives.

### TD-284 — ProviderRegistry capability cache grows unbounded
`app/providers/registry.py` ~L100. Every unique `provider:model` combo adds permanent entry.

### TD-285 — `list_all_models` concurrent mutation of shared list
`app/providers/registry.py` ~L119. Each `_fetch` coroutine extends shared `results` list.

### TD-286 — OpenAI o1/o3-mini `supports_thinking=True` but never handled
`app/providers/openai.py` ~L64. Misleading capability flag.

### TD-288 — `query_audit_log` LIKE wildcards not escaped
`app/audit/log.py` ~L118. `action` filter uses unescaped LIKE.

### TD-289 — `_circuit_registry` global dict has no cleanup
`app/providers/circuit_breaker.py` ~L330. No `remove_circuit_breaker()` function.

### TD-290 — `import json` inside hot streaming loop
`app/providers/anthropic.py` ~L237. Module-level import cheaper.

### TD-291 — MockProvider emits duplicate usage events
`app/providers/mock.py` ~L140. Script usage + auto-generated usage.

### TD-292 — CircuitBreaker `is_available()` reads state without lock
`app/providers/circuit_breaker.py` ~L100. Inconsistent with write methods that lock.

### TD-310 — `_parse_json_response` regex fails on nested brackets
`app/memory/extraction.py` ~L120. Non-greedy `\[.*?\]` stops at first `]`.

### TD-311 — Embedding cache invalidation clears ALL filter variants
`app/knowledge/embeddings.py` ~L215. One `add()` wipes all cached source types.

### TD-312 — `run_orphan_report` uses offset-based pagination
`app/memory/lifecycle.py` ~L459. Inconsistent with cursor-based pattern elsewhere.

### TD-313 — `_step1_classify` doesn't filter negative LLM indices
`app/memory/extraction.py` ~L313. Negative values resolve via Python negative indexing.

### TD-314 — `_build_json_schema` includes `self` parameter for methods
`app/tools/registry.py` ~L157. Bound methods export `self` as required string arg.

### TD-316 — `shortest_path` copies entire path list per BFS step
`app/knowledge/graph.py` ~L519. Should use parent map and reconstruct on find.

### TD-317 — `create_note` TOCTOU race on file existence check
`app/knowledge/vault.py` ~L230. Use `open(path, 'x')` instead of check-then-write.

### TD-318 — Hardcoded merge confidence bump (0.05)
`app/memory/extraction.py` ~L448. Should be configurable.

### TD-322 — `_JSONFormatter` leaks internal LogRecord attributes
`app/audit/logger.py` ~L58. Deny-list approach becomes stale over time.

### TD-333 — `SessionPolicyPresets.by_name()` returns shared mutable instances
`app/sessions/policy.py` ~L157. Callers can mutate shared presets.

### TD-334 — `Message.role` Literal missing `"tool"` vs `_VALID_ROLES`
`app/sessions/models.py` ~L164. Inconsistent with insert validation.

### TD-335 — `_register_builtins` silently swallows real ImportErrors
`app/plugins/registry.py` ~L389. Coding bugs become invisible.

### TD-336 — Failed plugin loads pollute `sys.modules`
`app/plugins/discovery.py` ~L117. Partially-loaded module remains on failure.

---

## Recommended Priorities

### Immediate (one-line or simple fixes, high impact)

1. **TD-270** — Change `error=` to `error_message=` in both providers (one-line each)
2. **TD-294** — Change `hit.score` to `hit.similarity` in lifecycle.py (two-line fix)
3. **TD-278** — Add retry guard to AgentStore.update OCC loop
4. **TD-305** — Read back actual ID after upsert in set_cap
5. **TD-301** — Raise ConflictError in EntityStore.update after retry exhaustion
6. **TD-275** — Fix remove_turn_queue to use session_key

### Short-term (moderate effort, high value)

7. **TD-271/TD-272** — Restructure circuit breaker to intercept streaming errors
8. **TD-276/TD-277** — Fix prompt assembly for tool call rounds
9. **TD-295** — Fix rebuild_semantic_edges to use source tables
10. **TD-303/TD-304** — Convert remaining LIKE queries to range queries
11. **TD-324** — Persist API key during setup wizard
12. **TD-297** — Escape LIKE wildcards in search methods

### Medium-term (more involved)

13. **TD-298/TD-299** — Batch N+1 queries in recall pipeline
14. **TD-283/TD-287/TD-296** — Add eviction to unbounded dicts
15. **TD-321** — Incremental token counting in compress_trim_oldest
16. **TD-319** — Make branching atomic with turn execution
17. **TD-331** — Thread cancel_event through parallel workflow steps
