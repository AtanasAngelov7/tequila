# Post-Cleanup Tech Debt Findings — March 2026

**Scope**: Full codebase audit after resolution of TD-001 through TD-269
**New issues**: TD-270 through TD-336 (67 findings)
**Audit date**: March 17, 2026
**Reference**: [sprint_15_tech_debt_audit.md](sprint_15_tech_debt_audit.md) — full details, code locations, and fix descriptions

---

## Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| **Critical** | 3 | Silent error loss, runtime crashes, dead code paths |
| **High** | 8 | Dead retry/fallback logic, OCC bugs, setup key discarded, memory leaks |
| **Medium** | 25 | N+1 queries, unbounded caches, security holes, incomplete prior fixes |
| **Low** | 31 | Code quality, edge cases, minor performance, UX polish |
| **Total** | **67** | |

---

## Critical Findings (3)

| ID | File(s) | Issue | Impact |
|----|---------|-------|--------|
| **TD-270** | `providers/anthropic.py`, `providers/openai.py` | Error events use `error=str(exc)` but field is `error_message` | All provider error messages silently lost; users see "Unknown provider error" |
| **TD-294** | `memory/lifecycle.py` | `hit.score` should be `hit.similarity` | `AttributeError` crashes memory merge — consolidation completely broken |
| **TD-295** | `knowledge/graph.py` | `rebuild_semantic_edges()` queries non-existent `graph_nodes` table | Entire function is dead code; `except: pass` hides the failure |

---

## High Findings (8)

| ID | File(s) | Issue | Impact |
|----|---------|-------|--------|
| **TD-271** | `providers/circuit_breaker.py` | `call()` wraps async gen at creation, not iteration — retry/failure recording dead | Circuit breaker never opens on streaming failures |
| **TD-272** | `providers/circuit_breaker.py` | `GracefulDegradation` fallback try/except fires at gen creation | Fallback provider never activated on streaming errors |
| **TD-275** | `sessions/store.py` | `remove_turn_queue(session_id)` but queues keyed by `session_key` | Turn queues for archived/deleted sessions never freed — memory leak |
| **TD-276** | `agent/turn_loop.py`, `prompt_assembly.py` | Tool results injected as user messages on multi-round tool calls | Prompt corruption on 2nd+ tool execution rounds |
| **TD-278** | `agent/store.py` | `AgentStore.update()` OCC loop raises unconditionally on first conflict | OCC retry mechanism completely non-functional |
| **TD-293** | `memory/lifecycle.py` | `run_decay` uses offset pagination; score updates shift rows | Rows skipped or double-processed during decay |
| **TD-301** | `memory/entity_store.py` | `EntityStore.update` returns stale data after OCC exhaustion | Silent data loss — caller believes update succeeded |
| **TD-305** | `budget/__init__.py` | `set_cap()` returns new UUID, not actual ID after upsert conflict | Clients get 404s using returned ID |
| **TD-324** | `api/routers/setup.py` | Setup wizard validates API key then discards it | Provider fails on first use unless key set in env |

---

## Medium Findings (25)

### Bugs
| ID | File | Issue |
|----|------|-------|
| TD-273 | `providers/anthropic.py` | Silently drops thinking/reasoning content blocks |
| TD-277 | `prompt_assembly.py` | History messages lose `tool_calls` and `tool_call_id` |
| TD-279 | `agent/store.py` | `clone()` drops tools, skills, policy, memory_scope, escalation, context_budget, status |
| TD-302 | `memory/recall.py` | `prefetch_background` touches LIKE-matched memories, not recalled ones |
| TD-309 | `memory/models.py` | `MemoryExtract.from_row` uncaught `json.JSONDecodeError` — one bad row crashes all |
| TD-315 | `memory/recall.py` | FTS fallback passes raw 200-char user message as LIKE pattern |
| TD-323 | `prompt_assembly.py` | Tool token budget double-counted in system prompt and Step 5 |
| TD-325 | `api/routers/messages.py` | Pagination `total` = page size, not true total |
| TD-306 | `budget/__init__.py` | Alert fires every turn above 80% — burst of duplicates |
| TD-328 | `api/routers/system.py` | `system_status` returns hardcoded stubs for initialized stores |

### Performance
| ID | File | Issue |
|----|------|-------|
| TD-283 | `agent/turn_loop.py` | `_session_locks` dict grows unbounded |
| TD-287 | `agent/sub_agent.py` | `_active` and `_spawn_locks` grow unbounded |
| TD-296 | `tools/executor.py` | Unbounded `_pending`, `_allow_all`, `_session_approvals` |
| TD-298 | `memory/recall.py` | N+1 queries in `recall_for_turn` semantic search (15 individual gets) |
| TD-299 | `memory/recall.py` | N+1 queries in `_entity_expand` (up to 65 queries) |
| TD-303 | `budget/__init__.py` | `is_blocked()` still uses LIKE — TD-160 incomplete |
| TD-304 | `budget/__init__.py` | `get_summary`, `get_by_agent`, `get_by_provider` also use LIKE |
| TD-308 | `knowledge/vault.py` | `sync_from_disk` reads ALL files unconditionally |
| TD-321 | `agent/context.py` | `compress_trim_oldest` still O(n²) |
| TD-327 | `api/routers/system.py` | `system_status` queries providers sequentially |
| TD-330 | `db/web_cache.py` | `purge_expired()` loads entire `web_cache` table into memory |

### Concurrency
| ID | File | Issue |
|----|------|-------|
| TD-281 | `providers/registry.py` | Double-checked locking creates new Lock each time |
| TD-300 | `memory/entity_store.py` | OCC uses timestamp, not version counter — same-ms races |
| TD-307 | `memory/store.py` | `_sync_entity_ids_json` SELECT outside write transaction |
| TD-319 | `sessions/branching.py` | Branching not atomic with turn execution |
| TD-331 | `workflows/runtime.py` | Parallel mode ignores `cancel_event` during execution |

### Security
| ID | File | Issue |
|----|------|-------|
| TD-274 | `providers/anthropic.py` | Never sends extended thinking API params |
| TD-282 | `providers/ollama.py` | httpx client has no lifecycle cleanup |
| TD-297 | `memory/store.py`, `entity_store.py`, `vault.py` | LIKE wildcard injection in search |
| TD-320 | `sessions/policy.py` | `allows_path` does no path normalization — traversal risk |
| TD-326 | `api/ws.py`, routers | Fire-and-forget tasks — unhandled exception warnings |
| TD-329 | `db/connection.py` | `shutdown()` doesn't reset `_app_db_path` or `_write_locks` |
| TD-332 | `plugins/api.py` | `install_dependencies` allows pip argument injection |

---

## Low Findings (31)

| ID | File | Issue |
|----|------|-------|
| TD-280 | `providers/anthropic.py` | Multiple system messages silently overwritten |
| TD-284 | `providers/registry.py` | Capability cache grows unbounded |
| TD-285 | `providers/registry.py` | `list_all_models` concurrent list mutation |
| TD-286 | `providers/openai.py` | o1/o3-mini `supports_thinking=True` but never handled |
| TD-288 | `audit/log.py` | `query_audit_log` LIKE wildcards not escaped |
| TD-289 | `providers/circuit_breaker.py` | `_circuit_registry` has no cleanup |
| TD-290 | `providers/anthropic.py` | `import json` inside hot streaming loop |
| TD-291 | `providers/mock.py` | Duplicate usage events |
| TD-292 | `providers/circuit_breaker.py` | `is_available()` reads state without lock |
| TD-310 | `memory/extraction.py` | `_parse_json_response` regex fails on nested brackets |
| TD-311 | `knowledge/embeddings.py` | Cache invalidation clears ALL filter variants |
| TD-312 | `memory/lifecycle.py` | `run_orphan_report` uses offset pagination |
| TD-313 | `memory/extraction.py` | `_step1_classify` doesn't filter negative LLM indices |
| TD-314 | `tools/registry.py` | `_build_json_schema` includes `self` parameter |
| TD-316 | `knowledge/graph.py` | `shortest_path` copies entire path list per BFS step |
| TD-317 | `knowledge/vault.py` | `create_note` TOCTOU race |
| TD-318 | `memory/extraction.py` | Hardcoded merge confidence bump (0.05) |
| TD-322 | `audit/logger.py` | `_JSONFormatter` leaks internal LogRecord attributes |
| TD-333 | `sessions/policy.py` | `by_name()` returns shared mutable instances |
| TD-334 | `sessions/models.py` | `Message.role` Literal missing `"tool"` |
| TD-335 | `plugins/registry.py` | `_register_builtins` swallows real ImportErrors |
| TD-336 | `plugins/discovery.py` | Failed plugin loads pollute `sys.modules` |

---

## Cross-Cutting Patterns

### 1. Async Generator Error Handling
TD-271, TD-272 share the same root cause: try/except around async generator *creation* instead of *iteration*. Affects circuit breaker and graceful degradation — the entire provider reliability layer.

### 2. Unbounded In-Memory Dicts
TD-283, TD-287, TD-284, TD-289, TD-296 — five separate modules accumulate per-session or per-provider state with no eviction. Combined effect grows linearly with sessions over app lifetime.

### 3. Incomplete LIKE→Range Migration
TD-160 was marked resolved but only `_check_caps` was converted. TD-303, TD-304 show 4 more budget methods still use LIKE. TD-297 adds wildcard injection in 3 search methods.

### 4. OCC Implementation Gaps
TD-278 (AgentStore), TD-301 (EntityStore), TD-300 (timestamp-based) — three stores have broken or weak optimistic concurrency control, despite correct implementation in SessionStore and MemoryStore.

### 5. Tool Call Prompt Assembly
TD-276, TD-277, TD-323 — the prompt assembly pipeline doesn't properly handle multi-round tool conversations: results become user messages, tool metadata is stripped, and token budgets are double-counted.
