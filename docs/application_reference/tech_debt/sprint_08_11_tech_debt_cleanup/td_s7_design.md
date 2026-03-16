# TD-S7 — Design & Code Quality

**Focus**: Dead code, design improvements, NER quality, health check, small cleanups, test hygiene
**Items**: 23 (TD-57, TD-72, TD-73, TD-76, TD-77, TD-84, TD-87, TD-90, TD-104, TD-113, TD-116, TD-117, TD-119, TD-120, TD-122, TD-124, TD-125, TD-126, TD-127, TD-131, TD-132, TD-133, TD-134)
**Severity**: 8 Medium, 15 Low
**Status**: ⬜ Not Started
**Estimated effort**: ~40 minutes

---

## Goal

Clean up remaining design debt: implement the health-check loop, fix the contradiction step placeholder, improve NER quality, remove dead code, fix minor type issues, and tighten up test hygiene. After this sub-sprint, the codebase has no outstanding tech debt from Sprints 08–11.

---

## Items

| TD | Title | Severity | File(s) |
|----|-------|----------|---------|
| TD-57 | Health-check background task never started | **Medium** | `app/knowledge/sources/registry.py` |
| TD-72 | `total` field is page count, not DB total | **Medium** | `app/workflows/api.py` |
| TD-73 | No `agent_id` existence validation in spawn/workflow | **Medium** | `app/agent/sub_agent.py`, `app/workflows/api.py` |
| TD-76 | `update_note` doesn't rename file when title changes | **Medium** | `app/knowledge/vault.py` |
| TD-77 | `delete_note` removes disk file after DB delete | **Medium** | `app/knowledge/vault.py` |
| TD-84 | `extract_entity_mentions` high false-positive rate | **Medium** | `app/memory/entities.py` |
| TD-87 | `_step4_contradiction` is a complete no-op | **Medium** | `app/memory/extraction.py` |
| TD-113 | `_step1_classify` fallback returns ALL messages | **Medium** | `app/memory/extraction.py` |
| TD-90 | `prefetch_background` calls `get()` for side effects | **Low** | `app/memory/recall.py` |
| TD-104 | `memory_extract_now` uses hardcoded fake session ID | **Low** | `app/tools/builtin/memory.py` |
| TD-116 | Unused `NotFoundError` import in vault router | **Low** | `app/api/routers/vault.py` |
| TD-117 | No validation on vault note title | **Low** | `app/api/routers/vault.py` |
| TD-119 | `_unique_slug` has no upper bound on loop | **Low** | `app/knowledge/vault.py` |
| TD-120 | `sync_from_disk` calls `row_to_dict` twice per row | **Low** | `app/knowledge/vault.py` |
| TD-122 | Truncated UUID step IDs — collision risk | **Low** | `app/workflows/models.py` |
| TD-124 | `_active` shared `"_global"` bucket | **Low** | `app/agent/sub_agent.py` |
| TD-125 | Duplicate `mode` validation | **Low** | `app/workflows/api.py` |
| TD-126 | Tests reach into private `_active` dict | **Low** | Multiple test files |
| TD-127 | Private `_events_router` accessed from app.py | **Low** | `app/api/` module |
| TD-131 | Hardcoded content truncation at 500 chars | **Low** | `app/memory/extraction.py` |
| TD-132 | Token estimation fails for non-ASCII | **Low** | `app/memory/recall.py` |
| TD-133 | Unused `asyncio` import in knowledge tools | **Low** | `app/tools/builtin/knowledge.py` |
| TD-134 | `kb_search` passes `agent_id=None` to typed `str` | **Low** | `app/tools/builtin/knowledge.py` |

---

## Tasks

### T1: Implement health-check background loop (TD-57)

**File**: `app/knowledge/sources/registry.py` (~lines 68–77)

- [ ] Add a `start()` method that creates the background task:
  ```python
  async def start(self) -> None:
      if self._health_task is None:
          self._health_task = asyncio.create_task(self._health_loop())

  async def _health_loop(self) -> None:
      while True:
          await asyncio.sleep(self.health_check_interval_s)
          for source_id, adapter in list(self._adapters.items()):
              try:
                  healthy = await adapter.health_check()
                  if not healthy:
                      logger.warning("Source %s health check failed", source_id)
              except Exception:
                  logger.warning("Source %s health check error", source_id, exc_info=True)
  ```
- [ ] Call `start()` during app startup (in `app/api/app.py` lifespan)
- [ ] Add a `stop()` method that cancels the task for clean shutdown

### T2: Fix `total` field to return real DB count (TD-72)

**File**: `app/workflows/api.py` (~lines 123, 183)

- [ ] Add a `SELECT COUNT(*)` query for the unfiltered total:
  ```python
  total_row = await db.execute("SELECT COUNT(*) as cnt FROM workflows")
  total = total_row["cnt"]
  ```
- [ ] Return this as the `total` field instead of `len(results)`

### T3: Validate `agent_id` existence at spawn/creation time (TD-73)

**Files**: `app/agent/sub_agent.py`, `app/workflows/api.py`

- [ ] Before spawning a sub-agent or creating a workflow, verify the agent exists:
  ```python
  agent = await agent_store.get(agent_id)
  if not agent:
      raise ValueError(f"Agent '{agent_id}' not found")
  ```
- [ ] This catches typos early instead of failing at turn-loop time

### T4: Document `update_note` title-filename behavior (TD-76)

**File**: `app/knowledge/vault.py`

- [ ] Add a docstring explaining the intentional decision:
  ```python
  async def update_note(self, ...):
      """Update a note's content and/or metadata.

      Note: Filenames are NOT renamed when titles change. This is intentional
      to maintain stable filesystem paths. The title is stored in the DB only.
      """
  ```
- [ ] If rename behavior is desired in the future, add it with proper conflict handling

### T5: Fix `delete_note` order — file first, then DB (TD-77)

**File**: `app/knowledge/vault.py` (~lines 370–373)

- [ ] Reverse the order:
  ```python
  # Delete file first (can be retried if it fails)
  await asyncio.to_thread(path.unlink, missing_ok=True)
  # Then remove from DB
  await db.execute("DELETE FROM vault_notes WHERE note_id = ?", [note_id])
  ```
- [ ] This avoids orphan files that `sync_from_disk` would resurrect

### T6: Improve entity mention extraction (TD-84)

**File**: `app/memory/entities.py` (~lines 136–180)

- [ ] Expand the stopword list with common false positives:
  ```python
  _MENTION_STOPWORDS = {
      "I", "The", "This", "That", "These", "Those", "Here", "There",
      "What", "When", "Where", "Who", "How", "Why", "Which",
      "Yes", "No", "Ok", "Sure", "Thanks", "Hello", "Hi", "Hey",
      "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
      "January", "February", "March", "April", "May", "June",
      "July", "August", "September", "October", "November", "December",
      # Add more as discovered
  }
  ```
- [ ] Filter out single-word mentions that are in the stopword set
- [ ] Optionally add a minimum length filter (e.g., 2+ characters)

### T7: Add minimal contradiction detection placeholder (TD-87)

**File**: `app/memory/extraction.py` (~lines 372–376)

- [ ] The step currently returns candidates unchanged. Add a TODO and log:
  ```python
  async def _step4_contradiction(self, candidates, existing_memories):
      """Placeholder for contradiction detection — logs when enabled.

      TODO: Implement actual contradiction detection using embedding similarity
      and LLM comparison. Currently a no-op.
      """
      logger.debug("Contradiction detection step — not yet implemented (%d candidates)", len(candidates))
      return candidates
  ```
- [ ] Update the pipeline documentation to be honest about the 5-step (not 6-step) pipeline

### T8: Cap `_step1_classify` fallback (TD-113)

**File**: `app/memory/extraction.py` (~lines 307–308)

- [ ] Instead of returning ALL messages on LLM failure, cap to the most recent N:
  ```python
  MAX_FALLBACK_MESSAGES = 10

  except Exception:
      logger.warning("Classification step failed — falling back to last %d messages", MAX_FALLBACK_MESSAGES)
      return messages[-MAX_FALLBACK_MESSAGES:]
  ```

### T9: Fix `prefetch_background` to use `touch()` (TD-90)

**File**: `app/memory/recall.py` (~lines 347–352)

- [ ] After TD-S4 T4 creates the `touch()` method, update:
  ```python
  async def prefetch_background(self, memory_ids: list[str]) -> None:
      for mid in memory_ids:
          try:
              await self.store.touch(mid)
          except Exception:
              logger.debug("Prefetch touch failed for %s", mid)
  ```
- [ ] Note: This task depends on TD-S4 being complete

### T10: Generate unique session ID per `memory_extract_now` call (TD-104)

**File**: `app/tools/builtin/memory.py` (~lines 738–741)

- [ ] Replace hardcoded fake session ID:
  ```python
  import uuid
  session_id = f"direct_extract:{uuid.uuid4().hex[:12]}"
  ```

### T11: Remove unused import in vault router (TD-116)

**File**: `app/api/routers/vault.py` (~line 20)

- [ ] Remove `from app.exceptions import NotFoundError` if unused

### T12: Add vault note title validation (TD-117)

**File**: `app/api/routers/vault.py` (~line 39)

- [ ] Add validation:
  ```python
  title: str = Field(min_length=1, max_length=255)
  ```

### T13: Add loop guard to `_unique_slug` (TD-119)

**File**: `app/knowledge/vault.py` (~lines 168–177)

- [ ] Add a maximum iteration count:
  ```python
  MAX_SLUG_ATTEMPTS = 100
  for i in range(MAX_SLUG_ATTEMPTS):
      candidate = f"{base_slug}-{i}" if i > 0 else base_slug
      if not await self._slug_exists(candidate):
          return candidate
  raise RuntimeError(f"Could not generate unique slug after {MAX_SLUG_ATTEMPTS} attempts")
  ```

### T14: Cache `row_to_dict` result in `sync_from_disk` (TD-120)

**File**: `app/knowledge/vault.py` (~lines 423–425)

- [ ] Store the result and reuse:
  ```python
  row_dict = row_to_dict(row)
  # Use row_dict instead of calling row_to_dict(row) again
  ```

### T15: Increase UUID step ID length (TD-122)

**File**: `app/workflows/models.py` (~line 27)

- [ ] Change from 8 hex chars to 16:
  ```python
  step_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
  ```
- [ ] 16 hex chars = 64 bits → birthday collision at ~4 billion vs ~65K

### T16: Use `parent_id` as bucket key for sub-agent tracking (TD-124)

**File**: `app/agent/sub_agent.py` (~lines 97–98)

- [ ] Replace `"_global"` fallback with `parent_id` or `"_orphan"`:
  ```python
  bucket = parent_id if parent_id else "_orphan"
  ```

### T17: Remove duplicate `mode` validation (TD-125)

**File**: `app/workflows/api.py` (~lines 109–113)

- [ ] Remove the manual `if mode not in (...)` check in the handler — Pydantic already validates this on the request model
- [ ] Keep only the Pydantic validation

### T18: Add public API for sub-agent active count (TD-126)

**File**: `app/agent/sub_agent.py`

- [ ] Add a public method:
  ```python
  def get_active_count(parent_id: str | None = None) -> int:
      """Return the number of active sub-agents, optionally filtered by parent."""
      if parent_id:
          return len(_active.get(parent_id, {}))
      return sum(len(v) for v in _active.values())
  ```
- [ ] Update test files to use this method instead of poking `_active` directly:
  - `tests/unit/test_sub_agent.py`
  - `tests/unit/test_session_tools.py`
  - `tests/integration/test_multi_agent.py`

### T19: Make `_events_router` public (TD-127)

**File**: Source module that exports `_events_router`, and `app/api/app.py`

- [ ] Rename `_events_router` → `events_router`
- [ ] Update the import in `app/api/app.py` line ~315

### T20: Extract content truncation to constant (TD-131)

**File**: `app/memory/extraction.py` (~lines 77, 93)

- [ ] Define a constant at module top:
  ```python
  EXTRACTION_CONTENT_MAX_CHARS = 500
  ```
- [ ] Replace hardcoded `500` with the constant

### T21: Improve token estimation for non-ASCII (TD-132)

**File**: `app/memory/recall.py` (~lines 49–51)

- [ ] Replace:
  ```python
  estimated_tokens = len(text) // 4
  ```
  With:
  ```python
  estimated_tokens = len(text.encode("utf-8")) // 4
  ```
- [ ] This gives a more accurate estimate for CJK and other multi-byte text

### T22: Remove unused `asyncio` import (TD-133)

**File**: `app/tools/builtin/knowledge.py` (~line 4)

- [ ] Remove `import asyncio` if unused

### T23: Fix `agent_id=None` type mismatch (TD-134)

**File**: `app/tools/builtin/knowledge.py` (~lines 62–65)

- [ ] Change the function signature to accept `str | None`:
  ```python
  async def kb_search(query: str, ..., agent_id: str | None = None) -> ...:
  ```
- [ ] Or pass `""` instead of `None` if the downstream function expects `str`

---

## Testing

### Existing tests to verify
- [ ] All knowledge source registry tests pass
- [ ] All workflow tests pass
- [ ] All sub-agent tests pass
- [ ] All vault tests pass
- [ ] All extraction tests pass
- [ ] All recall tests pass

### New tests to add
- [ ] Test health-check loop starts and runs (mock adapter)
- [ ] Test `total` field returns correct DB count for workflows/runs
- [ ] Test that invalid `agent_id` raises at spawn time
- [ ] Test `_unique_slug` raises after max attempts
- [ ] Test `get_active_count()` public API
- [ ] Test that classify fallback returns at most MAX_FALLBACK_MESSAGES

---

## Definition of Done

- [ ] All 23 items resolved
- [ ] Health-check background task starts on app boot
- [ ] No dead code or unused imports in Sprint 08–11 files
- [ ] NER stopword list expanded
- [ ] All `type: ignore` comments in scope are resolved
- [ ] Tests use public APIs (no private dict access)
- [ ] All existing tests pass (683+, 1 pre-existing failure)
- [ ] New tests added where specified
- [ ] **All 95 tech debt items from Sprint 08–11 audit are resolved**
