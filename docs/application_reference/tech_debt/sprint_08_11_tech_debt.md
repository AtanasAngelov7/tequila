# Tech Debt Audit — Sprints 08–11

**Audited**: Sprints 08 through 11 (Memory I–III, Multi-Agent)
**Test baseline at audit time**: 683 passing, 1 pre-existing failure (`test_list_providers`)
**Audit scope**: Backend source code, API security, concurrency, error handling, performance, type safety
**Previous audits**: TD-01 through TD-42 (Sprints 01–07, two passes)

---

## Executive Summary

**122 issues** identified across 4 sprints. The most urgent cluster is **security** — 4 Critical items in Sprint 10's knowledge source adapters (SQL injection, SSRF, path traversal, missing auth) that together form an attack chain allowing arbitrary SQL execution, internal network scanning, and filesystem reads from an unauthenticated API.

The second cluster is **correctness bugs** — broken feedback weighting in extraction, substring-based dedup in recall, a `session_key` vs `session_id` mixup that makes all workflow steps silently return empty results, and offset-based pagination that skips items during mutation passes.

The third cluster is **performance** — blocking synchronous I/O in async contexts (vault file ops, embedding model inference, ChromaDB/FAISS calls) and N+1 query patterns (entity alias resolution, graph rebuild).

| Severity | Count | Description |
|----------|-------|-------------|
| **Critical** | 7 | Security holes (SQLi, SSRF, path traversal, missing auth), data-losing bugs |
| **High** | 16 | Correctness bugs, concurrency races, data integrity risks, performance bottlenecks |
| **Medium** | 33 | Validation gaps, silent error swallowing, design problems, missing observability |
| **Low** | 19 | Code quality, dead code, minor performance, type annotations |
| **Total** | **75** | |

---

## Quick Reference

| ID | Title | Sev | Sprint | Category |
|----|-------|-----|--------|----------|
| [TD-43](#td-43) | SQL injection in pgvector adapter via user-supplied identifiers | **Crit** | S10 | Security |
| [TD-44](#td-44) | SSRF vulnerability in HTTP knowledge source adapter | **Crit** | S10 | Security |
| [TD-45](#td-45) | Path traversal in FAISS adapter — arbitrary filesystem reads | **Crit** | S10 | Security |
| [TD-46](#td-46) | Knowledge source API endpoints completely unauthenticated | **Crit** | S10 | Security |
| [TD-47](#td-47) | `_run_step` passes `session_key` where `session_id` (UUID) is expected | **Crit** | S08 | Bug |
| [TD-48](#td-48) | Workflow cancellation is a no-op — background task ignores cancelled status | **Crit** | S08 | Design |
| [TD-49](#td-49) | `entity_merge` silently loses aliases and memory links on failure | **Crit** | S11 | Data Integrity |
| [TD-50](#td-50) | Feedback weighting in extraction pipeline is completely broken | **High** | S10 | Bug |
| [TD-51](#td-51) | Confidence adjustment applies all message boosts to every candidate | **High** | S10 | Bug |
| [TD-52](#td-52) | Recall `_dedup_against_always` uses substring containment — false positives | **High** | S10 | Bug |
| [TD-53](#td-53) | `kb_list_sources` accesses `src.id` — AttributeError at runtime | **High** | S10 | Bug |
| [TD-54](#td-54) | FAISS score interpretation inverted for L2 indexes | **High** | S10 | Bug |
| [TD-55](#td-55) | Knowledge source `connection` config has no schema validation | **High** | S10 | Security |
| [TD-56](#td-56) | Knowledge source `backend` field not validated in API | **High** | S10 | Validation |
| [TD-57](#td-57) | Health-check background task in KnowledgeSourceRegistry never started | **High** | S10 | Dead Code |
| [TD-58](#td-58) | TOCTOU race in sub-agent concurrency check | **High** | S08 | Concurrency |
| [TD-59](#td-59) | `update_run_status` read-then-write has no OCC — concurrent updates lose data | **High** | S08 | Concurrency |
| [TD-60](#td-60) | Blocking sync I/O in vault async methods (file reads/writes) | **High** | S09 | Performance |
| [TD-61](#td-61) | `LocalEmbeddingProvider.embed()` runs CPU-bound inference on event loop | **High** | S09 | Performance |
| [TD-62](#td-62) | `MemoryStore.get()` has side effect — bumps access_count on every call | **High** | S09 | Design |
| [TD-63](#td-63) | `unlink_entity` doesn't update the `entity_ids` JSON column — stale data | **High** | S09 | Data Integrity |
| [TD-64](#td-64) | `EntityStore.resolve()` does a full table scan for alias matching | **High** | S09 | Performance |
| [TD-65](#td-65) | Offset pagination bug in lifecycle mutation passes — items skipped | **High** | S11 | Correctness |

---

## Critical Severity

### TD-43

**SQL injection in pgvector adapter via user-supplied identifiers**

- **File**: `app/knowledge/sources/adapters/pgvector.py` lines 60–82, 103–104
- **Sprint**: S10
- **Category**: Security

`table`, `content_col`, `emb_col`, and `meta_cols` come from `source.connection`, a user-supplied JSON dict. These are interpolated directly into SQL via f-strings:

```python
f"SELECT {content_col}{meta_clause}, 1 - ({emb_col} <=> $1::vector) AS score FROM {table} ..."
```

Combined with the unauthenticated API (TD-46), this allows SQL injection from the network.

**Fix**: Validate identifiers against `^[a-zA-Z_][a-zA-Z0-9_]*$` regex, or use `asyncpg` identifier quoting.

---

### TD-44

**SSRF vulnerability in HTTP knowledge source adapter**

- **File**: `app/knowledge/sources/adapters/http.py` lines 38–62
- **Sprint**: S10
- **Category**: Security

The URL is taken verbatim from user-supplied `connection` config:

```python
resp = await client.post(url, json=payload, headers=headers)
```

An attacker can register a source pointing to `http://169.254.169.254/latest/meta-data/`, internal services, or `file://` URIs.

**Fix**: Validate URL scheme (https only in prod), block private/link-local IP ranges.

---

### TD-45

**Path traversal in FAISS adapter — arbitrary filesystem reads**

- **File**: `app/knowledge/sources/adapters/faiss.py` lines 41–47
- **Sprint**: S10
- **Category**: Security

```python
index_path = Path(cfg.get("index_path", "data/faiss/index.faiss"))
self._index = faiss.read_index(str(index_path))
```

User-supplied paths allow reading arbitrary files (e.g., `../../etc/passwd` or loading a crafted FAISS index).

**Fix**: Resolve paths and verify they're within the expected data directory.

---

### TD-46

**Knowledge source API endpoints completely unauthenticated**

- **File**: `app/api/routers/knowledge_sources.py` (all endpoints)
- **Sprint**: S10
- **Category**: Security

All 14 endpoints (register, delete, activate, search, test, stats) have zero auth. Combined with TD-43/44/45, this creates a complete attack chain from the network.

**Fix**: Add `dependencies=[Depends(require_gateway_token)]` to the router.

---

### TD-47

**`_run_step` passes `session_key` where `session_id` (UUID) is expected**

- **File**: `app/workflows/runtime.py` line 104
- **Sprint**: S08
- **Category**: Bug

```python
messages = await msg_store.list_by_session(sub_key, limit=50, active_only=True)
```

`sub_key` is a session_key string like `"agent:bot:sub:abc12345"`, but `list_by_session` expects a UUID `session_id`. Every workflow step silently returns empty results.

**Fix**: Resolve `sub_key` to `session_id` via `session_store.get_by_key(sub_key)` before the call.

---

### TD-48

**Workflow cancellation is a no-op — background task ignores cancelled status**

- **File**: `app/workflows/api.py` lines 158–174, 190
- **Sprint**: S08
- **Category**: Design

`cancel_run` sets `status="cancelled"` in the DB, but the `_execute()` background task never checks run status. It runs to completion, potentially overwriting the cancelled status.

**Fix**: Pass a cancellation token (`asyncio.Event`) checked by the pipeline/parallel loops between steps.

---

### TD-49

**`entity_merge` silently loses aliases and memory links on failure**

- **File**: `app/tools/builtin/memory.py` lines 579–598
- **Sprint**: S11
- **Category**: Data Integrity

During entity merge, both alias transfer and memory re-linking silently swallow all exceptions:

```python
for alias in (source.aliases or []):
    try:
        await store.add_alias(target_entity_id, alias)
    except Exception:
        pass  # ← alias silently lost
```

If `link_entity` succeeds but `unlink_entity` fails, memory points to both entities. If both fail, memory loses its entity link after source is soft-deleted.

**Fix**: Collect failures, log at WARNING, include partial-failure info in response.

---

## High Severity

### TD-50

**Feedback weighting in extraction pipeline is completely broken**

- **File**: `app/memory/extraction.py` lines 189–196
- **Sprint**: S10
- **Category**: Bug

```python
for msg in weighted:
    if rating == "up":
        msg = dict(msg, _confidence_boost=0.2)  # ← rebinds local var only
```

`msg = dict(msg, ...)` creates a new dict but doesn't update the list. Feedback ratings are completely ignored.

**Fix**: Use index-based mutation: `weighted[i] = dict(msg, _confidence_boost=0.2)`.

---

### TD-51

**Confidence adjustment applies all message boosts to every candidate**

- **File**: `app/memory/extraction.py` lines 215–224
- **Sprint**: S10
- **Category**: Bug / Design

Boosts are summed from **all** relevant messages and applied identically to **every** candidate. 3 upvoted messages → every candidate gets +0.6.

**Fix**: Track which messages generated each candidate; apply per-message adjustments.

---

### TD-52

**Recall `_dedup_against_always` uses substring containment — false positives**

- **File**: `app/memory/recall.py` lines 368–370
- **Sprint**: S10
- **Category**: Bug

```python
return [c for c in candidates if c.get("content", "") not in always_content]
```

Python `in` on strings checks **substring** containment. `"art" in "...start..."` is `True`.

**Fix**: Compare against a set of exact content strings.

---

### TD-53

**`kb_list_sources` accesses `src.id` — AttributeError at runtime**

- **File**: `app/tools/builtin/knowledge.py` line 119
- **Sprint**: S10
- **Category**: Bug

`KnowledgeSource` model uses `source_id`, not `id`. This raises `AttributeError` at runtime.

**Fix**: Change `src.id` to `src.source_id`.

---

### TD-54

**FAISS score interpretation inverted for L2 indexes**

- **File**: `app/knowledge/sources/adapters/faiss.py` lines 67–69
- **Sprint**: S10
- **Category**: Bug

L2 distance = dissimilarity (lower = more similar). No conversion is applied, so the most irrelevant results get the highest scores.

**Fix**: Detect index type and apply `1 / (1 + dist)` for L2.

---

### TD-55

**Knowledge source `connection` config has no schema validation**

- **File**: `app/api/routers/knowledge_sources.py` line 42, `app/knowledge/sources/models.py` line 40
- **Sprint**: S10
- **Category**: Security / Validation

`connection: dict[str, Any]` is stored as-is and later used to construct SQL, file paths, and URLs.

**Fix**: Define per-backend connection schemas and validate on registration.

---

### TD-56

**Knowledge source `backend` field not validated in API**

- **File**: `app/api/routers/knowledge_sources.py` line 42
- **Sprint**: S10
- **Category**: Validation

Any string accepted; invalid records persist in DB and fail at activation time.

**Fix**: Use `Literal["chroma", "pgvector", "faiss", "http"]`.

---

### TD-57

**Health-check background task in KnowledgeSourceRegistry never started**

- **File**: `app/knowledge/sources/registry.py` lines 68–77
- **Sprint**: S10
- **Category**: Dead Code

`health_check_interval_s = 300` is defined but `start()` never creates the background task. Automatic health monitoring is completely non-functional.

**Fix**: Implement `self._health_task = asyncio.create_task(self._health_loop())` in `start()`.

---

### TD-58

**TOCTOU race in sub-agent concurrency check**

- **File**: `app/agent/sub_agent.py` lines 96–117
- **Sprint**: S08
- **Category**: Concurrency

Between the count check and `_register()`, there are multiple `await` points. Two concurrent spawns can both pass the check.

**Fix**: Use an `asyncio.Lock` per parent to make check-and-register atomic.

---

### TD-59

**`update_run_status` read-then-write has no OCC**

- **File**: `app/workflows/store.py` lines 175–211
- **Sprint**: S08
- **Category**: Concurrency

Cancel status can be silently overwritten by the pipeline setting `status="running"`.

**Fix**: Add `WHERE status != 'cancelled'` guard to the UPDATE, or add a `version` column.

---

### TD-60

**Blocking sync I/O in vault async methods**

- **Files**: `app/knowledge/vault.py` lines 199, 234, 247, 317, 350 (throughout)
- **Sprint**: S09
- **Category**: Performance

All `path.read_text()`, `path.write_text()`, `path.exists()`, `path.unlink()` calls block the asyncio event loop.

**Fix**: Use `asyncio.to_thread()` or `aiofiles`.

---

### TD-61

**`LocalEmbeddingProvider.embed()` runs CPU-bound inference on event loop**

- **File**: `app/knowledge/embeddings.py` lines 88–92
- **Sprint**: S09
- **Category**: Performance

`model.encode()` can take seconds, stalling all concurrent requests.

**Fix**: Wrap in `await asyncio.to_thread(model.encode, texts, ...)`.

---

### TD-62

**`MemoryStore.get()` has side effect — bumps `access_count` on every call**

- **File**: `app/memory/store.py` lines 102–115
- **Sprint**: S09
- **Category**: Design

Internal operations (`update()`, `delete()`, `soft_delete()`, `link_entity()`) all call `get()`, polluting access-count metrics. OCC retry loops amplify this.

**Fix**: Split into read-only `get()` and side-effecting `get_and_touch()`.

---

### TD-63

**`unlink_entity` doesn't update the `entity_ids` JSON column**

- **File**: `app/memory/store.py` lines 204–210
- **Sprint**: S09
- **Category**: Data Integrity

`link_entity()` updates both the link table and the JSON column. `unlink_entity()` only removes from the link table, leaving stale IDs in JSON.

**Fix**: Also remove the entity_id from the memory's `entity_ids` JSON array.

---

### TD-64

**`EntityStore.resolve()` does a full table scan for alias matching**

- **File**: `app/memory/entity_store.py` lines 111–121
- **Sprint**: S09
- **Category**: Performance

Loads ALL active entities into memory, iterates every alias of every entity. 10K entities with 3 aliases = 30K comparisons per resolve call. `extract_and_link` calls this per mention.

**Fix**: Use SQLite `json_each()`: `SELECT * FROM entities, json_each(entities.aliases) WHERE json_each.value = ? COLLATE NOCASE AND status = 'active'`.

---

### TD-65

**Offset pagination bug in lifecycle mutation passes — items skipped**

- **File**: `app/memory/lifecycle.py` lines 198–235, 237–275, 301–397
- **Sprint**: S11
- **Category**: Correctness

`run_archive`, `run_expire_tasks`, and `run_merge` paginate with `offset += batch` while mutating items (archived/deleted). Items shift in the result set — next page skips them.

**Fix**: Use cursor-based pagination (`WHERE id > last_seen_id`) or collect IDs first.

---

## Medium Severity

### TD-66

**Session tools have no authorization — any agent can read/write any session**

- **File**: `app/tools/builtin/sessions.py` lines 68–170
- **Sprint**: S08
- **Category**: Security

`sessions_list`, `sessions_history`, `sessions_send` perform no access control. The `SessionPolicy` defines `can_send_inter_session`, but none of these tools check it.

**Fix**: Check the calling agent's session policy before allowing cross-session operations.

---

### TD-67

**`sessions_history` returns `[]` for non-existent sessions — indistinguishable from empty**

- **File**: `app/tools/builtin/sessions.py` lines 114–116
- **Sprint**: S08
- **Category**: Validation

**Fix**: Return an error response when the session doesn't exist.

---

### TD-68

**Race between `AGENT_RUN_COMPLETE` event and message persistence**

- **File**: `app/tools/builtin/sessions.py` lines 190–204, `app/workflows/runtime.py` lines 93–104
- **Sprint**: S08
- **Category**: Concurrency

The event may fire before the message store commits. The immediate read can return stale data.

**Fix**: Include reply content in the event payload, or add a short retry.

---

### TD-69

**`sessions_spawn` doesn't catch `ValueError` from bad policy preset**

- **File**: `app/tools/builtin/sessions.py` lines 237–241
- **Sprint**: S08
- **Category**: Code Quality

Only `RuntimeError` is caught. `ValueError` from `SessionPolicyPresets.by_name()` propagates unhandled.

**Fix**: Catch `(RuntimeError, ValueError)`.

---

### TD-70

**`_active` dict memory leak when `auto_archive_minutes=0`**

- **File**: `app/agent/sub_agent.py` lines 138–144
- **Sprint**: S08
- **Category**: Memory Leak

`_unregister()` is only called inside `_auto_archive`. When `auto_archive_minutes=0`, entries stay in `_active` forever.

**Fix**: Add explicit cleanup, or call `_unregister` after the agent run completes.

---

### TD-71

**Nested silent error swallowing in workflow `_execute`**

- **File**: `app/workflows/api.py` lines 167–172, 211
- **Sprint**: S08
- **Category**: Code Quality

If DB update to "failed" status itself fails, `except Exception: pass` leaves the run stuck in "running" forever.

**Fix**: Add `logger.exception(...)`. Consider a background reaper for stale runs.

---

### TD-72

**`list_workflows`/`list_runs` `total` field is page count, not DB total**

- **File**: `app/workflows/api.py` lines 123, 183
- **Sprint**: S08
- **Category**: API Design

**Fix**: Issue `SELECT COUNT(*)` for the real total, or rename the field.

---

### TD-73

**No `agent_id` existence validation in spawn or workflow steps**

- **File**: `app/agent/sub_agent.py` line 67, `app/workflows/api.py` line 89
- **Sprint**: S08
- **Category**: Validation

A typo in `agent_id` creates a session that fails at turn-loop time with an opaque error.

**Fix**: Validate `agent_id` at spawn/creation time.

---

### TD-74

**`sessions_send` bare `except Exception` catches too broadly**

- **File**: `app/tools/builtin/sessions.py` lines 205–207
- **Sprint**: S08
- **Category**: Code Quality

Returns `"completed"` status even when reply reading fails. Caller can't detect the failure.

**Fix**: Narrow catch, or return `{"status": "error"}`.

---

### TD-75

**`sync_from_disk` opens a separate write transaction per file**

- **File**: `app/knowledge/vault.py` lines 437–470
- **Sprint**: S09
- **Category**: Performance

100 changed files → 100 separate transactions.

**Fix**: Batch all changes into a single transaction.

---

### TD-76

**`update_note` doesn't rename file when title changes**

- **File**: `app/knowledge/vault.py` lines 322–368
- **Sprint**: S09
- **Category**: Design

Filenames diverge from titles over time. Document as intentional or implement rename.

---

### TD-77

**`delete_note` removes disk file after DB delete — inconsistent cleanup order**

- **File**: `app/knowledge/vault.py` lines 370–373
- **Sprint**: S09
- **Category**: Reliability

If process crashes between DB delete and `unlink()`, orphan file remains and `sync_from_disk` resurrects it.

**Fix**: Delete file first, or undo DB delete on file-delete failure.

---

### TD-78

**Embedding `_load_vectors` caching inconsistent for filtered queries**

- **File**: `app/knowledge/embeddings.py` lines 198–221
- **Sprint**: S09
- **Category**: Performance

Filtered queries bypass cache but never cache their results. Unfiltered `_invalidate()` clears everything.

---

### TD-79

**Reindex treats batch failure as 100% failure**

- **File**: `app/knowledge/embeddings.py` lines 405–410
- **Sprint**: S09
- **Category**: Code Quality

No partial progress reported.

---

### TD-80

**`MemoryCreateRequest` doesn't validate enum-like fields**

- **File**: `app/api/routers/memory.py` lines 41–56
- **Sprint**: S09
- **Category**: Validation

`memory_type`, `source_type`, `scope`, `status` are plain `str` — invalid values pass API validation.

**Fix**: Use the Literal types from `app.memory.models`.

---

### TD-81

**`expires_at` silently ignores invalid date strings**

- **File**: `app/api/routers/memory.py` lines 99–106
- **Sprint**: S09
- **Category**: Validation

`except ValueError: pass` — user thinks they set an expiration but didn't.

**Fix**: Raise `HTTPException(400)`.

---

### TD-82

**Audit endpoints silently return `[]` when module not initialized**

- **File**: `app/api/routers/memory.py` lines 168–173, 190–196
- **Sprint**: S11
- **Category**: Observability

Client can't distinguish "no events" from "audit system unavailable".

**Fix**: Return HTTP 503.

---

### TD-83

**`EntityStore.update()` has no optimistic concurrency control**

- **File**: `app/memory/entity_store.py` lines 133–158
- **Sprint**: S09
- **Category**: Concurrency

Plain read-then-write — last-writer-wins.

**Fix**: Add a `version` column and OCC pattern.

---

### TD-84

**`extract_entity_mentions` has high false-positive rate**

- **File**: `app/memory/entities.py` lines 136–180
- **Sprint**: S09
- **Category**: Code Quality

Regex-based NER matches any capitalized word after sentence boundary.

**Fix**: Expand stopword list, add confidence score.

---

### TD-85

**No CHECK constraints on enum-like TEXT columns in migration 0009**

- **File**: `alembic/versions/0009_sprint09_memory_entities.py` lines 23–143
- **Sprint**: S09
- **Category**: Data Integrity

`memory_type`, `source_type`, `scope`, `status`, `entity_type` — all plain TEXT.

---

### TD-86

**ChromaDB calls block event loop**

- **File**: `app/knowledge/sources/adapters/chroma.py` lines 70–100
- **Sprint**: S10
- **Category**: Performance

Synchronous Chroma API calls without `asyncio.to_thread()`.

---

### TD-87

**`_step4_contradiction` is a complete no-op**

- **File**: `app/memory/extraction.py` lines 372–376
- **Sprint**: S10
- **Category**: Dead Code

Always returns the candidate unchanged. Pipeline claims 6 steps but only 5 do anything.

---

### TD-88

**`_parse_json_response` greedy regex can match invalid JSON**

- **File**: `app/memory/extraction.py` line 104
- **Sprint**: S10
- **Category**: Code Quality

`re.search(r"\[.*\]", text, re.DOTALL)` — greedy `.*` matches from first `[` to last `]`.

**Fix**: Use non-greedy `\[.*?\]`.

---

### TD-89

**Entity link failures silently swallowed in extraction pipeline**

- **File**: `app/memory/extraction.py` lines 434–436
- **Sprint**: S10
- **Category**: Data Integrity

Bare `except Exception: pass` with zero logging.

---

### TD-90

**`prefetch_background` calls `get()` purely for side effects**

- **File**: `app/memory/recall.py` lines 347–352
- **Sprint**: S10
- **Category**: Design

Calls `get()` only to bump `last_accessed` (see also TD-62). Swallows all errors silently.

**Fix**: Add a dedicated `touch()` method.

---

### TD-91

**Internal exception details leaked in knowledge source API responses**

- **File**: `app/api/routers/knowledge_sources.py` lines 173, 223
- **Sprint**: S10
- **Category**: Security

SQL errors, connection strings sent directly to client.

**Fix**: Return generic error messages; log details server-side.

---

### TD-92

**`update_source` can't clear optional fields (None filtering)**

- **File**: `app/api/routers/knowledge_sources.py` line 136
- **Sprint**: S10
- **Category**: Bug

`if v is not None` → impossible to set `allowed_agents` back to null.

**Fix**: Use `body.model_dump(exclude_unset=True)`.

---

### TD-93

**Chroma collection fetched on every search (no caching)**

- **File**: `app/knowledge/sources/adapters/chroma.py` lines 56–65
- **Sprint**: S10
- **Category**: Performance

---

### TD-94

**No connection pool cleanup in PgVector adapter**

- **File**: `app/knowledge/sources/adapters/pgvector.py` lines 27–40
- **Sprint**: S10
- **Category**: Resource Leak

Pool created but never closed on deactivation/deletion.

---

### TD-95

**Race condition on `_adapters` dict in registry**

- **File**: `app/knowledge/sources/registry.py` line 59
- **Sprint**: S10
- **Category**: Concurrency

Mutations interleave at `await` boundaries.

---

### TD-96

**`_search_one` uses stale `consecutive_failures` count**

- **File**: `app/knowledge/sources/registry.py` line 326
- **Sprint**: S10
- **Category**: Concurrency

Concurrent failures both read `0` and both write `1`.

**Fix**: Use atomic SQL increment.

---

### TD-97

**`_audit()` fire-and-forget double-swallows all errors**

- **File**: `app/tools/builtin/memory.py` lines 752–785
- **Sprint**: S11
- **Category**: Observability

Two nested `except Exception: pass` — zero indication of audit system failure.

**Fix**: Log at WARNING. Replace deprecated `get_event_loop()` with `get_running_loop()`.

---

### TD-98

**`EVENT_TYPES`/`ACTOR_TYPES` defined but never enforced**

- **File**: `app/memory/audit.py` lines 36–63
- **Sprint**: S11
- **Category**: Validation

`log()` accepts plain `str` — any arbitrary string can be persisted.

---

### TD-99

**`NODE_TYPES`/`EDGE_TYPES` defined but never validated**

- **File**: `app/knowledge/graph.py` lines 37–55
- **Sprint**: S11
- **Category**: Validation

`add_edge` API accepts arbitrary type strings.

---

### TD-100

**Orphan detection loads 10K edges into memory, incomplete for larger graphs**

- **File**: `app/api/routers/graph.py` lines 97–128
- **Sprint**: S11
- **Category**: Performance / Correctness

Hardcoded `limit=10_000` means false-positive orphans for larger graphs.

**Fix**: Use a SQL query (`NOT IN (SELECT ... UNION SELECT ...)`).

---

### TD-101

**`memory_search` ignores `memory_type` filter on embedding path**

- **File**: `app/tools/builtin/memory.py` lines 253–258
- **Sprint**: S11
- **Category**: Correctness

Type filter only works on the FTS fallback, not the primary embedding search.

---

### TD-102

**Lifecycle audit errors logged at DEBUG — invisible in production**

- **File**: `app/memory/lifecycle.py` lines 131–134
- **Sprint**: S11
- **Category**: Observability

**Fix**: Log at WARNING.

---

### TD-103

**`run_merge` embedding failures invisible — no escalation**

- **File**: `app/memory/lifecycle.py` lines 349–351
- **Sprint**: S11
- **Category**: Code Quality

Systemic embedding store failures → DEBUG logs only, reports success.

**Fix**: Track consecutive failures; abort or escalate after threshold.

---

### TD-104

**`memory_extract_now` uses hardcoded fake session ID**

- **File**: `app/tools/builtin/memory.py` lines 738–741
- **Sprint**: S11
- **Category**: Design

All `"direct_extract"` calls share one session ID — potential interference.

**Fix**: Generate unique ID per call.

---

### TD-105

**`MemoryEvent.from_row` replaces bad timestamps with `now()`**

- **File**: `app/memory/audit.py` lines 105–110
- **Sprint**: S11
- **Category**: Data Integrity

Corrupt timestamps look like "just created" — masks data corruption.

---

### TD-106

**`get_neighborhood()` BFS silently drops errors**

- **File**: `app/knowledge/graph.py` lines 291–297
- **Sprint**: S11
- **Category**: Observability

`BaseException` results from `asyncio.gather` continue with no logging.

---

### TD-107

**`rebuild_semantic_edges` — N×M individual DB operations**

- **File**: `app/knowledge/graph.py` lines 444–480
- **Sprint**: S11
- **Category**: Performance

1000 nodes → 1000 searches + up to 10K individual insert transactions.

**Fix**: Batch edge inserts using `executemany` in a single transaction per batch.

---

### TD-108

**No rate limiting on `/api/graph/rebuild`**

- **File**: `app/api/routers/graph.py` lines 189–199
- **Sprint**: S11
- **Category**: Security / Availability

Expensive operation with no concurrency guard.

**Fix**: Add a mutex to prevent concurrent rebuilds.

---

### TD-109

**No concurrency guard on lifecycle passes**

- **File**: `app/memory/lifecycle.py` lines 435–451
- **Sprint**: S11
- **Category**: Concurrency

Two concurrent `run_all()` calls can cause double-archives, double-merges.

**Fix**: Add an `asyncio.Lock`.

---

### TD-110

**`MemoryLifecycleManager` — all store dependencies typed as `Any`**

- **File**: `app/memory/lifecycle.py` lines 96–103
- **Sprint**: S11
- **Category**: Type Safety

Bypasses all static analysis.

**Fix**: Define `Protocol` classes with required methods.

---

### TD-111

**`_parse_dt` silently returns `_now()` for corrupt date strings**

- **File**: `app/memory/models.py` lines 60–68
- **Sprint**: S09
- **Category**: Data Integrity

Bad date → current UTC time. Masks data corruption.

---

### TD-112

**Dual storage of entity links (link table + JSON column)**

- **File**: `app/memory/store.py` lines 190–210
- **Sprint**: S09
- **Category**: Design

Two sources of truth that can desync (see also TD-63).

**Fix**: Pick one canonical source.

---

### TD-113

**`_step1_classify` fallback returns ALL user/assistant messages**

- **File**: `app/memory/extraction.py` lines 307–308
- **Sprint**: S10
- **Category**: Design / Performance

LLM failure → every message treated as relevant. Large sessions flood step 2.

**Fix**: Return empty list on failure, or cap to last N messages.

---

### TD-114

**`type: ignore[return-value]` in `KnowledgeSource._dt_required`**

- **File**: `app/knowledge/sources/models.py` line 67
- **Sprint**: S10
- **Category**: Type Safety

Hides the case where `_dt()` returns `None` for a truthy non-datetime string.

---

---

## Low Severity

### TD-115

**`EntityCreateRequest.entity_type` unconstrained in API**

- **File**: `app/api/routers/entities.py` line 40
- **Sprint**: S09
- **Category**: Validation

---

### TD-116

**Unused `NotFoundError` import in vault router**

- **File**: `app/api/routers/vault.py` line 20
- **Sprint**: S09
- **Category**: Dead Code

---

### TD-117

**No validation on vault note title (length/empty)**

- **File**: `app/api/routers/vault.py` line 39
- **Sprint**: S09
- **Category**: Validation

---

### TD-118

**`entity_store.create()` does an extra `get()` round-trip**

- **File**: `app/memory/entity_store.py` lines 56–70
- **Sprint**: S09
- **Category**: Performance

---

### TD-119

**`_unique_slug` has no upper bound on loop iterations**

- **File**: `app/knowledge/vault.py` lines 168–177
- **Sprint**: S09
- **Category**: Code Quality

---

### TD-120

**`sync_from_disk` calls `row_to_dict` twice per row**

- **File**: `app/knowledge/vault.py` lines 423–425
- **Sprint**: S09
- **Category**: Performance

---

### TD-121

**Multiple `# type: ignore[valid-type]` in memory models**

- **File**: `app/memory/models.py` lines 83, 115, 131, 137
- **Sprint**: S09
- **Category**: Type Safety

**Fix**: Use `TypeAlias`.

---

### TD-122

**Truncated UUID step IDs — birthday collision risk**

- **File**: `app/workflows/models.py` line 27
- **Sprint**: S08
- **Category**: Code Quality

8 hex chars = 32 bits. ~50% collision at ~65K steps.

**Fix**: Use 12+ characters.

---

### TD-123

**Event source hardcoded to `"sessions_send_tool"` — no caller context**

- **File**: `app/tools/builtin/sessions.py` line 165
- **Sprint**: S08
- **Category**: Observability

---

### TD-124

**`_active` shared `"_global"` bucket for orphan sub-agents**

- **File**: `app/agent/sub_agent.py` lines 97–98
- **Sprint**: S08
- **Category**: Design

Unrelated callers block each other's orphan spawns.

---

### TD-125

**Duplicate `mode` validation between API handler and Pydantic model**

- **File**: `app/workflows/api.py` lines 109–113
- **Sprint**: S08
- **Category**: Code Quality

---

### TD-126

**Tests reach into private `_active` dict**

- **Files**: `tests/unit/test_sub_agent.py`, `tests/unit/test_session_tools.py`, `tests/integration/test_multi_agent.py`
- **Sprint**: S08
- **Category**: Test Design

---

### TD-127

**Private `_events_router` accessed from app.py**

- **File**: `app/api/app.py` line 315
- **Sprint**: S11
- **Category**: Design

**Fix**: Export as public `events_router`.

---

### TD-128

**`shortest_path()` uses `list.pop(0)` — O(n) per dequeue**

- **File**: `app/knowledge/graph.py` lines 498–507
- **Sprint**: S11
- **Category**: Performance

**Fix**: Use `collections.deque`.

---

### TD-129

**`get_stats()` fetches all unique nodes into Python just to count them**

- **File**: `app/knowledge/graph.py` lines 383–387
- **Sprint**: S11
- **Category**: Performance

**Fix**: Use `SELECT COUNT(*) FROM (SELECT ... UNION SELECT ...)`.

---

### TD-130

**Mutable default `{}` in `AddEdgeRequest` Pydantic model**

- **File**: `app/api/routers/graph.py` line 54
- **Sprint**: S11
- **Category**: Code Quality

---

### TD-131

**Hardcoded content truncation at 500 chars in extraction prompts**

- **File**: `app/memory/extraction.py` lines 77, 93
- **Sprint**: S10
- **Category**: Configuration

---

### TD-132

**Token estimation `len(text) // 4` fails for non-ASCII text**

- **File**: `app/memory/recall.py` lines 49–51
- **Sprint**: S10
- **Category**: Code Quality

---

### TD-133

**Unused `asyncio` import in knowledge tools**

- **File**: `app/tools/builtin/knowledge.py` line 4
- **Sprint**: S10
- **Category**: Dead Code

---

### TD-134

**`kb_search` passes `agent_id=None` to typed `str` parameter**

- **File**: `app/tools/builtin/knowledge.py` lines 62–65
- **Sprint**: S10
- **Category**: Type Safety

---

### TD-135

**No index on `auto_recall` column**

- **File**: `alembic/versions/0010_sprint10_knowledge_sources.py`
- **Sprint**: S10
- **Category**: Performance

---

### TD-136

**DB datetime defaults timezone-naive vs Python timezone-aware**

- **File**: `alembic/versions/0010_sprint10_knowledge_sources.py` lines 39–40
- **Sprint**: S10
- **Category**: Data Integrity

---

### TD-137

**HTTP adapter reports 4xx as healthy**

- **File**: `app/knowledge/sources/adapters/http.py` line 96
- **Sprint**: S10
- **Category**: Code Quality

---

---

## Severity Summary

| Severity | Count | IDs |
|----------|-------|-----|
| **Critical** | 7 | TD-43 – TD-49 |
| **High** | 16 | TD-50 – TD-65 |
| **Medium** | 33 | TD-66 – TD-114 |
| **Low** | 19 | TD-115 – TD-137 |
| **Total** | **75** | |

---

## Recommended Priority Clusters

### P0 — Security (address before any deployment)
TD-43, TD-44, TD-45, TD-46, TD-55: Knowledge source attack chain. The unauthenticated API + SQL injection + SSRF + path traversal form a complete attack surface.

### P1 — Correctness Bugs (silent data corruption or wrong results)
TD-47 (workflow steps return empty), TD-50 (feedback broken), TD-51 (confidence broken), TD-52 (recall dedup broken), TD-53 (kb_list_sources crashes), TD-54 (FAISS scores inverted), TD-65 (lifecycle skips items), TD-49 (entity merge data loss), TD-63 (stale entity_ids), TD-101 (memory_search ignores type)

### P2 — Performance (blocking I/O on event loop)
TD-60, TD-61, TD-86: All async-context blocking I/O. Quick fix (wrap in `asyncio.to_thread`) with high impact.
TD-64: Full table scan in entity resolution.
TD-107: Graph rebuild N×M transactions.

### P3 — Concurrency Guards
TD-58 (sub-agent race), TD-59 (workflow OCC), TD-109 (lifecycle concurrency), TD-48 (cancelled-but-running workflows)

### P4 — Validation Hardening
TD-80, TD-81, TD-85, TD-98, TD-99, TD-56, TD-115: Enum-like fields need Literal constraints or CHECK constraints.
