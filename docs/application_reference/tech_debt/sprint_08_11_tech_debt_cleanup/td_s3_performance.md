# TD-S3 — Performance & Async

**Focus**: Blocking I/O in async contexts, full table scans, N+1 queries, missing caches/indexes
**Items**: 13 (TD-60, TD-61, TD-64, TD-75, TD-78, TD-86, TD-93, TD-100, TD-107, TD-118, TD-128, TD-129, TD-135)
**Severity**: 3 High, 7 Medium, 3 Low
**Status**: ✅ Complete
**Estimated effort**: ~45 minutes

---

## Goal

Eliminate all blocking synchronous I/O from async code paths, fix N+1 query patterns, and add missing database indexes. After this sub-sprint, the event loop is never blocked by file I/O, CPU-bound inference, or ChromaDB calls.

---

## Items

| TD | Title | Severity | File(s) |
|----|-------|----------|---------|
| TD-60 | Blocking sync I/O in vault async methods | **High** | `app/knowledge/vault.py` |
| TD-61 | `LocalEmbeddingProvider.embed()` CPU-bound on event loop | **High** | `app/knowledge/embeddings.py` |
| TD-64 | `EntityStore.resolve()` full table scan for alias matching | **High** | `app/memory/entity_store.py` |
| TD-75 | `sync_from_disk` opens separate transaction per file | **Medium** | `app/knowledge/vault.py` |
| TD-78 | Embedding `_load_vectors` cache inconsistent for filtered queries | **Medium** | `app/knowledge/embeddings.py` |
| TD-86 | ChromaDB calls block event loop | **Medium** | `app/knowledge/sources/adapters/chroma.py` |
| TD-93 | Chroma collection fetched on every search (no caching) | **Medium** | `app/knowledge/sources/adapters/chroma.py` |
| TD-100 | Orphan detection loads 10K edges into Python | **Medium** | `app/api/routers/graph.py` |
| TD-107 | `rebuild_semantic_edges` — N×M individual DB operations | **Medium** | `app/knowledge/graph.py` |
| TD-118 | `entity_store.create()` extra `get()` round-trip | **Low** | `app/memory/entity_store.py` |
| TD-128 | `shortest_path()` uses `list.pop(0)` — O(n) per dequeue | **Low** | `app/knowledge/graph.py` |
| TD-129 | `get_stats()` fetches all unique nodes into Python to count | **Low** | `app/knowledge/graph.py` |
| TD-135 | No index on `auto_recall` column | **Low** | New migration |

---

## Tasks

### T1: Wrap vault file I/O in `asyncio.to_thread()` (TD-60)

**File**: `app/knowledge/vault.py`

- [x] Find all `path.read_text()`, `path.write_text()`, `path.exists()`, `path.unlink()`, `path.mkdir()`, `path.rename()` calls
- [x] Wrap each in `await asyncio.to_thread(...)`:  
  ```python
  content = await asyncio.to_thread(path.read_text, encoding="utf-8")
  await asyncio.to_thread(path.write_text, content, encoding="utf-8")
  exists = await asyncio.to_thread(path.exists)
  await asyncio.to_thread(path.unlink, missing_ok=True)
  ```
- [x] Import `asyncio` at module top if not already imported
- [x] Applies to: `create_note`, `update_note`, `delete_note`, `sync_from_disk`, `_write_file`, and any other async methods using sync file ops

### T2: Wrap embedding model inference in thread (TD-61)

**File**: `app/knowledge/embeddings.py` (~lines 88–92)

- [x] Wrap the `model.encode()` call:
  ```python
  vectors = await asyncio.to_thread(model.encode, texts, normalize_embeddings=True)
  ```
- [x] This moves the CPU-bound inference off the event loop

### T3: Fix entity resolve full table scan with SQL (TD-64)

**File**: `app/memory/entity_store.py` (~lines 111–121)

- [x] Replace the Python-side scan with a SQL query using `json_each()`:  
  ```sql
  SELECT e.*
  FROM entities e, json_each(e.aliases) AS j
  WHERE j.value = ? COLLATE NOCASE
    AND e.status = 'active'
  UNION
  SELECT e.*
  FROM entities e
  WHERE e.name = ? COLLATE NOCASE
    AND e.status = 'active'
  ```
- [x] This leverages SQLite's `json_each()` table-valued function for efficient alias lookup
- [x] Entities matched by name checked first; aliases via `json_each()` second (LIMIT 1)

### T4: Batch `sync_from_disk` into single transaction (TD-75)

**File**: `app/knowledge/vault.py` (~lines 437–470)

- [x] Collect all changes (inserts, updates, deletes) into lists
- [x] Execute them in a single write transaction:
  ```python
  async with get_write_db() as db:
      async with write_transaction(db):
          for note_data in inserts:
              await db.execute("INSERT INTO ...", note_data)
          for note_data in updates:
              await db.execute("UPDATE ...", note_data)
          for note_id in deletes:
              await db.execute("DELETE ...", [note_id])
  ```

### T5: Fix embedding cache for filtered queries (TD-78)

**File**: `app/knowledge/embeddings.py` (~lines 198–221)

- [x] Include the filter parameters in the cache key:
  ```python
  cache_key = tuple(sorted(source_types)) if source_types is not None else None
  ```
- [x] Cache filtered query results alongside unfiltered results
- [x] On `_invalidate()`, clear all cache entries (both filtered and unfiltered)

### T6: Wrap ChromaDB calls in `asyncio.to_thread()` (TD-86)

**File**: `app/knowledge/sources/adapters/chroma.py` (~lines 70–100)

- [x] Wrap all synchronous Chroma API calls:
  ```python
  results = await asyncio.to_thread(collection.query, query_embeddings=..., n_results=...)
  ```
- [x] Applies to: `collection.query()`, `collection.count()`, `client.heartbeat()`

### T7: Cache Chroma collection object (TD-93)

**File**: `app/knowledge/sources/adapters/chroma.py` (~lines 56–65)

- [x] Fetch the collection once via `_get_collection()` and store as `self._collection`
- [x] Reuse `self._collection` in `search()` and other methods instead of fetching each time
- [x] Added `self._collection: Any = None` attribute in `__init__`

### T8: Move orphan detection to SQL (TD-100)

**File**: `app/api/routers/graph.py` (~lines 97–128)

- [x] Replace Python-side set operations with direct SQL subqueries on `gs._db`:
  ```sql
  SELECT m.id FROM memory_extracts m
  WHERE m.status = 'active'
    AND m.id NOT IN (
      SELECT source_id FROM graph_edges
      UNION SELECT target_id FROM graph_edges
    )
  LIMIT ?
  ```
- [x] Same pattern for entity orphans; no `list_edges(10_000)` call
- [x] Handles any graph size without loading edges into Python

### T9: Batch edge inserts in `rebuild_semantic_edges` (TD-107)

**File**: `app/knowledge/graph.py` (~lines 444–480)

- [x] Collect edges to insert into a list (`edges_to_insert`)
- [x] Use `executemany` in a single transaction per batch of 500
- [x] Also fixed 3 bugs: `execute_fetchall` → standard `execute/fetchall`, `"id"` column → `"source_id"`, `hit.score` → `hit.similarity`

### T10: Remove redundant `get()` in `entity_store.create()` (TD-118)

**File**: `app/memory/entity_store.py` (~lines 56–70)

- [x] After `INSERT`, construct and return the entity model directly from the input data instead of doing an extra `get()` round-trip
- [x] The `INSERT` already has all the fields — no need to re-read from DB

### T11: Use `collections.deque` for BFS in `shortest_path()` (TD-128)

**File**: `app/knowledge/graph.py` (~lines 498–507)

- [x] Replace:
  ```python
  queue = [start_node]
  # ...
  current = queue.pop(0)  # O(n)
  ```
  With:
  ```python
  from collections import deque
  queue = deque([start_node])
  # ...
  current = queue.popleft()  # O(1)
  ```
- [x] `from collections import deque` added to imports

### T12: Move `get_stats()` unique node count to SQL (TD-129)

**File**: `app/knowledge/graph.py` (~lines 383–387)

- [x] Replace Python-side counting with SQL:
  ```sql
  SELECT COUNT(*) FROM (
      SELECT source_id AS nid FROM graph_edges
      UNION
      SELECT target_id AS nid FROM graph_edges
  )
  ```

### T13: Add migration for `auto_recall` index (TD-135)

**File**: New migration: `alembic/versions/0012_add_auto_recall_index.py`

- [x] Created `alembic/versions/0012_td_s3_auto_recall_index.py`:
  ```python
  def upgrade():
      op.create_index("ix_knowledge_sources_auto_recall", "knowledge_sources", ["auto_recall"])
  ```
- [x] `revision = "0012"`, `down_revision = "0011"`

---

## Testing

### Existing tests to verify
- [x] All vault tests pass (file ops now async but behavior unchanged)
- [x] All embedding tests pass
- [x] All entity store tests pass
- [x] All graph tests pass
- [x] All knowledge source adapter tests pass
- [x] All lifecycle tests pass

### New tests added (`tests/unit/test_td_s3_performance.py` — 30 tests)
- [x] Test that `entity_store.resolve()` finds entities by alias (SQL query works)
- [x] Test that `get_stats()` returns correct node count
- [x] Test that `shortest_path()` works correctly (deque doesn't change behavior)
- [x] Test that orphan detection returns correct results via SQL
- [x] Test vault async file I/O (source inspection + functional round-trip)
- [x] Test embedding filter-keyed cache
- [x] Test Chroma collection caching
- [x] Test `entity_store.create()` no round-trip
- [x] Test migration 0012 index definition and DB presence
- [x] Test `rebuild_semantic_edges` uses `executemany` and `hit.similarity`

---

## Definition of Done

- [x] All 13 items resolved
- [x] Zero blocking sync calls in async code paths (`to_thread` wrapping complete)
- [x] Entity resolve uses SQL instead of Python scan
- [x] Graph operations use batched SQL and SQL-based counting
- [x] New migration for `auto_recall` index created and tested
- [x] All existing tests pass (549 unit passed, 1 skipped; integration: 202 passed, 1 pre-existing failure)
- [x] New tests added: 30 tests in `test_td_s3_performance.py`
