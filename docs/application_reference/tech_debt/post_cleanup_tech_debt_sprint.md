# Tech Debt Sprint — Post-Cleanup Implementation

**Phase**: Tech Debt Resolution (Post TD-001–TD-269 Cleanup)
**Scope**: TD-270 through TD-336 (67 findings)
**Status**: ⬜ Not Started
**Estimated Duration**: 3 batches across 1–2 weeks
**Reference**: [post_cleanup_findings.md](post_cleanup_findings.md) — findings summary
**Full Details**: [sprint_15_tech_debt_audit.md](sprint_15_tech_debt_audit.md) — complete audit report

---

## Goal

Resolve all 67 post-cleanup tech debt findings (TD-270–TD-336) identified in the March 2026 full-codebase audit. Work is organized into 8 batches by dependency order and risk, with critical/high items first.

---

## Batch 1 — Critical One-Line Fixes (6 tasks)

*Highest impact, lowest risk. Each is a 1–3 line change. Do these first.*

- [ ] **T1.1** Fix provider error field name (TD-270)
  - Files: `app/providers/anthropic.py` ~L270, `app/providers/openai.py` ~L207
  - Change: `error=str(exc)` → `error_message=str(exc), error_code="stream_error"`
  - Impact: Restores all provider error reporting

- [ ] **T1.2** Fix memory merge attribute name (TD-294)
  - File: `app/memory/lifecycle.py` ~L404–L408
  - Change: `hit.score` → `hit.similarity` (2 occurrences)
  - Impact: Unblocks memory consolidation

- [ ] **T1.3** Fix AgentStore OCC retry guard (TD-278)
  - File: `app/agent/store.py` ~L192–L218
  - Change: Add `if attempt >= MAX_OCC_RETRIES:` before `raise ConflictError`
  - Impact: Enables OCC retries (matches SessionStore pattern)

- [ ] **T1.4** Fix EntityStore OCC exhaustion behavior (TD-301)
  - File: `app/memory/entity_store.py` ~L224–L228
  - Change: Replace `return await self.get(entity_id)` with `raise ConflictError(...)`
  - Impact: Stops silent data loss on concurrent entity updates

- [ ] **T1.5** Fix `set_cap()` return ID on upsert conflict (TD-305)
  - File: `app/budget/__init__.py` ~L259–L277
  - Change: After INSERT, SELECT back actual row ID; return that instead of pre-generated UUID
  - Impact: Fixes 404s when using returned cap IDs

- [ ] **T1.6** Fix `remove_turn_queue` key mismatch (TD-275)
  - File: `app/sessions/store.py` ~L453, L476, L508
  - Change: Fetch session's `session_key` before calling `remove_turn_queue()`
  - Impact: Stops unbounded turn queue memory leak

### Batch 1 Tests
- [ ] Add unit test: provider error events contain `error_message`
- [ ] Add unit test: memory merge uses `similarity` attribute
- [ ] Add unit test: AgentStore OCC retries before raising
- [ ] Add unit test: EntityStore OCC raises ConflictError
- [ ] Add unit test: `set_cap` returns correct ID on conflict
- [ ] Add unit test: `remove_turn_queue` receives session_key

---

## Batch 2 — High-Severity Bug Fixes (5 tasks)

*More involved fixes that address broken reliability infrastructure and data corruption.*

- [ ] **T2.1** Fix circuit breaker streaming error handling (TD-271, TD-272)
  - Files: `app/providers/circuit_breaker.py` ~L180–L219, ~L292–L313
  - Implementation:
    1. In `CircuitBreaker.call()`: wrap the async generator iteration, not creation. Use an inner async generator that yields from the real one inside a try/except, calling `record_failure()` on error.
    2. In `GracefulDegradation.stream_completion()`: prefetch first event inside try block before returning generator. On error, switch to fallback provider.
  - Impact: Circuit breaker and fallback actually work for streaming

- [ ] **T2.2** Fix prompt assembly for multi-round tool calls (TD-276, TD-277)
  - Files: `app/agent/turn_loop.py` ~L393–L414, `app/agent/prompt_assembly.py` ~L229–L243
  - Implementation:
    1. In `_assemble()`: detect when last message is `tool_result` (continuation case). Don't treat it as user message.
    2. Preserve `tool_calls` on assistant messages and `tool_call_id` on tool messages during history assembly (Step 7).
    3. In turn loop: don't re-inject tool results as user messages on subsequent rounds.
  - Impact: Multi-round tool conversations work correctly

- [ ] **T2.3** Fix `run_decay` pagination (TD-293)
  - File: `app/memory/lifecycle.py` ~L175–L188
  - Implementation: Switch from `OFFSET` to cursor-based `WHERE id > ?` (matching `run_archive`/`run_expire_tasks` pattern)
  - Impact: Decay processes all rows exactly once

- [ ] **T2.4** Persist API key in setup wizard (TD-324)
  - File: `app/api/routers/setup.py` ~L202–L279
  - Implementation: After validation, store key via `ConfigStore` or `VaultStore` for the selected provider
  - Impact: Setup actually configures the provider

- [ ] **T2.5** Fix `rebuild_semantic_edges` to use source tables (TD-295)
  - File: `app/knowledge/graph.py` ~L487–L493
  - Implementation: Replace `SELECT content FROM graph_nodes` with resolution from source tables based on `source_type` field (e.g., `memory_extracts.content`, `entities.name`)
  - Impact: Semantic edge rebuilding actually functions

### Batch 2 Tests
- [ ] Add unit test: circuit breaker records failure on streaming error
- [ ] Add unit test: graceful degradation falls back on streaming error
- [ ] Add unit test: multi-round tool call preserves tool_calls/tool_call_id
- [ ] Add unit test: tool results not injected as user messages on round 2+
- [ ] Add unit test: `run_decay` processes all rows without skips
- [ ] Add unit test: setup wizard persists API key
- [ ] Add unit test: `rebuild_semantic_edges` resolves from source tables

---

## Batch 3 — LIKE-to-Range & SQL Injection Fixes (4 tasks)

*Completes the incomplete TD-160 migration and closes SQL injection vectors.*

- [ ] **T3.1** Convert remaining budget LIKE queries to range queries (TD-303, TD-304)
  - File: `app/budget/__init__.py`
  - Methods: `is_blocked()`, `get_summary()`, `get_by_agent()`, `get_by_provider()`
  - Change: `WHERE timestamp LIKE '2026-03-17%'` → `WHERE timestamp >= ? AND timestamp < ?` using date range
  - Impact: Index usage restored on 4 high-frequency queries

- [ ] **T3.2** Escape LIKE wildcards in search methods (TD-297)
  - Files: `app/memory/store.py`, `app/memory/entity_store.py`, `app/knowledge/vault.py`
  - Change: Add `escape_like(term)` helper that escapes `%`, `_`, and `\`; use `LIKE ? ESCAPE '\'`
  - Impact: User-supplied `%` no longer matches everything

- [ ] **T3.3** Escape LIKE wildcards in audit log query (TD-288)
  - File: `app/audit/log.py` ~L118
  - Change: Apply same `escape_like()` helper to `action` filter
  - Impact: Consistent LIKE safety across codebase

- [ ] **T3.4** Fix `recall_for_turn` FTS fallback LIKE pattern (TD-315)
  - File: `app/memory/recall.py` ~L197
  - Change: Extract keywords from user message instead of using raw 200-char string as LIKE pattern
  - Impact: FTS fallback returns meaningful results

### Batch 3 Tests
- [ ] Add unit test: budget queries use range, not LIKE
- [ ] Add unit test: search with `%` wildcard doesn't match everything
- [ ] Add unit test: FTS fallback extracts keywords

---

## Batch 4 — Unbounded Dict Eviction (5 tasks)

*Addresses the 5 modules with per-session/per-provider dicts that grow forever.*

- [ ] **T4.1** Add LRU eviction to `_session_locks` in TurnLoop (TD-283)
  - File: `app/agent/turn_loop.py` ~L79
  - Implementation: Use `collections.OrderedDict` with max size (e.g., 1000). Evict oldest on insert.
  - Impact: Bounds memory for long-running instances

- [ ] **T4.2** Add eviction to `sub_agent._active` and `_spawn_locks` (TD-287)
  - File: `app/agent/sub_agent.py` ~L43–L44
  - Implementation: Clean up entries when parent session completes or is archived. Add `cleanup_session(session_key)` method.
  - Impact: Sub-agent tracking bounded

- [ ] **T4.3** Add eviction to `ToolExecutor` state dicts (TD-296)
  - File: `app/tools/executor.py` ~L92–L97
  - Implementation: Add `cleanup_session(session_key)` that removes `_pending`, `_allow_all`, `_session_approvals` entries. Call on session archive/delete.
  - Impact: Tool executor state bounded

- [ ] **T4.4** Add eviction to `ProviderRegistry` capability cache (TD-284)
  - File: `app/providers/registry.py` ~L100
  - Implementation: TTL-based expiry (e.g., 5 min) or max-size LRU
  - Impact: Provider capability cache bounded

- [ ] **T4.5** Add cleanup for `_circuit_registry` (TD-289)
  - File: `app/providers/circuit_breaker.py` ~L330
  - Implementation: Add `remove_circuit_breaker(key)` function. Call when provider is removed from registry.
  - Impact: Circuit breaker state bounded

### Batch 4 Tests
- [ ] Add unit test: session lock eviction after max size
- [ ] Add unit test: sub-agent cleanup on session archive
- [ ] Add unit test: tool executor cleanup on session delete
- [ ] Add unit test: provider cache respects TTL/max-size

---

## Batch 5 — Concurrency & OCC Hardening (5 tasks)

*Fixes race conditions and concurrency gaps across stores and registries.*

- [ ] **T5.1** Fix ProviderRegistry double-checked locking (TD-281)
  - File: `app/providers/registry.py` ~L51–L58
  - Change: Move Lock to module level (e.g., `_registry_lock = threading.Lock()`)
  - Impact: Thread-safe singleton initialization

- [ ] **T5.2** Convert EntityStore OCC to version counter (TD-300)
  - File: `app/memory/entity_store.py` ~L179–L228
  - Implementation: Add `version` column (Alembic migration), use integer compare-and-swap instead of timestamp
  - Impact: Eliminates same-millisecond race condition

- [ ] **T5.3** Fix `_sync_entity_ids_json` transaction scope (TD-307)
  - File: `app/memory/store.py` ~L272–L280
  - Change: Move SELECT inside same `write_transaction()` scope as UPDATE
  - Impact: Atomic read-modify-write for entity ID sync

- [ ] **T5.4** Make branching atomic with turn execution (TD-319)
  - File: `app/sessions/branching.py` ~L60–L95
  - Implementation: Acquire session lock before `deactivate_from`, hold through branch creation
  - Impact: No interleaved turns during branching

- [ ] **T5.5** Thread `cancel_event` through parallel workflow steps (TD-331)
  - File: `app/workflows/runtime.py` ~L152–L195
  - Implementation: Pass `cancel_event` to each parallel step; check between iterations; cancel gathering on event
  - Impact: Parallel workflows respect cancellation

### Batch 5 Tests
- [ ] Add unit test: registry singleton under concurrent access
- [ ] Add unit test: entity version counter increments correctly
- [ ] Add unit test: entity_ids_json sync is atomic
- [ ] Add unit test: branching blocks concurrent turns
- [ ] Add unit test: parallel workflow cancellation works

---

## Batch 6 — Performance Optimizations (6 tasks)

*N+1 query batching, O(n²) fixes, and unnecessary I/O reduction.*

- [ ] **T6.1** Batch N+1 queries in `recall_for_turn` (TD-298)
  - File: `app/memory/recall.py` ~L159–L175
  - Change: Replace 15 individual `mem_store.get(source_id)` with single `mem_store.get_batch(source_ids)`
  - Impact: 15 queries → 1 query per recall

- [ ] **T6.2** Batch N+1 queries in `_entity_expand` (TD-299)
  - File: `app/memory/recall.py` ~L240–L270
  - Change: Collect all entity/memory IDs, batch-fetch in 2–3 queries
  - Impact: Up to 65 queries → 2–3 queries

- [ ] **T6.3** Fix `compress_trim_oldest` O(n²) (TD-321)
  - File: `app/agent/context.py` ~L278–L290
  - Change: Pre-compute cumulative token counts; binary search for trim point
  - Impact: O(n²) → O(n log n) for history compression

- [ ] **T6.4** Make `system_status` query providers concurrently (TD-327)
  - File: `app/api/routers/system.py` ~L227–L261
  - Change: `asyncio.gather(*[p.list_models() for p in providers])` with timeout
  - Impact: Status endpoint latency = slowest provider, not sum of all

- [ ] **T6.5** SQL-only `purge_expired` for web_cache (TD-330)
  - File: `app/db/web_cache.py` ~L156–L168
  - Change: `DELETE FROM web_cache WHERE expires_at < datetime('now')` — no Python-side loading
  - Impact: Constant memory usage for purge regardless of cache size

- [ ] **T6.6** Skip unchanged files in `sync_from_disk` (TD-308)
  - File: `app/knowledge/vault.py` ~L440–L480
  - Change: Check file mtime against stored `updated_at`; skip read+hash if unchanged
  - Impact: Sync speed proportional to changed files, not total files

### Batch 6 Tests
- [ ] Add unit test: recall batch-fetches memories
- [ ] Add unit test: entity expand uses batched queries
- [ ] Add unit test: compress_trim is sub-quadratic
- [ ] Add unit test: system_status uses concurrent provider queries
- [ ] Add unit test: purge_expired uses SQL-only delete
- [ ] Add unit test: sync_from_disk skips unchanged files

---

## Batch 7 — Security & Reliability Hardening (6 tasks)

*Path traversal, injection, resource leaks, and error resilience.*

- [ ] **T7.1** Normalize paths in `allows_path` (TD-320)
  - File: `app/sessions/policy.py` ~L98–L101
  - Change: `os.path.realpath(path).startswith(os.path.realpath(allowed))` — resolves `../` traversal
  - Impact: Path policy actually enforced

- [ ] **T7.2** Sanitize pip install spec to prevent argument injection (TD-332)
  - File: `app/plugins/api.py` ~L270–L293
  - Change: Strip flags/options from spec; only allow `name[extras]==version` pattern
  - Impact: Prevents `--index-url` injection via dependency spec

- [ ] **T7.3** Store fire-and-forget task references (TD-326)
  - Files: `app/api/ws.py`, `app/api/routers/messages.py`, `app/api/routers/sessions.py`
  - Change: Collect task refs in a set; add `done_callback` to discard + log exceptions
  - Impact: No more "Task exception was never retrieved" warnings

- [ ] **T7.4** Add Ollama httpx client lifecycle cleanup (TD-282)
  - File: `app/providers/ollama.py`
  - Change: Register `close()` in app shutdown hook; or use context manager pattern
  - Impact: HTTP connections properly closed

- [ ] **T7.5** Reset connection state in `shutdown()` (TD-329)
  - File: `app/db/connection.py` ~L204
  - Change: Clear `_app_db_path` and `_write_locks` dict after closing connections
  - Impact: Clean state for test isolation and restarts

- [ ] **T7.6** Handle corrupt JSON rows in `MemoryExtract.from_row` (TD-309)
  - File: `app/memory/models.py` ~L207–L209
  - Change: Wrap `json.loads()` in try/except; log warning and use empty default
  - Impact: One corrupt row doesn't crash entire listing

### Batch 7 Tests
- [ ] Add unit test: `allows_path` blocks `../` traversal
- [ ] Add unit test: pip install rejects `--index-url` in spec
- [ ] Add unit test: fire-and-forget tasks log exceptions
- [ ] Add unit test: Ollama client cleanup on shutdown
- [ ] Add unit test: shutdown resets connection state
- [ ] Add unit test: corrupt JSON row handled gracefully

---

## Batch 8 — Low-Severity Cleanup & Polish (31 tasks)

*Code quality, edge cases, minor performance, UX polish. Can be done opportunistically.*

### Provider Cleanup
- [ ] **T8.1** Fix multiple system message handling in Anthropic (TD-280) — join instead of overwrite
- [ ] **T8.2** Remove misleading `supports_thinking` on o1/o3-mini (TD-286) — set to False
- [ ] **T8.3** Move `import json` to module level in Anthropic (TD-290) — one-line move
- [ ] **T8.4** Fix MockProvider duplicate usage events (TD-291) — emit only one
- [ ] **T8.5** Add lock to `is_available()` in CircuitBreaker (TD-292) — match write methods
- [ ] **T8.6** Fix `list_all_models` shared list mutation (TD-285) — use per-provider lists, merge

### Memory & Knowledge Cleanup
- [ ] **T8.7** Fix `_parse_json_response` nested bracket handling (TD-310) — use balanced bracket matching
- [ ] **T8.8** Optimize embedding cache invalidation (TD-311) — only clear affected source_type
- [ ] **T8.9** Convert `run_orphan_report` to cursor pagination (TD-312) — match existing pattern
- [ ] **T8.10** Filter negative indices in `_step1_classify` (TD-313) — `if idx < 0: continue`
- [ ] **T8.11** Make merge confidence bump configurable (TD-318) — add to config
- [ ] **T8.12** Optimize `shortest_path` with parent map (TD-316) — reconstruct path on find

### Tools & Plugins Cleanup
- [ ] **T8.13** Exclude `self` from `_build_json_schema` (TD-314) — skip first param for bound methods
- [ ] **T8.14** Fix `_register_builtins` ImportError handling (TD-335) — re-raise non-ModuleNotFoundError
- [ ] **T8.15** Clean `sys.modules` on failed plugin load (TD-336) — remove partial module entry

### Sessions & Policy Cleanup
- [ ] **T8.16** Return copies from `SessionPolicyPresets.by_name()` (TD-333) — `copy.deepcopy(preset)`
- [ ] **T8.17** Add `"tool"` to `Message.role` Literal type (TD-334) — align with `_VALID_ROLES`
- [ ] **T8.18** Fix `prefetch_background` to touch recalled memories (TD-302) — use actual recall IDs

### API & UX Cleanup
- [ ] **T8.19** Fix messages pagination total (TD-325) — add COUNT query
- [ ] **T8.20** Replace hardcoded stubs in `system_status` (TD-328) — query actual store counts
- [ ] **T8.21** De-duplicate budget alerts (TD-306) — track last alert time, throttle to once per minute

### Provider Thinking Support (Deferred/Optional)
- [ ] **T8.22** Handle Anthropic thinking content blocks (TD-273) — emit as metadata or reasoning field
- [ ] **T8.23** Send extended thinking API params (TD-274) — `thinking={"type": "enabled", ...}`

### Logging & Observability
- [ ] **T8.24** Fix `_JSONFormatter` attribute leakage (TD-322) — use allow-list instead of deny-list
- [ ] **T8.25** Fix `create_note` TOCTOU race (TD-317) — use `open(path, 'x')` mode

### Agent Cleanup
- [ ] **T8.26** Fix `AgentStore.clone()` to copy all fields (TD-279) — add missing tools, skills, default_policy, memory_scope, escalation, context_budget, status
- [ ] **T8.27** Fix tool token double-counting (TD-323) — count only once in prompt assembly

---

## Execution Order & Dependencies

```
Batch 1 (Critical one-liners)     ──┐
                                     ├──→ Run full test suite
Batch 2 (High-severity fixes)     ──┘

Batch 3 (LIKE/SQL fixes)          ──┐
                                     ├──→ Run full test suite
Batch 4 (Unbounded dict eviction) ──┘

Batch 5 (Concurrency hardening)   ──→ Run full test suite (+ migration for T5.2)

Batch 6 (Performance)             ──┐
                                     ├──→ Run full test suite
Batch 7 (Security & reliability)  ──┘

Batch 8 (Low-severity polish)     ──→ Run full test suite (can be split across sessions)
```

---

## Testing Strategy

- **Baseline**: 935 unit + 220 integration tests passing
- **Per-batch**: Run full unit suite after each batch; integration suite after every 2 batches
- **New tests**: Each batch includes specific test tasks (listed above)
- **Regression gate**: No batch merge until baseline + new tests all pass

---

## Definition of Done

- [ ] All 3 Critical items resolved (TD-270, TD-294, TD-295)
- [ ] All 8 High items resolved (TD-271/272, TD-275/276/278, TD-293, TD-301, TD-305, TD-324)
- [ ] All 25 Medium items resolved (TD-273/274/277/279/281–283/287/296–300/302–304/306–309/315/319–321/323/325–332)
- [ ] All 31 Low items resolved (TD-280/284–286/288–292/310–314/316–318/322/333–336)
- [ ] All new unit tests passing
- [ ] Full test suite green: unit + integration
- [ ] Audit documents updated with resolution status
