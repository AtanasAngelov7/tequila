# TD-S5 — Validation & Data Integrity

**Focus**: Enum constraints, schema validation, type safety, data consistency, migration hardening
**Items**: 14 (TD-80, TD-81, TD-85, TD-98, TD-99, TD-105, TD-110, TD-111, TD-112, TD-114, TD-115, TD-121, TD-130, TD-136)
**Severity**: 1 High, 8 Medium, 5 Low
**Status**: ✅ Complete
**Estimated effort**: ~40 minutes

---

## Goal

Add validation to all enum-like string fields across API models and domain code. Fix data integrity issues where corrupt data is silently accepted or masked. Resolve the dual entity storage design, add CHECK constraints to databases, and clean up type annotations.

---

## Items

| TD | Title | Severity | File(s) |
|----|-------|----------|---------|
| TD-85 | No CHECK constraints on enum columns in migration 0009 | **High** | New migration |
| TD-80 | `MemoryCreateRequest` doesn't validate enum fields | **Medium** | `app/api/routers/memory.py` |
| TD-81 | `expires_at` silently ignores invalid date strings | **Medium** | `app/api/routers/memory.py` |
| TD-98 | `EVENT_TYPES`/`ACTOR_TYPES` defined but never enforced | **Medium** | `app/memory/audit.py` |
| TD-99 | `NODE_TYPES`/`EDGE_TYPES` defined but never validated | **Medium** | `app/knowledge/graph.py` |
| TD-105 | `MemoryEvent.from_row` replaces bad timestamps with `now()` | **Medium** | `app/memory/audit.py` |
| TD-110 | Lifecycle stores typed as `Any` | **Medium** | `app/memory/lifecycle.py` |
| TD-111 | `_parse_dt` returns `_now()` for corrupt date strings | **Medium** | `app/memory/models.py` |
| TD-112 | Dual storage of entity links (link table + JSON column) | **Medium** | `app/memory/store.py` |
| TD-114 | `type: ignore[return-value]` in `KnowledgeSource._dt_required` | **Medium** | `app/knowledge/sources/models.py` |
| TD-115 | `EntityCreateRequest.entity_type` unconstrained | **Low** | `app/api/routers/entities.py` |
| TD-121 | Multiple `# type: ignore[valid-type]` in memory models | **Low** | `app/memory/models.py` |
| TD-130 | Mutable default `{}` in `AddEdgeRequest` | **Low** | `app/api/routers/graph.py` |
| TD-136 | DB datetime defaults timezone-naive vs Python timezone-aware | **Low** | Migration / models |

---

## Tasks

### T1: Add Literal types to memory API request models (TD-80)

**File**: `app/api/routers/memory.py` (~lines 41–56)

- [x] Change plain `str` fields to `Literal` types:
  ```python
  from typing import Literal

  class MemoryCreateRequest(BaseModel):
      memory_type: Literal["episodic", "semantic", "procedural", "preference"]
      source_type: Literal["conversation", "tool", "user", "system", "extraction"]
      scope: Literal["personal", "shared", "agent"]
      status: Literal["active", "archived", "forgotten"] = "active"
      # ... other fields
  ```
- [x] Apply the same to `MemoryUpdateRequest` if it has these fields
- [x] Check the actual valid values from `app/memory/models.py` literal definitions

### T2: Raise on invalid `expires_at` (TD-81)

**File**: `app/api/routers/memory.py` (~lines 99–106)

- [x] Replace:
  ```python
  try:
      expires_at = datetime.fromisoformat(raw_expires)
  except ValueError:
      pass  # silently ignored
  ```
  With:
  ```python
  try:
      expires_at = datetime.fromisoformat(raw_expires)
  except ValueError:
      raise HTTPException(status_code=400, detail=f"Invalid expires_at format: {raw_expires!r}")
  ```

### T3: Enforce EVENT_TYPES and ACTOR_TYPES in audit log (TD-98)

**File**: `app/memory/audit.py`

- [x] In `AuditLog.log()`, validate parameters:
  ```python
  if event_type not in EVENT_TYPES:
      raise ValueError(f"Invalid event_type: {event_type!r}. Must be one of {EVENT_TYPES}")
  if actor_type not in ACTOR_TYPES:
      raise ValueError(f"Invalid actor_type: {actor_type!r}. Must be one of {ACTOR_TYPES}")
  ```
- [x] Alternatively, change these to `Literal` types in the function signature

### T4: Enforce NODE_TYPES and EDGE_TYPES in graph store (TD-99)

**File**: `app/knowledge/graph.py`

- [x] In `add_edge()`, validate:
  ```python
  if edge_type not in EDGE_TYPES:
      raise ValueError(f"Invalid edge_type: {edge_type!r}. Must be one of {EDGE_TYPES}")
  ```
- [x] In any node creation functions, validate node types similarly
- [x] Allow extending the types via a configuration mechanism if needed (add a note)

### T5: Fix `MemoryEvent.from_row` corrupt timestamp handling (TD-105)

**File**: `app/memory/audit.py` (~lines 105–110)

- [x] Instead of silently replacing with `now()`, log a warning:
  ```python
  try:
      timestamp = datetime.fromisoformat(row["timestamp"])
  except (ValueError, TypeError):
      logger.warning("Corrupt timestamp in memory_event %s: %r — using epoch", row.get("event_id"), row.get("timestamp"))
      timestamp = datetime(2000, 1, 1, tzinfo=timezone.utc)  # Clearly wrong, not disguised as current
  ```

### T6: Add Protocol types for lifecycle store dependencies (TD-110)

**File**: `app/memory/lifecycle.py` (~lines 96–103)

- [x] Define Protocol classes for the stores:
  ```python
  from typing import Protocol, runtime_checkable

  @runtime_checkable
  class MemoryStoreProtocol(Protocol):
      async def get(self, memory_id: str) -> MemoryExtract: ...
      async def update(self, memory_id: str, **kwargs: Any) -> MemoryExtract: ...
      async def query(self, sql: str, params: list) -> list: ...

  @runtime_checkable
  class EmbeddingStoreProtocol(Protocol):
      async def search(self, query: str, top_k: int, **kwargs: Any) -> list: ...
  ```
- [x] Type the constructor parameters with these protocols instead of `Any`

### T7: Fix `_parse_dt` silent corruption masking (TD-111)

**File**: `app/memory/models.py` (~lines 60–68)

- [x] Change `_parse_dt` to raise instead of returning `_now()`:
  ```python
  def _parse_dt(value: str | datetime | None) -> datetime | None:
      if value is None:
          return None
      if isinstance(value, datetime):
          return value
      try:
          return datetime.fromisoformat(value)
      except (ValueError, TypeError):
          logger.warning("Corrupt datetime value: %r — returning None", value)
          return None  # Return None instead of disguising as now()
  ```
- [x] Update callers that rely on _parse_dt always returning a datetime to handle None

### T8: Consolidate dual entity storage (TD-112)

**File**: `app/memory/store.py` (~lines 190–210)

- [x] **Decision**: Make the link table the single source of truth; the JSON column becomes a read-through cache
- [x] In `link_entity()`: update link table first, then update JSON column (existing behavior)
- [x] In `unlink_entity()`: update link table, then update JSON column (fix from TD-63 in S2)
- [x] Add a `_sync_entity_ids_json()` helper that rebuilds the JSON from the link table:
  ```python
  async def _sync_entity_ids_json(self, memory_id: str) -> None:
      rows = await db.execute("SELECT entity_id FROM memory_entity_links WHERE memory_id = ?", [memory_id])
      entity_ids = [r["entity_id"] for r in rows]
      await db.execute("UPDATE memory_extracts SET entity_ids = ? WHERE id = ?", [json.dumps(entity_ids), memory_id])
  ```
- [x] Call `_sync_entity_ids_json()` in both `link_entity()` and `unlink_entity()`
- [x] Add a one-time repair query to fix existing stale JSON (can be a management command or migration)

### T9: Fix `type: ignore[return-value]` in KnowledgeSource (TD-114)

**File**: `app/knowledge/sources/models.py` (~line 67)

- [x] Examine `_dt_required()` — it likely returns `datetime | None` but is annotated as `datetime`
- [x] Fix the implementation to handle the None case:
  ```python
  def _dt_required(self, value: str | None) -> datetime:
      if not value:
          return datetime.now(timezone.utc)
      return datetime.fromisoformat(value)
  ```
- [x] Or change the return type annotation to match reality: `-> datetime | None`
- [x] Remove the `# type: ignore` comment

### T10: Constrain `entity_type` in API (TD-115)

**File**: `app/api/routers/entities.py` (~line 40)

- [x] Change:
  ```python
  entity_type: str
  ```
  To:
  ```python
  entity_type: Literal["person", "organization", "place", "concept", "event", "other"]
  ```
- [x] Check `app/memory/entity_store.py` or models for the actual valid set of types

### T11: Fix `type: ignore[valid-type]` in memory models (TD-121)

**File**: `app/memory/models.py` (~lines 83, 115, 131, 137)

- [x] Replace complex type annotations with `TypeAlias`:
  ```python
  from typing import TypeAlias

  MemoryType: TypeAlias = Literal["episodic", "semantic", "procedural", "preference"]
  SourceType: TypeAlias = Literal["conversation", "tool", "user", "system", "extraction"]
  ```
- [x] Use these aliases in the model definitions
- [x] Remove the `# type: ignore[valid-type]` comments

### T12: Fix mutable default in `AddEdgeRequest` (TD-130)

**File**: `app/api/routers/graph.py` (~line 54)

- [x] Change:
  ```python
  metadata: dict = {}
  ```
  To:
  ```python
  metadata: dict = Field(default_factory=dict)
  ```

### T13: Add CHECK constraints migration (TD-85)

**File**: New migration (e.g., `alembic/versions/0013_add_check_constraints.py`)

- [x] Add CHECK constraints for enum-like columns:
  ```sql
  -- memory_extracts table
  ALTER TABLE memory_extracts ADD CHECK (memory_type IN ('episodic', 'semantic', 'procedural', 'preference'));
  ALTER TABLE memory_extracts ADD CHECK (source_type IN ('conversation', 'tool', 'user', 'system', 'extraction'));
  ALTER TABLE memory_extracts ADD CHECK (scope IN ('personal', 'shared', 'agent'));
  ALTER TABLE memory_extracts ADD CHECK (status IN ('active', 'archived', 'forgotten'));

  -- entities table
  ALTER TABLE entities ADD CHECK (entity_type IN ('person', 'organization', 'place', 'concept', 'event', 'other'));
  ALTER TABLE entities ADD CHECK (status IN ('active', 'merged', 'deleted'));
  ```
- [x] Note: SQLite supports CHECK constraints but `ALTER TABLE ADD CHECK` may require table recreation. If so, enforce at the application layer only and document for future migration.

### T14: Standardize datetime timezone handling (TD-136)

**File**: Models and/or migration

- [x] Audit all `datetime.utcnow()` calls — replace with `datetime.now(timezone.utc)`
- [x] Ensure all DB defaults that use `CURRENT_TIMESTAMP` are consistent with the Python-side timezone-aware datetimes
- [x] If SQLite stores naive strings, ensure the Python layer always strips/adds tzinfo consistently

---

## Testing

### Existing tests to verify
- [x] All memory API tests pass
- [x] All audit tests pass
- [x] All graph tests pass
- [x] All entity tests pass
- [x] All knowledge source tests pass

### New tests to add
- [x] Test that invalid `memory_type` values are rejected by API (422 response)
- [x] Test that invalid `expires_at` returns 400 (not silently ignored)
- [x] Test that invalid `event_type` in audit raises ValueError
- [x] Test that invalid `edge_type` in graph raises ValueError
- [x] Test that invalid `entity_type` is rejected by API
- [x] Test that `_parse_dt` returns None for corrupt input (not current time)
- [x] Test that `_sync_entity_ids_json()` correctly rebuilds JSON from link table
- [x] Test CHECK constraint migration runs cleanly

---

## Definition of Done

- [x] All 14 items resolved
- [x] All enum-like API fields use `Literal` types
- [x] Invalid dates raise errors instead of being silently ignored
- [x] Audit and graph types are validated
- [x] Entity link storage uses single source of truth pattern
- [x] Type annotations are clean (no `type: ignore` for fixable issues)
- [x] All existing tests pass (611 unit passing, 1 skipped, 1 pre-existing failure)
- [x] New validation tests added and passing (31 tests in `test_td_s5_validation.py`)
