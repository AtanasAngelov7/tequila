# TD-S2 — Correctness Bugs

**Focus**: Silent data corruption, wrong results, runtime errors, broken pipelines
**Items**: 11 (TD-47, TD-49, TD-50, TD-51, TD-52, TD-53, TD-54, TD-63, TD-65, TD-92, TD-101)
**Severity**: 3 Critical, 6 High, 2 Medium
**Status**: ✅ Complete
**Estimated effort**: ~55 minutes

---

## Goal

Fix all correctness bugs that cause wrong results, data loss, or runtime errors. After this sub-sprint, workflow steps return real data, feedback weighting actually works, recall deduplication is accurate, knowledge source tools don't crash, and lifecycle pagination doesn't skip items.

---

## Items

| TD | Title | Severity | File(s) |
|----|-------|----------|---------|
| TD-47 | `_run_step` passes `session_key` where `session_id` expected | **Critical** | `app/workflows/runtime.py` |
| TD-49 | `entity_merge` silently loses aliases and links on failure | **Critical** | `app/tools/builtin/memory.py` |
| TD-50 | Feedback weighting broken (loop var rebinding) | **High** | `app/memory/extraction.py` |
| TD-51 | Confidence adjustment applied globally to all candidates | **High** | `app/memory/extraction.py` |
| TD-52 | Recall dedup uses substring containment — false positives | **High** | `app/memory/recall.py` |
| TD-53 | `kb_list_sources` uses `src.id` — AttributeError | **High** | `app/tools/builtin/knowledge.py` |
| TD-54 | FAISS L2 score interpretation inverted | **High** | `app/knowledge/sources/adapters/faiss.py` |
| TD-63 | `unlink_entity` doesn't update `entity_ids` JSON column | **High** | `app/memory/store.py` |
| TD-65 | Offset pagination during mutations skips items | **High** | `app/memory/lifecycle.py` |
| TD-92 | `update_source` can't clear optional fields (None filtering) | **Medium** | `app/api/routers/knowledge_sources.py` |
| TD-101 | `memory_search` ignores `memory_type` on embedding path | **Medium** | `app/tools/builtin/memory.py` |

---

## Tasks

### T1: Fix `_run_step` session_key vs session_id (TD-47)

**File**: `app/workflows/runtime.py` (~line 104)

- [x] The bug: `sub_key` is a session_key string like `"agent:bot:sub:abc12345"`, but `list_by_session()` expects a UUID `session_id`
- [x] Fix: Resolve `sub_key` to a session record first, then use its `session_id`:
  ```python
  session = await session_store.get_by_key(sub_key)
  messages = await msg_store.list_by_session(session.session_id, limit=50, active_only=True)
  ```
- [x] Verify that `session_store` is available in the runtime context (inject via constructor if needed)

### T2: Fix entity_merge silent data loss (TD-49)

**File**: `app/tools/builtin/memory.py` (~lines 579–598)

- [x] Replace `except Exception: pass` blocks in alias transfer and memory relinking with:
  ```python
  failures = []
  for alias in (source.aliases or []):
      try:
          await store.add_alias(target_entity_id, alias)
      except Exception as exc:
          failures.append(f"alias '{alias}': {exc}")
          logger.warning("entity_merge: failed to transfer alias %r", alias, exc_info=True)
  ```
- [x] Do the same for memory relinking (`link_entity`/`unlink_entity` calls)
- [x] Include `"partial_failures": failures` in the merge response dict when `failures` is non-empty
- [x] If alias transfer fails, do not proceed to delete the source entity (leave both alive for manual resolution)

### T3: Fix feedback weighting loop variable rebinding (TD-50)

**File**: `app/memory/extraction.py` (~lines 189–196)

- [x] The bug: `msg = dict(msg, _confidence_boost=0.2)` creates a new dict but doesn't update the list
- [x] Fix: Use index-based mutation:
  ```python
  for i, msg in enumerate(weighted):
      if rating == "up":
          weighted[i] = dict(msg, _confidence_boost=0.2)
      elif rating == "down":
          weighted[i] = dict(msg, _confidence_boost=-0.15)
  ```

### T4: Fix confidence adjustment global application (TD-51)

**File**: `app/memory/extraction.py` (~lines 215–224)

- [x] The bug: Boosts from all messages are summed and applied identically to every candidate
- [x] Fix: Track which messages generated each candidate during step 2 (extraction):
  - Add a `_source_msg_indices: list[int]` field to each candidate dict during extraction
  - In the confidence adjustment, only sum boosts from matched message indices:
    ```python
    for candidate in candidates:
        source_indices = candidate.get("_source_msg_indices", [])
        boost = sum(
            weighted[i].get("_confidence_boost", 0.0)
            for i in source_indices
            if i < len(weighted)
        )
        candidate["confidence"] = min(1.0, max(0.0, candidate.get("confidence", 0.5) + boost))
    ```
- [x] Remove `_source_msg_indices` before persisting (strip internal fields)

### T5: Fix recall dedup substring false positives (TD-52)

**File**: `app/memory/recall.py` (~lines 368–370)

- [x] The bug: `c.get("content", "") not in always_content` uses Python string `in` — substring match
- [x] Fix: Build a set of exact content strings and use set membership:
  ```python
  always_content_set = {item.get("content", "") for item in always_memories}
  return [c for c in candidates if c.get("content", "") not in always_content_set]
  ```

### T6: Fix `kb_list_sources` AttributeError (TD-53)

**File**: `app/tools/builtin/knowledge.py` (~line 119)

- [x] Change `src.id` to `src.source_id` (the correct field name on `KnowledgeSource`)

### T7: Fix FAISS L2 score inversion (TD-54)

**File**: `app/knowledge/sources/adapters/faiss.py` (~lines 67–69)

- [x] After FAISS search returns `(distances, indices)`, convert L2 distances to similarity scores:
  ```python
  # L2: lower distance = more similar. Convert to 0–1 similarity score.
  scores = [1.0 / (1.0 + d) for d in distances[0]]
  ```
- [x] If the index uses inner product (IP), scores can be used directly (higher = more similar)
- [x] Optionally detect metric type: `faiss.downcast_index(self._index).metric_type`

### T8: Fix `unlink_entity` stale JSON column (TD-63)

**File**: `app/memory/store.py` (~lines 204–210)

- [x] After removing from the link table, also update the memory's `entity_ids` JSON:
  ```python
  async def unlink_entity(self, memory_id: str, entity_id: str) -> None:
      # Remove from link table
      await db.execute("DELETE FROM memory_entity_links WHERE memory_id = ? AND entity_id = ?", [memory_id, entity_id])
      # Also remove from JSON column
      memory = await self.get(memory_id)
      current_ids = json.loads(memory.entity_ids) if memory.entity_ids else []
      updated_ids = [eid for eid in current_ids if eid != entity_id]
      await db.execute("UPDATE memory_extracts SET entity_ids = ? WHERE id = ?", [json.dumps(updated_ids), memory_id])
  ```

### T9: Fix lifecycle offset pagination during mutations (TD-65)

**File**: `app/memory/lifecycle.py` (~lines 198–275, 301–397)

- [x] Replace offset-based pagination with cursor-based in all three mutation passes:
  - `run_archive`
  - `run_expire_tasks` (if using offset pagination)
  - `run_merge`
- [x] Pattern:
  ```python
  last_seen_id = ""
  while True:
      batch = await store.query(
          "SELECT * FROM memory_extracts WHERE id > ? AND status = 'active' ORDER BY id LIMIT ?",
          [last_seen_id, batch_size]
      )
      if not batch:
          break
      last_seen_id = batch[-1].id
      # ... process batch (archive/merge/etc.)
  ```
- [x] This avoids skipping items when rows are mutated (archived/deleted) during iteration

### T10: Fix `update_source` None filtering (TD-92)

**File**: `app/api/routers/knowledge_sources.py` (~line 136)

- [x] Replace `{k: v for k, v in body.dict().items() if v is not None}` with:
  ```python
  updates = body.model_dump(exclude_unset=True)
  ```
- [x] This allows explicitly setting fields to `None` (e.g., clearing `allowed_agents`) while still ignoring fields the client didn't include

### T11: Fix `memory_search` type filter on embedding path (TD-101)

**File**: `app/tools/builtin/memory.py` (~lines 253–258)

- [x] The bug: `memory_type` filter is only applied on the FTS fallback, not the embedding search
- [x] Fix: Pass the `memory_type` parameter through to the embedding search:
  - If the embedding store supports metadata filtering, pass `memory_type` as a filter
  - If not, apply a post-filter: `results = [r for r in results if r.memory_type == memory_type]`

---

## Testing

### Existing tests to verify
- [x] All workflow runtime tests pass
- [x] All memory tool tests pass (especially entity_merge tests)
- [x] All extraction pipeline tests pass
- [x] All recall tests pass
- [x] All knowledge tool tests pass
- [x] All lifecycle tests pass

### New tests to add
- [x] Test that `_run_step` correctly resolves session_key → session_id and retrieves messages
- [x] Test that entity_merge reports partial failures in response (not silent)
- [x] Test that feedback weighting actually modifies the weighted list
- [x] Test that confidence boosts are applied per-candidate, not globally
- [x] Test that dedup uses exact match (not substring)
- [x] Test that `kb_list_sources` works without AttributeError
- [x] Test that FAISS scores are correctly converted (higher = more similar)
- [x] Test that `unlink_entity` clears both link table and JSON column
- [x] Test that lifecycle pagination processes all items (no skips under mutation)
- [x] Test that `update_source` with explicit None clears the field
- [x] Test that `memory_search` with `memory_type` filter works on embedding path

---

## Definition of Done

- [x] All 11 items resolved
- [x] Workflow steps return real message data (not empty)
- [x] Feedback weighting modifies candidate confidence correctly
- [x] Recall dedup uses exact string comparison
- [x] `kb_list_sources` runs without exceptions
- [x] FAISS returns most-similar results first (not least-similar)
- [x] Entity unlinking is consistent across link table and JSON
- [x] Lifecycle processes every item without skipping
- [x] All existing tests pass (519 unit, 202 integration, 1 pre-existing failure)
- [x] New regression tests added and passing (14 tests in `tests/unit/test_td_s2_correctness.py`)
