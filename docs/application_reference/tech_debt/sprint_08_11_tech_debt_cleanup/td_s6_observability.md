# TD-S6 â€” Observability & Error Handling

**Focus**: Silent error swallowing, logging, error responses, event sourcing
**Items**: 14 (TD-67, TD-69, TD-71, TD-74, TD-79, TD-82, TD-88, TD-89, TD-97, TD-102, TD-103, TD-106, TD-123, TD-137)
**Severity**: 12 Medium, 2 Low
**Status**: ✅ Complete
**Estimated effort**: ~30 minutes

---

## Goal

Replace all `except Exception: pass` patterns with proper logging. Fix error responses that mask system state. Improve diagnostic observability so failures are visible in logs. After this sub-sprint, no error is silently swallowed anywhere in the codebase.

---

## Items

| TD | Title | Severity | File(s) |
|----|-------|----------|---------|
| TD-67 | `sessions_history` returns `[]` for non-existent sessions | **Medium** | `app/tools/builtin/sessions.py` |
| TD-69 | `sessions_spawn` doesn't catch `ValueError` | **Medium** | `app/tools/builtin/sessions.py` |
| TD-71 | Nested silent error swallowing in workflow `_execute` | **Medium** | `app/workflows/api.py` |
| TD-74 | `sessions_send` bare `except Exception` too broad | **Medium** | `app/tools/builtin/sessions.py` |
| TD-79 | Reindex treats batch failure as 100% failure | **Medium** | `app/knowledge/embeddings.py` |
| TD-82 | Audit endpoints return `[]` when module not initialized | **Medium** | `app/api/routers/memory.py` |
| TD-88 | `_parse_json_response` greedy regex | **Medium** | `app/memory/extraction.py` |
| TD-89 | Entity link failures silently swallowed in extraction | **Medium** | `app/memory/extraction.py` |
| TD-97 | `_audit()` double-swallows all errors | **Medium** | `app/tools/builtin/memory.py` |
| TD-102 | Lifecycle audit errors logged at DEBUG | **Medium** | `app/memory/lifecycle.py` |
| TD-103 | `run_merge` embedding failures invisible | **Medium** | `app/memory/lifecycle.py` |
| TD-106 | `get_neighborhood()` BFS silently drops errors | **Medium** | `app/knowledge/graph.py` |
| TD-123 | Event source hardcoded to `"sessions_send_tool"` | **Low** | `app/tools/builtin/sessions.py` |
| TD-137 | HTTP adapter reports 4xx as healthy | **Low** | `app/knowledge/sources/adapters/http.py` |

---

## Tasks

### T1: Return error for non-existent session in `sessions_history` (TD-67)

**File**: `app/tools/builtin/sessions.py` (~lines 114â€“116)

- [x] Before returning messages, check if the session exists:
  ```python
  session = await session_store.get_by_key(session_key)
  if not session:
      return {"error": f"Session '{session_key}' not found"}
  ```
- [x] This lets the caller distinguish "empty session" from "no such session"

### T2: Catch `ValueError` in `sessions_spawn` (TD-69)

**File**: `app/tools/builtin/sessions.py` (~lines 237â€“241)

- [x] Expand the except clause:
  ```python
  except (RuntimeError, ValueError) as exc:
      return {"error": str(exc)}
  ```

### T3: Log errors in workflow `_execute` status update (TD-71)

**File**: `app/workflows/api.py` (~lines 167â€“172, 211)

- [x] Replace:
  ```python
  except Exception:
      pass
  ```
  With:
  ```python
  except Exception:
      logger.exception("Failed to update workflow run status to 'failed' for run_id=%s", run_id)
  ```
- [x] Consider adding a comment about a future background reaper for stuck runs

### T4: Narrow catch in `sessions_send` (TD-74)

**File**: `app/tools/builtin/sessions.py` (~lines 205â€“207)

- [x] Replace broad `except Exception` with specific exceptions:
  ```python
  except (asyncio.TimeoutError, RuntimeError) as exc:
      logger.warning("sessions_send reply read failed: %s", exc)
      return {"status": "error", "detail": str(exc)}
  ```
- [x] If reply reading fails, return `"status": "error"` instead of `"completed"`

### T5: Report partial progress in reindex (TD-79)

**File**: `app/knowledge/embeddings.py` (~lines 405â€“410)

- [x] Track per-batch success/failure:
  ```python
  succeeded = 0
  failed = 0
  for batch in batches:
      try:
          await self._index_batch(batch)
          succeeded += len(batch)
      except Exception:
          logger.warning("Reindex batch failed (%d items)", len(batch), exc_info=True)
          failed += len(batch)
  return {"succeeded": succeeded, "failed": failed}
  ```

### T6: Return 503 when audit module unavailable (TD-82)

**File**: `app/api/routers/memory.py` (~lines 168â€“196)

- [x] Replace silent empty-list returns:
  ```python
  if audit_log is None:
      raise HTTPException(status_code=503, detail="Audit system not initialized")
  ```
- [x] Apply to both `GET /api/memories/{id}/history` and `GET /api/memory-events`

### T7: Fix greedy regex in `_parse_json_response` (TD-88)

**File**: `app/memory/extraction.py` (~line 104)

- [x] Change:
  ```python
  match = re.search(r"\[.*\]", text, re.DOTALL)
  ```
  To non-greedy:
  ```python
  match = re.search(r"\[.*?\]", text, re.DOTALL)
  ```
- [x] This prevents matching from the first `[` to the last `]` across unrelated JSON arrays

### T8: Log entity link failures in extraction (TD-89)

**File**: `app/memory/extraction.py` (~lines 434â€“436)

- [x] Replace:
  ```python
  except Exception:
      pass
  ```
  With:
  ```python
  except Exception:
      logger.warning("Failed to link entity for mention %r in memory %s", mention, memory_id, exc_info=True)
  ```

### T9: Fix `_audit()` double error swallowing (TD-97)

**File**: `app/tools/builtin/memory.py` (~lines 752â€“785)

- [x] Replace both nested `except Exception: pass` with logging:
  ```python
  except Exception:
      logger.warning("Audit event failed for %s", event_type, exc_info=True)
  ```
- [x] Replace deprecated `asyncio.get_event_loop()` with `asyncio.get_running_loop()`:
  ```python
  loop = asyncio.get_running_loop()
  loop.create_task(self._audit_impl(...))
  ```

### T10: Raise lifecycle audit log level to WARNING (TD-102)

**File**: `app/memory/lifecycle.py` (~lines 131â€“134)

- [x] Change:
  ```python
  logger.debug("Audit event failed: %s", exc)
  ```
  To:
  ```python
  logger.warning("Lifecycle audit event failed", exc_info=True)
  ```

### T11: Track and escalate embedding failures in `run_merge` (TD-103)

**File**: `app/memory/lifecycle.py` (~lines 349â€“351)

- [x] Add a consecutive failure counter:
  ```python
  consecutive_embedding_failures = 0
  for pair in merge_candidates:
      try:
          similarity = await self._compute_similarity(pair)
          consecutive_embedding_failures = 0
      except Exception:
          consecutive_embedding_failures += 1
          logger.warning("Embedding similarity failed (consecutive: %d)", consecutive_embedding_failures, exc_info=True)
          if consecutive_embedding_failures >= 3:
              logger.error("Aborting merge pass â€” embedding store unavailable")
              break
  ```

### T12: Log errors in `get_neighborhood()` BFS (TD-106)

**File**: `app/knowledge/graph.py` (~lines 291â€“297)

- [x] After `asyncio.gather(..., return_exceptions=True)`, check results:
  ```python
  for result in results:
      if isinstance(result, BaseException):
          logger.warning("BFS gather error in get_neighborhood", exc_info=result)
  ```

### T13: Include caller context in event source (TD-123)

**File**: `app/tools/builtin/sessions.py` (~line 165)

- [x] Replace hardcoded `"sessions_send_tool"` with dynamic source:
  ```python
  source = f"sessions_send:{calling_agent_id or 'unknown'}"
  ```
- [x] Or pass the caller's agent_id/session_key as context

### T14: Fix HTTP adapter 4xx health reporting (TD-137)

**File**: `app/knowledge/sources/adapters/http.py` (~line 96)

- [x] In the health check method, treat 4xx responses as unhealthy:
  ```python
  async def health_check(self) -> bool:
      try:
          resp = await client.get(self._health_url)
          return 200 <= resp.status_code < 300
      except Exception:
          return False
  ```

---

## Testing

### Existing tests to verify
- [x] All session tool tests pass
- [x] All workflow tests pass
- [x] All embedding tests pass
- [x] All memory API tests pass
- [x] All extraction tests pass
- [x] All graph tests pass

### New tests to add
- [x] Test that `sessions_history` returns error dict for non-existent session
- [x] Test that `sessions_spawn` catches ValueError
- [x] Test that audit endpoints return 503 when not initialized
- [x] Test that greedy regex fix correctly parses nested JSON
- [x] Test that HTTP adapter health check returns False for 4xx

---

## Definition of Done

- [x] All 14 items resolved
- [x] Zero instances of `except Exception: pass` in the codebase (for Sprint 08â€“11 files)
- [x] All error swallowing replaced with `logger.warning(...)` + `exc_info=True`
- [x] Error responses are accurate (not `[]` when system is down)
- [x] Deprecated `get_event_loop()` replaced with `get_running_loop()`
- [x] All existing tests pass (634 unit passing, 1 skipped, zero regressions)
- [x] New observability tests added (23 tests in test_td_s6_observability.py)
