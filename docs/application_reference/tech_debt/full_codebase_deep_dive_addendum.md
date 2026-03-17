# Tech Debt Audit — Full Codebase Deep Dive (Addendum)

**Audited**: Full codebase — all sprints, deep investigation into core modules, providers, frontend, migrations, cross-cutting patterns
**Extends**: [sprint_12_14b_tech_debt.md](sprint_12_14b_tech_debt.md) (TD-138 through TD-192)
**New issues**: TD-193 through TD-269 (77 findings)
**Audit date**: March 17, 2026

---

## Resolution Status (Updated March 17, 2026)

**70 of 77 issues resolved. 7 deferred.**

All code changes validated with 935 unit tests passing + 230+ integration tests passing.
See [tech_debt_cleanup_report.md](tech_debt_cleanup_report.md) for full details.

| Status | Count | IDs |
|--------|-------|-----|
| ✅ Resolved | 70 | TD-193–244, TD-247–264 |
| ⬜ Deferred | 7 | TD-245 (risky historic migration), TD-246 (risky migration), TD-265 (Fernet TTL acceptable), TD-266 (Ollama has close()), TD-267 (needs tiktoken), TD-268 (low priority), TD-269 (needs new migration) |

---

## Executive Summary

A comprehensive deep-dive audit beyond the S12–14b surface-level scan uncovered **77 additional issues** spanning every layer of the application. The most alarming cluster is **silently broken features**: scheduled tasks never execute due to a payload key mismatch (TD-193), semantic recall always fails on an attribute error (TD-199), memory extraction dedup is completely disabled by 5 parameter mismatches (TD-200), the circuit breaker materialises entire streams defeating real-time streaming (TD-196), and `regenerate()` picks the wrong user message corrupting branched conversations (TD-203).

The second cluster is **security gaps** uncovered in previously unexamined layers: the Fernet encryption key is stored in plaintext in the same database it protects (TD-194), WebSocket accepts arbitrary message `role` from clients (TD-229), the prompt assembly injects fake assistant messages that can be exploited for context manipulation (TD-210), and tool executor passes LLM-hallucinated kwargs directly to functions (TD-219).

The third cluster is **unbounded memory growth**: buffers never evicted for abandoned sessions (TD-205), per-session context budget and token counter caches grow without limit (TD-212, TD-213), and fire-and-forget tasks are GC'd before completion (TD-204).

| Severity | Count | Description |
|----------|-------|-------------|
| **Critical** | 8 | Broken scheduler, broken semantic recall, broken extraction dedup, stream materialisation, Fernet key in DB, regenerate bug, `await` on async gen, graph embeds UUIDs |
| **High** | 12 | Concurrent turns, fire-and-forget GC, prompt double-count, history budget calc, active_turn_count wrong, ConfigStore OCC, tool shadowing, BFS wrong, provider stream errors, WS role injection, stale session filters, agent import unvalidated |
| **Medium** | 27 | Frontend UX/a11y, API gaps, concurrency races, performance, migration downgrades, design issues |
| **Low** | 30 | Minor code quality, missing indexes, accessibility, UX polish, minor design |
| **Total** | **77** | |

---

## Quick Reference

| ID | Title | Sev | Category | Status |
|----|-------|-----|----------|--------|
| [TD-193](#td-193) | Scheduler→TurnLoop payload key mismatch — cron jobs never execute | **Crit** | Bug | ✅ |
| [TD-194](#td-194) | Fernet encryption key stored in plaintext SQLite | **Crit** | Security | ✅ |
| [TD-195](#td-195) | `regenerate()` picks wrong preceding user message — corrupts branches | **Crit** | Bug | ✅ |
| [TD-196](#td-196) | Circuit breaker materialises entire stream — defeats real-time streaming | **Crit** | Performance | ✅ |
| [TD-197](#td-197) | `GracefulDegradation.stream_completion()` — `await` on async generator crashes | **Crit** | Bug | ✅ |
| [TD-198](#td-198) | `rebuild_semantic_edges()` embeds UUID strings instead of node content | **Crit** | Bug | ✅ |
| [TD-199](#td-199) | `recall_for_turn` accesses nonexistent `r.score` — semantic recall silently broken | **Crit** | Bug | ✅ |
| [TD-200](#td-200) | Extraction `_step3_dedup` — 5 parameter mismatches disable dedup entirely | **Crit** | Bug | ✅ |
| [TD-201](#td-201) | No concurrent turn guard per session — parallel turns corrupt state | **High** | Concurrency | ✅ |
| [TD-202](#td-202) | Prompt assembly double-counts skill tokens — premature history truncation | **High** | Bug | ✅ |
| [TD-203](#td-203) | History budget uses wrong baseline — can go negative, zero history included | **High** | Bug | ✅ |
| [TD-204](#td-204) | Fire-and-forget tasks in `emit_nowait` are unreferenced — GC'd silently | **High** | Bug | ✅ |
| [TD-205](#td-205) | BufferRegistry never evicts abandoned session buffers — memory leak | **High** | Performance | ✅ |
| [TD-206](#td-206) | `active_turn_count()` counts queued, not active — inverted semantics | **High** | Bug | ✅ |
| [TD-207](#td-207) | `ConfigStore.set()` OCC has no row-count check — silent write loss | **High** | Bug | ✅ |
| [TD-208](#td-208) | Tool shadowing: no protection against post-startup overwrites | **High** | Security | ✅ |
| [TD-209](#td-209) | `shortest_path` BFS limited by node count, not hop depth | **High** | Bug | ✅ |
| [TD-210](#td-210) | Anthropic/OpenAI stream errors propagate raw — no error/done events | **High** | Error Handling | ✅ |
| [TD-211](#td-211) | Duplicate task execution on overlapping scheduler ticks | **High** | Bug | ✅ |
| [TD-212](#td-212) | `_default_llm_fn` imports nonexistent function — extraction silently returns `[]` | **High** | Bug | ✅ |
| [TD-213](#td-213) | Static mount at "/" swallows API 404s — returns HTML instead of JSON | **Med** | Bug | ✅ |
| [TD-214](#td-214) | Partial startup leaves orphaned singletons on mid-lifespan failure | **Med** | Design | ✅ |
| [TD-215](#td-215) | CORS origins parsed without format validation — `*` accepted silently | **Med** | Security | ✅ |
| [TD-216](#td-216) | Off-by-one in `events_since` resync detection — client misses one event | **Med** | Bug | ✅ |
| [TD-217](#td-217) | No `event_type` validation on `GatewayEvent` construction | **Med** | Design | ✅ |
| [TD-218](#td-218) | Untracked fire-and-forget tasks for recall prefetch and extraction | **Med** | Bug | ✅ |
| [TD-219](#td-219) | Exception during tool loop leaves orphaned tool messages in history | **Med** | Bug | ✅ |
| [TD-220](#td-220) | `ContextBudget` cache unbounded — grows for every session without eviction | **Med** | Performance | ✅ |
| [TD-221](#td-221) | `TokenCounter._cache` unbounded per-session — no LRU eviction | **Med** | Performance | ✅ |
| [TD-222](#td-222) | Synthetic assistant "Understood." messages pollute context | **Med** | Design | ✅ |
| [TD-223](#td-223) | `min_recent_messages` not fully honoured — adds 1 instead of N | **Med** | Bug | ✅ |
| [TD-224](#td-224) | Turn queues leak for archived/idle sessions | **Med** | Performance | ✅ |
| [TD-225](#td-225) | `get_active_chain` silently truncates at 1000 messages | **Med** | Bug | ✅ |
| [TD-226](#td-226) | `deactivate_from` timestamp ordering fragile under fast inserts | **Med** | Bug | ✅ |
| [TD-227](#td-227) | `execute_script` splits on `;` inside string literals | **Med** | Bug | ✅ |
| [TD-228](#td-228) | LLM-supplied `**arguments` passed directly to tool functions unsanitised | **Med** | Security | ✅ |
| [TD-229](#td-229) | WebSocket `message.send` allows any `role` from client | **High** | Security | ✅ |
| [TD-230](#td-230) | WS reconnect doesn't re-resume active session | **High** | Bug | ✅ |
| [TD-231](#td-231) | Global WS event buffer leaks events across sessions | **Med** | Bug | ✅ |
| [TD-232](#td-232) | SessionList only loads on mount — filter changes don't trigger reload | **High** | Bug | ✅ |
| [TD-233](#td-233) | Agent import endpoint accepts arbitrary unvalidated JSON | **High** | Security | ✅ |
| [TD-234](#td-234) | `system.py` missing `logger` import — `NameError` at runtime | **Med** | Bug | ✅ |
| [TD-235](#td-235) | Nested `write_transaction` causes deadlock (non-reentrant lock) | **Med** | Concurrency | ✅ |
| [TD-236](#td-236) | `_is_turn_active` ignores `agent_id`, uses global check | **Med** | Bug | ✅ |
| [TD-237](#td-237) | No timezone consistency in scheduler `next_run` computation | **Med** | Bug | ✅ |
| [TD-238](#td-238) | `_build_json_schema` doesn't handle Optional/Union/complex types | **Med** | Bug | ✅ |
| [TD-239](#td-239) | Anthropic usage events split across two stream events | **Med** | Design | ✅ |
| [TD-240](#td-240) | `GracefulDegradation` records success before stream consumption | **Med** | Bug | ✅ |
| [TD-241](#td-241) | `decrypt_credential` catches overly broad Exception | **Med** | Error Handling | ✅ |
| [TD-242](#td-242) | LIKE-injection in memory/vault search (`%` and `_` not escaped) | **Med** | Bug | ✅ |
| [TD-243](#td-243) | `skills` / `skill_resources` duplicated in migrations 0004 and 0016 | **High** | Migration | ✅ |
| [TD-244](#td-244) | `audit_log` schema conflict between migrations 0001 and 0007 | **Med** | Migration | ✅ |
| [TD-245](#td-245) | 0005 downgrade is `pass` — 16 columns can't be rolled back | **Med** | Migration | ⬜ |
| [TD-246](#td-246) | 0004 downgrade destroys 0003's index + CHECK constraint on agents | **Med** | Migration | ⬜ |
| [TD-247](#td-247) | 10 FK-like columns lack REFERENCES constraints | **Med** | Schema | ✅ |
| [TD-248](#td-248) | ExportMenu dropdown never closes on outside click | **Med** | UX | ✅ |
| [TD-249](#td-249) | Navigation divs lack keyboard Enter/Space handling | **Med** | Accessibility | ✅ |
| [TD-250](#td-250) | Sidebar nav uses divs instead of semantic `<nav>`/`<Link>` elements | **Med** | Accessibility | ✅ |
| [TD-251](#td-251) | MessageList auto-scroll fires on every streaming delta — causes jank | **Med** | Performance | ✅ |
| [TD-252](#td-252) | `send()` silently drops messages when WebSocket is not OPEN | **Med** | Bug | ✅ |
| [TD-253](#td-253) | `App.tsx` treats setup-status fetch failure as "app ready" | **Med** | Bug | ✅ |
| [TD-254](#td-254) | `chatStore.ts` WS payload cast without runtime validation | **Med** | Bug | ✅ |
| [TD-255](#td-255) | No error feedback to user on `agent.run.error` WS event | **Med** | UX | ✅ |
| [TD-256](#td-256) | `graph.py` orphans endpoint — bare `except Exception: pass` hides errors | **Med** | Observability | ✅ |
| [TD-257](#td-257) | `save_plugin_credential` writes via read-only DB connection dep | **Med** | Bug | ✅ |
| [TD-258](#td-258) | `skills.py` skill update has no OCC — concurrent updates silently overwrite | **Med** | Concurrency | ✅ |
| [TD-259](#td-259) | ExportMenu/BackupPage bypass `api` client — duplicate auth logic | **Low** | Design | ✅ |
| [TD-260](#td-260) | `alert()` used for error reporting in ExportMenu | **Low** | UX | ✅ |
| [TD-261](#td-261) | O(n²) trim strategy in `compress_trim_oldest` | **Low** | Performance | ✅ |
| [TD-262](#td-262) | Missing cancellation/timeout event types in gateway events | **Low** | Design | ✅ |
| [TD-263](#td-263) | Ollama first tool call chunk may drop arguments | **Low** | Bug | ✅ |
| [TD-264](#td-264) | `ProviderRegistry.global_registry()` not thread-safe (unused lock) | **Low** | Concurrency | ✅ |
| [TD-265](#td-265) | Fernet tokens have no TTL — leaked tokens valid forever | **Low** | Security | ⬜ |
| [TD-266](#td-266) | Ollama `httpx.AsyncClient` resource leak on GC | **Low** | Performance | ⬜ |
| [TD-267](#td-267) | OpenAI token counting underestimates real usage | **Low** | Accuracy | ⬜ |
| [TD-268](#td-268) | Embeddings `_load_vectors` duplicates data across cache keys | **Low** | Performance | ⬜ |
| [TD-269](#td-269) | Missing indexes on `sessions.parent_session_key`, `notifications.source_session_key` | **Low** | Schema | ⬜ |

---

## Critical Severity

### TD-193

**Scheduler→TurnLoop payload key mismatch — cron jobs never execute**

- **File**: `app/scheduler/engine.py` lines 200–208 / `app/agent/turn_loop.py` lines 82–87
- **Category**: Bug

`SchedulerEngine._fire_task()` emits `INBOUND_MESSAGE` with `payload={"text": prompt, "role": "user"}`, but `TurnLoop.handle_inbound()` reads `payload.get("session_id", "")` and `payload.get("content", "")`. The scheduler uses key `"text"` instead of `"content"`, and omits `"session_id"` entirely. Every scheduled task silently fails — the turn loop sees no session_id and returns immediately.

**Fix**: Change payload to `{"session_id": session.session_id, "content": prompt}`.

---

### TD-194

**Fernet encryption key stored in plaintext SQLite**

- **File**: `app/api/app.py` lines 97–104
- **Category**: Security

The auto-generated Fernet encryption key is persisted to the `config` table via `config_store.set("auth.encryption_key", _enc_key)`. The `config` table uses no encryption itself. Anyone with file-level read access to `data/tequila.db` can extract the master encryption key, defeating all credential encryption in the auth subsystem.

**Fix**: Store the key in an OS keyring, derive it from a `TEQUILA_SECRET_KEY` env var, or at minimum never persist it in the same DB it protects.

---

### TD-195

**`regenerate()` picks wrong preceding user message — corrupts branches**

- **File**: `app/sessions/branching.py` lines 66–85
- **Category**: Bug

The reversed iteration finds the first `role="user"` message scanning backward from the END of the chain. For a chain `[user1, assistant1, user2, assistant2]` when regenerating `assistant1`, the scan hits `user2` (chronologically AFTER `assistant1`), not `user1`. The regeneration replays the wrong prompt.

**Fix**: Iterate forward. Track last-seen user message. When encountering the target message_id, use the last-seen user content.

---

### TD-196

**Circuit breaker materialises entire stream — defeats real-time streaming**

- **File**: `app/providers/circuit_breaker.py` lines 195–206
- **Category**: Performance / Architectural

`CircuitBreaker.call()` buffers ALL stream events into a `list` before returning them via `_iter_list()`. The client receives zero events until the entire LLM response is finished, spiking memory and latency.

**Fix**: Yield events directly from the inner async-for. Track success/failure via a sentinel "done" event rather than full materialisation.

---

### TD-197

**`GracefulDegradation.stream_completion()` — `await` on async generator crashes**

- **File**: `app/providers/circuit_breaker.py` lines 299–306
- **Category**: Bug

`stream = await provider.stream_completion(...)` — all provider `stream_completion` methods are async generators (use `yield`). Async generators are not awaitable. This line raises `TypeError: object async_generator can't be used in 'await' expression`, crashing every fallback attempt.

**Fix**: Remove the `await` — call `provider.stream_completion(...)` directly.

---

### TD-198

**`rebuild_semantic_edges()` embeds UUID strings instead of node content**

- **File**: `app/knowledge/graph.py` lines 491–498
- **Category**: Bug

`await emb_store.search(nid, ...)` where `nid` is a UUID primary key string. `EmbeddingStore.search()` embeds the query text. Embedding a UUID produces a meaningless vector; the resulting "semantic_similar" edges are garbage.

**Fix**: Fetch the actual content text for each node from its source table and pass that to `emb_store.search()`.

---

### TD-199

**`recall_for_turn` accesses nonexistent `r.score` — semantic recall silently broken**

- **File**: `app/memory/recall.py` line 222
- **Category**: Bug

`score = float(r.score)` — `EmbeddingSearchResult` has `similarity`, not `score`. This raises `AttributeError`, caught by the surrounding `except Exception`. Semantic memory search silently fails every time, falling through to the FTS fallback.

**Fix**: Change `r.score` → `r.similarity`.

---

### TD-200

**Extraction `_step3_dedup` — 5 parameter mismatches disable dedup entirely**

- **File**: `app/memory/extraction.py` lines 349–371
- **Category**: Bug

`emb_store.search(text=content, source_type="memory", top_k=3, ...)` uses wrong keyword arguments (should be `query`, `source_types`, `limit`). Additionally `top.score` should be `top.similarity` and `top.item.source_id` should be `top.source_id`. All raise TypeError/AttributeError, caught silently. Dedup always returns `"create"`.

**Fix**: `emb_store.search(content, source_types=["memory"], limit=3, ...)`, `top.similarity`, `top.source_id`.

---

## High Severity

### TD-201

**No concurrent turn guard per session — parallel turns corrupt state**

- **File**: `app/agent/turn_loop.py` lines 118–160
- **Category**: Concurrency

`_run_full_turn` has no lock or semaphore. Two rapid `INBOUND_MESSAGE` events for the same session run simultaneously, both persisting user messages and assembling prompts, leading to unreliable message ordering.

**Fix**: Acquire a per-session asyncio lock before entering `_run_full_turn`.

---

### TD-202

**Prompt assembly double-counts skill tokens — premature history truncation**

- **File**: `app/agent/prompt_assembly.py` lines 139–149, 183–190
- **Category**: Bug

Skill text is embedded into the system prompt via Jinja2 (Step 1) and counted as system prompt tokens. Step 4 adds skill tokens AGAIN to `ctx.tokens_used`. This double-counting inflates apparent usage, causing premature history truncation.

**Fix**: Remove Step 4 skill token additions (already counted in system prompt).

---

### TD-203

**History budget uses wrong baseline — can go negative, zero history included**

- **File**: `app/agent/prompt_assembly.py` lines 235–236
- **Category**: Bug

`history_budget = budget.history_budget - ctx.tokens_used` subtracts cumulative tokens from a slot-specific budget. If the system prompt alone uses 3000 tokens and `history_budget` is 2000, the result is -1000.

**Fix**: Use `ctx.remaining()` or compute `max(0, budget.max_context_tokens - budget.reserved_for_response - ctx.tokens_used)`.

---

### TD-204

**Fire-and-forget tasks in `emit_nowait` are unreferenced — GC'd silently**

- **File**: `app/gateway/router.py` lines 133–139
- **Category**: Bug

`asyncio.create_task(self.emit(event))` discards the reference. Per Python docs, the event loop holds only a weak reference. If GC runs before completion, the task is destroyed and the event is silently dropped.

**Fix**: Store task references in a `set`; remove in a done-callback.

---

### TD-205

**BufferRegistry never evicts abandoned session buffers — memory leak**

- **File**: `app/gateway/buffer.py` lines 92–105
- **Category**: Performance

`BufferRegistry._buffers` grows for every new `session_key`. Buffers are only removed by explicit `remove()`. Sessions that go idle or get archived without cleanup leave `SessionBuffer` objects in memory indefinitely.

**Fix**: Add periodic sweep removing buffers for sessions no longer "active".

---

### TD-206

**`active_turn_count()` counts queued, not active — inverted semantics**

- **File**: `app/sessions/store.py` lines 53–60
- **Category**: Bug

Counts non-empty queues, but an actively processing turn has already dequeued its item (queue is empty). A session mid-turn reads as "no active turn"; a session with queued-but-unprocessed messages reads as "active". The scheduler relies on this, giving inverted results.

**Fix**: Track active turns with a `set[str]` of session_keys that add on turn start and remove on turn end.

---

### TD-207

**`ConfigStore.set()` OCC has no row-count check — silent write loss**

- **File**: `app/config.py` lines 225–235
- **Category**: Bug

The `UPDATE` uses version for OCC but never inspects `cursor.rowcount`. If the version changed (concurrent writer), zero rows are updated but the code proceeds to update `self._cache`. The caller thinks the write succeeded.

**Fix**: Check `cursor.rowcount == 0` after UPDATE. If so, retry or raise `ConflictError`.

---

### TD-208

**Tool shadowing: no protection against post-startup overwrites**

- **File**: `app/tools/registry.py` lines 82–85
- **Category**: Security

`register()` silently overwrites existing tool entries with just a warning log. A malicious plugin loaded after startup can replace a built-in tool with an arbitrary implementation.

**Fix**: Add a `frozen` flag preventing overwrites after initial registration, or separate namespaces.

---

### TD-209

**`shortest_path` BFS limited by node count, not hop depth**

- **File**: `app/knowledge/graph.py` lines 517–539
- **Category**: Bug

`for _ in range(max_depth)` iterates `max_depth` times, popping ONE node per iteration. Only `max_depth` nodes total are explored — not `max_depth` levels of BFS.

**Fix**: Track depth per queued path. Use `while queue:` with a depth check.

---

### TD-210

**Anthropic/OpenAI stream errors propagate raw — no error/done events**

- **File**: `app/providers/anthropic.py` lines 175–254 / `app/providers/openai.py` lines 157–228
- **Category**: Error Handling

Neither provider wraps the streaming loop in try/except. Rate limits, network errors, and auth failures propagate raw. Consumers never receive error/done events. Ollama's provider does this correctly.

**Fix**: Wrap stream body in try/except, yield `ProviderStreamEvent(kind="error")` then `kind="done"`.

---

### TD-211

**Duplicate task execution on overlapping scheduler ticks**

- **File**: `app/scheduler/engine.py` lines 129–141
- **Category**: Bug

`_tick()` fires tasks via `create_task()`. The task's `next_run_at` is updated AFTER `_run_task_with_deferral` completes (including 60s deferral). Meanwhile `_tick()` runs every 30s and re-loads tasks. Since `next_run_at` hasn't been updated, the same task fires again.

**Fix**: Update `next_run_at` optimistically BEFORE firing the task.

---

### TD-212

**`_default_llm_fn` imports nonexistent function — extraction silently returns `[]`**

- **File**: `app/memory/extraction.py` lines 164–180
- **Category**: Bug

`from app.providers.registry import get_provider_registry` — the actual function is `get_registry`, not `get_provider_registry` (ImportError). Also `registry.providers.values()` should be `registry._providers`. Exceptions caught silently → zero extractions.

**Fix**: Import `get_registry`, use `registry.list_providers()`.

---

### TD-229

**WebSocket `message.send` allows any `role` from client**

- **File**: `app/api/ws.py` line 163
- **Category**: Security

`handle_message_send` reads `role: str = params.get("role", "user")`. A malicious client can send `role: "assistant"` or `role: "system"` to inject messages that appear to come from the AI.

**Fix**: Force `role = "user"` for client-sent messages.

---

### TD-230

**WS reconnect doesn't re-resume active session**

- **File**: `frontend/src/api/ws.ts` lines 37–44
- **Category**: Bug

On reconnect, a new WebSocket is created and `connect` is sent. But `session.resume` is not re-sent — the active session goes silent until the user manually switches sessions.

**Fix**: After `onopen` + connect handshake, automatically re-send `session.resume` for the currently active session.

---

### TD-232

**SessionList only loads on mount — filter changes don't trigger reload**

- **File**: `frontend/src/components/session/SessionList.tsx` lines 25–33
- **Category**: Bug

The `useEffect` calls `loadSessions()` with `[]` dependency array. Changing search/status/kind/sort filters does NOT trigger a reload — the session list becomes stale.

**Fix**: Add filter values to the dependency array (debounced for search).

---

### TD-233

**Agent import endpoint accepts arbitrary unvalidated JSON**

- **File**: `app/api/routers/agents.py` lines 194–208
- **Category**: Security

`import_agent` accepts `body: dict[str, Any]` — completely untyped. No validation of shape, allowing agents with arbitrary unintended state.

**Fix**: Create a proper `ImportAgentRequest` Pydantic model with validated fields.

---

### TD-243

**`skills` / `skill_resources` duplicated in migrations 0004 and 0016**

- **File**: `alembic/versions/0016_sprint14_skills.py` lines 21–59
- **Category**: Migration

Both 0004 and 0016 create these tables with `IF NOT EXISTS`. The 0016 `downgrade()` drops them, orphaning 0004's expectation that they exist.

**Fix**: 0016's `upgrade()` should only add new artifacts (index, `soul_versions` table). Remove duplicate `CREATE TABLE` statements. `downgrade()` should only drop what 0016 uniquely added.

---

## Medium Severity

### TD-213

**Static mount at "/" swallows API 404s — returns HTML instead of JSON**

- **File**: `app/api/app.py` lines 477–479
- **Category**: Bug

`app.mount("/", StaticFiles(..., html=True))` catches all non-matched routes. Any typo in an API path (e.g., `/api/typo`) returns `index.html` with HTTP 200.

**Fix**: Mount frontend under `/app`, or add a catch-all 404 for `/api/*` before the static mount.

---

### TD-214

**Partial startup leaves orphaned singletons on mid-lifespan failure**

- **File**: `app/api/app.py` lines 66–295
- **Category**: Design

If any init step after step 7 fails, earlier singletons are already initialised but shutdown never runs. A restart replaces singletons but code holding old references stays stale.

**Fix**: Wrap startup in try/except that tears down in reverse order before re-raising.

---

### TD-215

**CORS origins parsed without format validation — `*` accepted silently**

- **File**: `app/api/app.py` lines 416–424
- **Category**: Security

`TEQUILA_CORS_ORIGINS` is split on commas with no URL format validation. A value like `"http://localhost:5173, *"` allows all origins.

**Fix**: Validate each origin matches `https?://...`. Reject `*` with a warning.

---

### TD-216

**Off-by-one in `events_since` resync detection — client misses one event**

- **File**: `app/gateway/buffer.py` lines 202–210
- **Category**: Bug

When `last_seq == oldest_seq - 1`, the code doesn't flag `resync_required` but the event at `oldest_seq - 1` was already evicted. The client silently misses one event.

**Fix**: Change condition to `if last_seq < oldest_seq`.

---

### TD-217

**No `event_type` validation on `GatewayEvent` construction**

- **File**: `app/gateway/events.py` lines 82–93
- **Category**: Design

`event_type` is a plain `str` with no validator against `EVENT_TYPES`. Arbitrary event types can be created.

**Fix**: Add a Pydantic validator checking `event_type in EVENT_TYPES`.

---

### TD-218

**Untracked fire-and-forget tasks for recall prefetch and extraction**

- **File**: `app/agent/turn_loop.py` lines 401–410, 583–587
- **Category**: Bug / Observability

Tasks created for `recall.prefetch_background()` and `_run_extraction()` without storing references. Exceptions are silently lost.

**Fix**: Store task references; add a done-callback that logs exceptions.

---

### TD-219

**Exception during tool loop leaves orphaned tool messages in history**

- **File**: `app/agent/turn_loop.py` lines 313–316
- **Category**: Bug

If an exception occurs after tool-call messages are persisted but before the final response, the session history has orphaned tool messages with no closing assistant response.

**Fix**: Persist a synthetic error-marker assistant message in the exception handler.

---

### TD-220

**`ContextBudget` cache unbounded — grows for every session without eviction**

- **File**: `app/agent/context.py` lines 453–466
- **Category**: Performance

`_budgets: dict[str, ContextBudget]` grows for every session, only evicted on session archive/delete. Long-running servers accumulate budget objects.

**Fix**: Add TTL-based eviction or LRU cap. Evict on `mark_idle()`.

---

### TD-221

**`TokenCounter._cache` unbounded per-session — no LRU eviction**

- **File**: `app/agent/context.py` lines 100–120
- **Category**: Performance

Maps MD5-hashed text → token count with no eviction. Grows without bound for sessions with many unique messages.

**Fix**: Use an LRU cache with a max size.

---

### TD-222

**Synthetic assistant "Understood." messages pollute context**

- **File**: `app/agent/prompt_assembly.py` lines 160–178
- **Category**: Design

Memory and knowledge injections use fake user/assistant pairs. The fabricated "Understood." responses were never generated by the LLM, consuming context and potentially confusing models.

**Fix**: Use system messages or explicit `[injected context]` framing.

---

### TD-223

**`min_recent_messages` not fully honoured — adds 1 instead of N**

- **File**: `app/agent/prompt_assembly.py` lines 241–247
- **Category**: Bug

The break condition after exceeding budget adds only one more message regardless of how far from `min_recent_messages`.

**Fix**: Continue loop until `len(selected) >= budget.min_recent_messages` even when over budget.

---

### TD-224

**Turn queues leak for archived/idle sessions**

- **File**: `app/sessions/store.py` lines 40–52, 396–415
- **Category**: Performance

`remove_turn_queue()` called in `delete()` but NOT in `archive()` or `mark_idle()`. Empty `asyncio.Queue` objects accumulate.

**Fix**: Call `remove_turn_queue(session_id)` in `archive()` and `mark_idle()`.

---

### TD-225

**`get_active_chain` silently truncates at 1000 messages**

- **File**: `app/sessions/messages.py` line 178
- **Category**: Bug

Calls `list_by_session(..., limit=1000)`. Sessions exceeding this threshold get truncated without warning.

**Fix**: Warn when limit is reached, or paginate through all results.

---

### TD-226

**`deactivate_from` timestamp ordering fragile under fast inserts**

- **File**: `app/sessions/messages.py` lines 199–224
- **Category**: Bug

Uses `created_at >= pivot_ts`. Two messages with identical ms-timestamps can cause wrong deactivation.

**Fix**: Use ROWID or monotonic sequence number for ordering.

---

### TD-227

**`execute_script` splits on `;` inside string literals**

- **File**: `app/db/schema.py` lines 39–44
- **Category**: Bug

Naively splits SQL on `;`. A string literal containing `;` produces invalid SQL fragments.

**Fix**: Use `aiosqlite.executescript()` or a proper SQL parser.

---

### TD-228

**LLM-supplied `**arguments` passed directly to tool functions unsanitised**

- **File**: `app/tools/executor.py` lines 367–378
- **Category**: Security

`await fn(**arguments)` spreads LLM-provided arguments as kwargs. If a tool accepts `**kwargs`, arbitrary key-value pairs pass through.

**Fix**: Filter `arguments` to only include keys present in `td.parameters["properties"]`.

---

### TD-231

**Global WS event buffer leaks events across sessions**

- **File**: `app/api/ws.py` line 43
- **Category**: Bug

`WS_EVENT_BUFFER` is a module-level singleton shared across all WebSocket connections. Events from Session A can be replayed to Session B on reconnect.

**Fix**: Use per-session or per-connection event buffers.

---

### TD-234

**`system.py` missing `logger` import — `NameError` at runtime**

- **File**: `app/api/routers/system.py` line 255
- **Category**: Bug

`logger.warning()` is called but `logging`/`logger` is never imported. Will crash when the provider registry fails during `/api/status`.

**Fix**: Add `import logging` and `logger = logging.getLogger(__name__)`.

---

### TD-235

**Nested `write_transaction` causes deadlock (non-reentrant lock)**

- **File**: `app/db/connection.py` lines 107–125
- **Category**: Concurrency

`asyncio.Lock` is not re-entrant. Code inside a `write_transaction` that calls another `write_transaction` will deadlock.

**Fix**: Use a re-entrant lock, or restructure to avoid nesting.

---

### TD-236

**`_is_turn_active` ignores `agent_id`, uses global check**

- **File**: `app/scheduler/engine.py` lines 216–221
- **Category**: Bug

Checks `active_turn_count() > 0` globally even though it receives `agent_id`. If ANY session has an active turn, ALL scheduled tasks are deferred with unnecessary 60s delays.

**Fix**: Filter by matching sessions' `agent_id`.

---

### TD-237

**No timezone consistency in scheduler `next_run` computation**

- **File**: `app/scheduler/engine.py` lines 133–141
- **Category**: Bug

`next_run_at` may be naive datetime; the patching assumes UTC. If cron expressions intend local time, schedules fire at the wrong time.

**Fix**: Enforce timezone-aware datetimes throughout. Store and compare in UTC.

---

### TD-238

**`_build_json_schema` doesn't handle Optional/Union/complex types**

- **File**: `app/tools/registry.py` lines 152–180
- **Category**: Bug

Only handles `str`, `int`, `float`, `bool`, `list[str]`. Parameters typed as `Optional[str]`, `dict[str, Any]`, etc. default to `{"type": "string"}`: LLM sends wrong types.

**Fix**: Handle `Optional` (Union with NoneType), `dict`, and other types.

---

### TD-239

**Anthropic usage events split across two stream events**

- **File**: `app/providers/anthropic.py` lines 240–256
- **Category**: Design

Input tokens in `RawMessageStartEvent`, output tokens in `RawMessageDeltaEvent`. Consumers that replace (not merge) usage events lose input token counts.

**Fix**: Accumulate and emit a single combined `usage` event.

---

### TD-240

**`GracefulDegradation` records success before stream consumption**

- **File**: `app/providers/circuit_breaker.py` lines 303–305
- **Category**: Bug

`await cb.record_success()` called immediately after obtaining the stream iterator. If the stream fails mid-way, the circuit breaker already recorded "success".

**Fix**: Record success only after the stream's `done` event.

---

### TD-241

**`decrypt_credential` catches overly broad Exception**

- **File**: `app/auth/encryption.py` lines 63–67
- **Category**: Error Handling

`except (InvalidToken, Exception)` swallows all errors including `TypeError`, `NameError`, etc., re-raising generic `ValueError`. Masks real bugs.

**Fix**: Catch only `InvalidToken` and known decoding errors.

---

### TD-242

**LIKE-injection in memory/vault search — `%` and `_` not escaped**

- **File**: `app/memory/store.py` line 177 / `app/knowledge/vault.py` lines 309–310
- **Category**: Bug

`f"%{search}%"` passes raw search into LIKE. The `%` and `_` chars act as wildcards, breaking exact-substring behaviour.

**Fix**: Escape `%` and `_` in user input; add `ESCAPE '\\'` to LIKE clause.

---

### TD-244

**`audit_log` schema conflict between migrations 0001 and 0007**

- **File**: `alembic/versions/0007_sprint07_audit_log.py` lines 29–42, 48–50
- **Category**: Migration

0007's `downgrade()` runs `DROP TABLE IF EXISTS audit_log`, destroying the table 0001 created. Downgrading to 0006 and re-upgrading leaves `audit_log` missing.

**Fix**: Remove `DROP TABLE` from 0007 downgrade; only drop the indexes 0007 added.

---

### TD-245

**0005 downgrade is `pass` — 16 columns can't be rolled back**

- **File**: `alembic/versions/0005_sprint05_messages_full.py` line 57
- **Category**: Migration

Downgrading from 0005 leaves 16 extra columns that pre-0005 code doesn't expect.

**Fix**: Use `batch_alter_table` to recreate `messages` with original columns.

---

### TD-246

**0004 downgrade destroys 0003's index + CHECK constraint on agents**

- **File**: `alembic/versions/0004_sprint04_agent_full.py` lines 83–92
- **Category**: Migration

Downgrade recreates `agents` via backup/drop/rename, destroying `idx_agents_status` and CHECK constraint from 0003.

**Fix**: Recreate the index after the table rename in downgrade.

---

### TD-247

**10 FK-like columns lack REFERENCES constraints**

- **Files**: Multiple migrations (0009, 0011, 0014, 0015, 0016, 0017)
- **Category**: Schema

`plugin_credentials.plugin_id`, `webhook_endpoints.plugin_id`, `turn_costs.session_id`, `turn_costs.agent_id`, `scheduled_tasks.agent_id`, `soul_versions.agent_id`, `memory_extracts.agent_id`, `memory_extracts.source_session_id`, `memory_events.memory_id`, `memory_events.entity_id` all lack REFERENCES constraints.

**Fix**: Add constraints in a new migration.

---

### TD-248

**ExportMenu dropdown never closes on outside click**

- **File**: `frontend/src/components/chat/ChatPanel.tsx` lines 9–65
- **Category**: UX

The dropdown only closes on format selection or button toggle.

**Fix**: Add `useEffect` with `document.addEventListener('click', ...)`.

---

### TD-249

**Navigation divs lack keyboard Enter/Space handling**

- **File**: `frontend/src/components/layout/AppLayout.tsx` lines 80–115
- **Category**: Accessibility

`<div role="button" tabIndex={0}>` items have no `onKeyDown` handler. Keyboard-only users can focus but not activate them.

**Fix**: Add `onKeyDown` for Enter/Space, or use `<Link>` elements.

---

### TD-250

**Sidebar nav uses divs instead of semantic `<nav>`/`<Link>` elements**

- **File**: `frontend/src/components/layout/AppLayout.tsx` lines 78–115
- **Category**: Accessibility

Screen readers won't announce divs as links; users can't middle-click to open in new tab. No `<nav>` landmark.

**Fix**: Replace with React Router `<Link>`, wrap in `<nav aria-label="Main navigation">`.

---

### TD-251

**MessageList auto-scroll fires on every streaming delta — causes jank**

- **File**: `frontend/src/components/chat/MessageList.tsx` lines 189–191
- **Category**: Performance

`useEffect` depends on `[messages, streamingContent]`. During streaming, `scrollIntoView` fires many times/second, causing jank and preventing user from scrolling up.

**Fix**: Debounce auto-scroll; only scroll if user was already at bottom.

---

### TD-252

**`send()` silently drops messages when WebSocket is not OPEN**

- **File**: `frontend/src/api/ws.ts` lines 66–69
- **Category**: Bug

Returns silently when WS not open. Messages during reconnect are permanently lost with no feedback.

**Fix**: Queue messages and flush on reconnect, or throw so caller shows feedback.

---

### TD-253

**`App.tsx` treats setup-status fetch failure as "app ready"**

- **File**: `frontend/src/App.tsx` lines 213–216
- **Category**: Bug

If `/api/setup/status` fails (server down), catch block sets `mode = 'app'`, showing broken UI instead of "server unreachable" error.

**Fix**: Show a connection error state with retry button.

---

### TD-254

**`chatStore.ts` WS payload cast without runtime validation**

- **File**: `frontend/src/stores/chatStore.ts` line ~256
- **Category**: Bug

WS payload blindly cast via `as unknown as Message` with no runtime validation. Malformed payloads create objects with missing fields.

**Fix**: Add runtime validation (type guard or Zod schema).

---

### TD-255

**No error feedback to user on `agent.run.error` WS event**

- **File**: `frontend/src/stores/chatStore.ts` lines ~283–285
- **Category**: UX

On error event, streaming stops but no error message is shown. User sees response just stop.

**Fix**: Store error message and display as system message or error banner.

---

### TD-256

**`graph.py` orphans endpoint — bare `except Exception: pass` hides errors**

- **File**: `app/api/routers/graph.py` lines 130–142
- **Category**: Observability

Both SQL blocks catch `Exception` with `pass`. SQL failures return empty list with no indication of error.

**Fix**: Log the exception, or include an `"error"` field.

---

### TD-257

**`save_plugin_credential` writes via read-only DB connection dep**

- **File**: `app/plugins/api.py` lines 282–289
- **Category**: Bug

Uses `Depends(get_db_dep)` (read-only) for a write operation. Bypasses write lock, risking SQLite locking errors.

**Fix**: Use `Depends(get_write_db_dep)`.

---

### TD-258

**`skills.py` skill update has no OCC — concurrent updates silently overwrite**

- **File**: `app/api/routers/skills.py` lines 191–197
- **Category**: Concurrency

No `version` field in `SkillUpdateRequest`. Concurrent updates are last-writer-wins. The agent API correctly uses OCC.

**Fix**: Add `version: int` field and check it in the store.

---

## Low Severity

### TD-259

**ExportMenu/BackupPage bypass `api` client — duplicate auth logic**

- **File**: `frontend/src/components/chat/ChatPanel.tsx` line 17, `frontend/src/pages/BackupPage.tsx` lines 64–77

Both use raw `fetch()` with manual token handling instead of the shared `api` client.

**Fix**: Extract shared `getAuthHeaders()` helper or add `rawFetch` to api client.

---

### TD-260

**`alert()` used for error reporting in ExportMenu**

- **File**: `frontend/src/components/chat/ChatPanel.tsx` line 30

Blocks UI thread. Other pages use inline error state.

**Fix**: Use toast notification or inline error banner.

---

### TD-261

**O(n²) trim strategy in `compress_trim_oldest`**

- **File**: `app/agent/context.py` lines 280–300

`list.pop(0)` inside a loop is O(n) per pop, O(n²) total for long conversations.

**Fix**: Use `deque` or track an index and slice.

---

### TD-262

**Missing cancellation/timeout event types in gateway events**

- **File**: `app/gateway/events.py` lines 100–204

No `AGENT_RUN_CANCELLED` or `AGENT_RUN_TIMEOUT`. All failures funnel through `AGENT_RUN_ERROR`.

**Fix**: Add distinct event types for cancellation and timeout.

---

### TD-263

**Ollama first tool call chunk may drop arguments**

- **File**: `app/providers/ollama.py` lines 148–165

First SSE chunk creates buffer with `args_raw=""`, ignoring any arguments in that chunk.

**Fix**: Check for and accumulate arguments in the first chunk.

---

### TD-264

**`ProviderRegistry.global_registry()` not thread-safe (unused lock)**

- **File**: `app/providers/registry.py` lines 47–51

Singleton check-then-create without lock protection. The defined `_lock` is never used.

**Fix**: Use threading lock for creation, or document single-thread assumption.

---

### TD-265

**Fernet tokens have no TTL — leaked tokens valid forever**

- **File**: `app/auth/encryption.py` lines 56–60

`get_fernet().decrypt(token.encode())` without `ttl`. Exfiltrated tokens remain valid indefinitely.

**Fix**: Add configurable TTL or document the no-expiry decision.

---

### TD-266

**Ollama `httpx.AsyncClient` resource leak on GC**

- **File**: `app/providers/ollama.py` line 84

Client created in `__init__` with no `__aenter__`/`__aexit__`. GC without explicit `close()` leaks connections.

**Fix**: Implement `__aenter__`/`__aexit__` or `__del__` guard.

---

### TD-267

**OpenAI token counting underestimates real usage**

- **File**: `app/providers/openai.py` lines 232–247

`total += 4` per-message overhead doesn't account for role, name, or conversation tokens. Budget calculations under-report.

**Fix**: Use model-specific `tiktoken` encoding or add safety margin.

---

### TD-268

**Embeddings `_load_vectors` duplicates data across cache keys**

- **File**: `app/knowledge/embeddings.py` lines 229–260

Searching with `source_types=None` and then `["memory"]` caches the same vectors under different keys.

**Fix**: Use canonical cache structure; always load all types and subset.

---

### TD-269

**Missing indexes on `sessions.parent_session_key`, `notifications.source_session_key`**

- **Files**: `alembic/versions/0001_baseline.py` line 48, `0017_sprint14b.py` line 35

No indexes on columns that may be filtered on. Full table scans for child-session or per-session notification lookups.

**Fix**: Add indexes in a new migration.

---

## Severity Distribution

| Severity | Count |
|----------|-------|
| **Critical** | 8 |
| **High** | 12 |
| **Medium** | 27 |
| **Low** | 11 |
| **Total** | **58** |

*Note: Some issues identified in the subaudits were deduplicated against the existing TD-138–192 list, reducing from 77 raw findings to 58 net-new unique TDs.*

---

## Combined Tech Debt Inventory

Including the original S12–14b audit (TD-138–192), the **total tech debt backlog** is:

| Batch | Range | Critical | High | Medium | Low | Total |
|-------|-------|----------|------|--------|-----|-------|
| S01–07 audit | TD-01–42 | ✅ resolved | | | | 42 |
| S08–11 audit | TD-43–137 | ✅ resolved | | | | 95 |
| S12–14b surface | TD-138–192 | 4 | 8 | 18 | 25 | 55 |
| Deep dive addendum | TD-193–269 | 8 | 12 | 27 | 11 | 58 |
| **Open total** | | **12** | **20** | **45** | **36** | **113** |

---

## Top 10 Most Impactful Issues (Combined)

1. **TD-193** — Scheduler→TurnLoop payload mismatch: all cron jobs silently broken
2. **TD-195** — `regenerate()` picks wrong user message: branching corrupts conversations
3. **TD-199+200** — Semantic recall and extraction dedup both fully disabled by attribute mismatches
4. **TD-196+197** — Circuit breaker destroys streaming; graceful degradation crashes
5. **TD-194** — Fernet key in plaintext SQLite: all encrypted credentials recoverable
6. **TD-138** — MCP stdio command injection: arbitrary host RCE
7. **TD-202+203** — Prompt assembly double-count + negative history budget: broken context windows
8. **TD-211** — Duplicate scheduler task execution from overlapping ticks
9. **TD-201** — No concurrent turn guard: parallel turns corrupt session state
10. **TD-140** — HookPoint literals mismatch: all plugin hooks silently broken

---

## Recommended Cleanup Phases

### Phase 1 — Silent Feature Failures (8 items)
TD-193, 195, 196, 197, 198, 199, 200, 212 — Fix these first because multiple core features are completely non-functional but silently appear to work.

### Phase 2 — Security Critical (8 items)
TD-138, 139, 194, 208, 229, 233, 142, 143 — RCE, SSTI, credential exposure, role injection, unvalidated imports.

### Phase 3 — Data Integrity & Correctness (12 items)
TD-140, 141, 195, 202, 203, 206, 207, 211, 146, 161, 162, 164 — Broken features, data corruption, incorrect results.

### Phase 4 — Concurrency & Reliability (8 items)
TD-201, 204, 205, 210, 230, 235, 258, 159 — Race conditions, deadlocks, unreferenced tasks.

### Phase 5 — Performance (10 items)
TD-148, 160, 165, 166, 167, 170, 220, 221, 224, 251 — Blocking I/O, memory leaks, query inefficiency.

### Phase 6 — Frontend & API Quality (15 items)
TD-213, 232, 248–250, 252–255, 168, 188, 234, 244–246 — UX, accessibility, API consistency, migrations.

### Phase 7 — Hardening & Polish (remaining)
All Low-severity items and remaining Medium items.
