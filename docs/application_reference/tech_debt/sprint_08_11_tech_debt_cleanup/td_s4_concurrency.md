# TD-S4 — Concurrency & Resource Management

**Focus**: Race conditions, optimistic concurrency, cancellation, resource leaks
**Items**: 11 (TD-48, TD-58, TD-59, TD-62, TD-68, TD-70, TD-83, TD-94, TD-95, TD-96, TD-109)
**Severity**: 2 Critical, 3 High, 6 Medium
**Status**: ✅ Complete
**Estimated effort**: ~45 minutes

---

## Goal

Eliminate race conditions and data races in concurrent agent operations, add proper optimistic concurrency control where needed, implement real workflow cancellation, fix resource leaks, and protect shared state with appropriate locks.

---

## Items

| TD | Title | Severity | File(s) |
|----|-------|----------|---------|
| TD-48 | Workflow cancellation is a no-op | **Critical** | `app/workflows/api.py`, `app/workflows/runtime.py` |
| TD-58 | TOCTOU race in sub-agent concurrency check | **High** | `app/agent/sub_agent.py` |
| TD-59 | `update_run_status` has no OCC | **High** | `app/workflows/store.py` |
| TD-62 | `MemoryStore.get()` bumps access_count (side effect) | **High** | `app/memory/store.py` |
| TD-68 | Race between event and message persistence | **Medium** | `app/tools/builtin/sessions.py`, `app/workflows/runtime.py` |
| TD-70 | `_active` dict memory leak when `auto_archive_minutes=0` | **Medium** | `app/agent/sub_agent.py` |
| TD-83 | `EntityStore.update()` has no OCC | **Medium** | `app/memory/entity_store.py` |
| TD-94 | No connection pool cleanup in PgVector adapter | **Medium** | `app/knowledge/sources/adapters/pgvector.py` |
| TD-95 | Race condition on `_adapters` dict in registry | **Medium** | `app/knowledge/sources/registry.py` |
| TD-96 | `_search_one` uses stale `consecutive_failures` count | **Medium** | `app/knowledge/sources/registry.py` |
| TD-109 | No concurrency guard on lifecycle passes | **Medium** | `app/memory/lifecycle.py` |

---

## Tasks

### T1: Implement real workflow cancellation (TD-48)

**Files**: `app/workflows/api.py`, `app/workflows/runtime.py`

- [x] Add a cancellation mechanism using `asyncio.Event`:
  ```python
  # In workflow api.py — store cancel events by run_id
  _cancel_events: dict[str, asyncio.Event] = {}
  ```
- [x] When `cancel_run()` is called:
  ```python
  event = _cancel_events.get(run_id)
  if event:
      event.set()
  await store.update_run_status(run_id, "cancelled")
  ```
- [x] When `_execute()` starts a run:
  ```python
  cancel_event = asyncio.Event()
  _cancel_events[run_id] = cancel_event
  try:
      await pipeline.run(steps, cancel_event=cancel_event)
  finally:
      _cancel_events.pop(run_id, None)
  ```
- [x] In the pipeline/runtime loop, check cancellation between steps:
  ```python
  for step in steps:
      if cancel_event.is_set():
          logger.info("Workflow %s cancelled", run_id)
          break
      await self._run_step(step)
  ```
- [x] In parallel execution, check before spawning each parallel task

### T2: Add asyncio.Lock for sub-agent spawn (TD-58)

**File**: `app/agent/sub_agent.py` (~lines 96–117)

- [x] Add a lock registry:
  ```python
  _spawn_locks: dict[str, asyncio.Lock] = {}

  def _get_spawn_lock(parent_id: str) -> asyncio.Lock:
      if parent_id not in _spawn_locks:
          _spawn_locks[parent_id] = asyncio.Lock()
      return _spawn_locks[parent_id]
  ```
- [x] Wrap the check-and-register in `spawn()`:
  ```python
  lock = _get_spawn_lock(parent_id)
  async with lock:
      count = _count_active(parent_id)
      if count >= max_concurrent:
          raise RuntimeError(f"Max concurrent sub-agents ({max_concurrent}) reached")
      _register(parent_id, agent_id, session_key)
  ```

### T3: Add OCC guard to workflow status updates (TD-59)

**File**: `app/workflows/store.py` (~lines 175–211)

- [x] Add a `WHERE status != 'cancelled'` guard to the UPDATE:
  ```sql
  UPDATE workflow_runs
  SET status = ?, updated_at = ?
  WHERE run_id = ? AND status != 'cancelled'
  ```
- [x] Check `changes()` after the update — if 0 rows affected and the target status wasn't 'cancelled', the run was already cancelled
- [x] Return a boolean or raise an exception to signal that the update was rejected

### T4: Split `MemoryStore.get()` into read-only + touch (TD-62)

**File**: `app/memory/store.py` (~lines 102–115)

- [x] Make `get()` purely read-only (remove the `access_count` bump and `last_accessed` update):
  ```python
  async def get(self, memory_id: str) -> MemoryExtract:
      """Read-only fetch — no side effects."""
      row = await db.execute("SELECT * FROM memory_extracts WHERE id = ?", [memory_id])
      if not row:
          raise NotFoundError(f"Memory {memory_id} not found")
      return MemoryExtract.from_row(row)
  ```
- [x] Add a new `touch()` method for intentional access tracking:
  ```python
  async def touch(self, memory_id: str) -> None:
      """Bump access_count and last_accessed timestamp."""
      await db.execute(
          "UPDATE memory_extracts SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
          [datetime.utcnow().isoformat(), memory_id]
      )
  ```
- [x] Update callers:
  - `recall.py` (after retrieving memories for a prompt) → call `touch()`
  - `recall.py` `prefetch_background` → call `touch()` instead of `get()`
  - All other internal callers (`update()`, `delete()`, `soft_delete()`, `link_entity()`, `unlink_entity()`) should use `get()` only (no side effects)

### T5: Fix race between event and message persistence (TD-68)

**Files**: `app/tools/builtin/sessions.py`, `app/workflows/runtime.py`

- [x] Include the reply content directly in the `AGENT_RUN_COMPLETE` event payload:
  ```python
  await emit(ET.AGENT_RUN_COMPLETE, {
      "session_key": key,
      "reply": reply_content,  # Include content directly
  })
  ```
- [x] Consumers that need the reply can use the event payload instead of re-reading from the DB
- [x] Alternatively, add a brief `asyncio.sleep(0)` to yield control and allow the DB write to flush before firing the event

### T6: Fix memory leak in `_active` when `auto_archive_minutes=0` (TD-70)

**File**: `app/agent/sub_agent.py` (~lines 138–144)

- [x] Add cleanup unconditionally after the agent run completes:
  ```python
  async def _run_and_cleanup(parent_id, agent_id, session_key, ...):
      try:
          await agent.run(...)
      finally:
          _unregister(parent_id, session_key)
  ```
- [x] The `_auto_archive` path still runs if configured, but cleanup happens regardless

### T7: Add OCC to `EntityStore.update()` (TD-83)

**File**: `app/memory/entity_store.py` (~lines 133–158)

- [x] Add a `version` column check if one exists, or use a `WHERE updated_at = ?` guard:
  ```sql
  UPDATE entities
  SET name = ?, entity_type = ?, aliases = ?, metadata = ?, updated_at = ?
  WHERE entity_id = ? AND updated_at = ?
  ```
- [x] If the entity table already has a `version` column, use the standard OCC pattern:
  ```sql
  UPDATE entities SET ..., version = version + 1 WHERE entity_id = ? AND version = ?
  ```
- [x] If no `version` column exists, add one via a migration (small schema change, single column)
- [x] Retry up to 3 times on conflict before raising

### T8: Add connection pool cleanup to PgVector adapter (TD-94)

**File**: `app/knowledge/sources/adapters/pgvector.py` (~lines 27–40)

- [x] Add a `deactivate()` method that closes the connection pool:
  ```python
  async def deactivate(self) -> None:
      if self._pool:
          await self._pool.close()
          self._pool = None
  ```
- [x] Ensure the registry calls `deactivate()` when a source is deleted or deactivated
- [x] Also close the pool in `__del__` as a safety net (best-effort)

### T9: Add lock to registry `_adapters` dict (TD-95)

**File**: `app/knowledge/sources/registry.py` (~line 59)

- [x] Add a module-level or instance-level `asyncio.Lock`:
  ```python
  self._adapter_lock = asyncio.Lock()
  ```
- [x] Guard all mutations of `self._adapters` with the lock:
  ```python
  async with self._adapter_lock:
      self._adapters[source_id] = adapter
  ```
- [x] Read operations can proceed without the lock (dict reads are effectively atomic in CPython, but use the lock for consistency if mutations are in flight)

### T10: Fix stale `consecutive_failures` count (TD-96)

**File**: `app/knowledge/sources/registry.py` (~line 326)

- [x] Replace the read-then-write pattern with an atomic SQL increment:
  ```sql
  UPDATE knowledge_sources
  SET consecutive_failures = consecutive_failures + 1,
      last_failure_at = ?
  WHERE source_id = ?
  ```
- [x] For reset on success:
  ```sql
  UPDATE knowledge_sources SET consecutive_failures = 0 WHERE source_id = ?
  ```

### T11: Add concurrency guard to lifecycle passes (TD-109)

**File**: `app/memory/lifecycle.py` (~lines 435–451)

- [x] Add an instance-level lock:
  ```python
  self._run_lock = asyncio.Lock()
  ```
- [x] Guard `run_all()`:
  ```python
  async def run_all(self) -> dict:
      if self._run_lock.locked():
          logger.info("Lifecycle pass already in progress, skipping")
          return {"skipped": True}
      async with self._run_lock:
          return await self._run_all_impl()
  ```

---

## Testing

### Existing tests to verify
- [x] All workflow tests pass (cancellation changes)
- [x] All sub-agent tests pass (lock + cleanup changes)
- [x] All memory store tests pass (`get`/`touch` split)
- [x] All entity store tests pass (OCC)
- [x] All knowledge source tests pass (pool cleanup, adapter lock)
- [x] All lifecycle tests pass (concurrency guard)

### New tests to add
- [x] Test workflow cancellation: start run → cancel → verify steps stop
- [x] Test sub-agent spawn lock: concurrent spawns respect max limit
- [x] Test that `get()` is now read-only (no access_count bump)
- [x] Test that `touch()` does bump access_count
- [x] Test OCC conflict in entity update (concurrent modifications)
- [x] Test lifecycle skips when already running
- [x] Test workflow status update rejected when already cancelled

---

## Definition of Done

- [x] All 11 items resolved
- [x] Workflow cancellation actually stops execution
- [x] Sub-agent spawns are race-free
- [x] `MemoryStore.get()` has no side effects
- [x] Entity updates use OCC
- [x] Knowledge source adapters clean up resources
- [x] Lifecycle passes cannot run concurrently
- [x] All existing tests pass (683+, 1 pre-existing failure)
- [x] New concurrency tests added and passing
