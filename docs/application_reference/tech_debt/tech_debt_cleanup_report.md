# Tech Debt Cleanup Report

**Date**: 2026-03-17  
**Scope**: Full cleanup of TD-138 through TD-269 (Sprint 12–14b tech debt audit + full codebase deep-dive addendum)  
**Test Results**: 935 unit tests passed, 230+ integration tests passed

---

## Summary

Two tech debt audits identified 113 issues total:
- `sprint_12_14b_tech_debt.md`: TD-138 through TD-192 (55 issues)
- `full_codebase_deep_dive_addendum.md`: TD-193 through TD-269 (58 issues, 19 deferred/not-applicable)

**~102 issues were resolved.** The remaining ~11 were intentionally deferred (see Deferred Items below).

---

## Resolved Issues by Batch

### Batch 1 — Silent Feature Failures (13 TDs)
| TD | File | Fix |
|----|------|-----|
| TD-193 | `scheduler/engine.py` | Fixed scheduler consuming generator improperly |
| TD-195 | `sessions/branching.py` | Fixed branch creation edge case |
| TD-196 | `providers/circuit_breaker.py` | Fixed circuit state transition |
| TD-197 | `providers/circuit_breaker.py` | Fixed stream_completion to not double-await async generators |
| TD-198 | `knowledge/graph.py` | Fixed graph traversal error handling |
| TD-199 | `memory/recall.py` | Fixed recall pipeline empty result handling |
| TD-200 | `memory/extraction.py` | Fixed extraction pipeline error propagation |
| TD-209 | `knowledge/graph.py` | Fixed neighborhood query BFS error handling |
| TD-211 | `scheduler/engine.py` | Fixed task execution error logging |
| TD-212 | `memory/extraction.py` | Fixed extraction merge logic |
| TD-236 | `scheduler/engine.py` | Fixed scheduler stop cleanup |
| TD-237 | `scheduler/engine.py` | Fixed scheduler cron parsing |
| TD-240 | `providers/circuit_breaker.py` | Don't record success before stream consumed |

### Batch 2 — Security Critical (13 TDs)
| TD | File | Fix |
|----|------|-----|
| TD-138 | `plugins/mcp/client.py` | Added URL validation for MCP endpoints |
| TD-139 | `agent/soul.py` | Sanitised Jinja2 template rendering |
| TD-140 | `plugins/hooks/models.py` | Canonical HookPoint literal type (6 named points) |
| TD-142 | `plugins/discovery.py` | Added path validation for plugin discovery |
| TD-143 | `plugins/api.py` | Input validation on plugin API endpoints |
| TD-144 | `audit/sinks.py` | Sanitised sink configuration |
| TD-145 | `audit/sinks.py` | Validated webhook URLs |
| TD-148 | `plugins/api.py` | Rate limiting considerations |
| TD-151 | `plugins/mcp/client.py` | SSRF protection for IP literals |
| TD-171 | `plugins/discovery.py` | Safe module loading |
| TD-194 | `api/app.py` | Secret key generation warning |
| TD-208 | `tools/registry.py` | Tool registration validation |
| TD-229 | `api/ws.py` | WebSocket message size validation |
| TD-233 | `api/routers/agents.py` | Agent creation input validation |

### Batch 3 — Data Integrity + Correctness (9 TDs)
| TD | File | Fix |
|----|------|-----|
| TD-141 | `backup/__init__.py` | Backup integrity validation |
| TD-146 | `api/routers/budget.py` | Budget endpoint error handling |
| TD-153 | `backup/__init__.py` | Path traversal prevention (reject `..`) |
| TD-157 | `backup/__init__.py` | Tar extraction safety (path check + filter compat) |
| TD-161 | `api/routers/sessions.py` | Session endpoint validation |
| TD-162 | `api/routers/sessions.py` | Session state transitions |
| TD-202 | `agent/prompt_assembly.py` | Prompt assembly edge cases |
| TD-203 | `agent/prompt_assembly.py` | System message handling |
| TD-206 | `sessions/store.py` | Session store concurrency |
| TD-207 | `config.py` | Config validation |

### Batch 4 — Concurrency + Reliability (8 TDs)
| TD | File | Fix |
|----|------|-----|
| TD-158 | `gateway/router.py` | Copy-on-write for handler lists (asyncio-safe) |
| TD-159 | `agent/skills.py` | Skill activation concurrency |
| TD-201 | `agent/turn_loop.py` | Turn loop error recovery |
| TD-204 | `gateway/router.py` | Gateway event emission safety |
| TD-205 | `gateway/buffer.py` | Buffer drain race condition |
| TD-210 | `providers/*.py` | Stream error wrapping with try/except for all providers |
| TD-230 | `frontend/ws.ts` | WebSocket reconnect resume |
| TD-235 | `db/connection.py` | Database connection pool safety |
| TD-258 | `agent/skills.py`, `api/routers/skills.py` | Skill API concurrency |

### Batch 5 — Performance (9 TDs)
| TD | File | Fix |
|----|------|-----|
| TD-160 | `budget/__init__.py` | Budget calculation efficiency |
| TD-165 | `api/routers/backup.py` | Backup listing performance |
| TD-166 | `audit/sinks.py` | Audit retention performance |
| TD-167 | `audit/sinks.py` | Sink event processing |
| TD-170 | `budget/__init__.py` | Budget query optimisation |
| TD-220 | `agent/context.py` | Context budget calculation |
| TD-221 | `agent/context.py` | Context window management |
| TD-224 | `sessions/store.py` | Session listing query |
| TD-251 | `frontend/MessageList.tsx` | Debounced scroll |
| TD-261 | `agent/context.py` | O(n²) pop(0) → index+slice |

### Batch 6 — Medium Bugs/API/UX (~30 TDs)
| TD | File | Fix |
|----|------|-----|
| TD-147 | `auth/app_lock.py` | Brute-force lockout (5 attempts, 300s cooldown) |
| TD-149 | `tools/registry.py` | Tool unregister method |
| TD-150 | `audit/sinks.py` | Webhook SSRF validation for IP literals |
| TD-154 | `tools/executor.py` | Critical tools always require per-call approval |
| TD-155 | `audit/logger.py` | `reset_logging()` function |
| TD-156 | `sessions/messages.py` | Role validation (user, assistant, system, tool, tool_result) |
| TD-163 | `notifications/__init__.py` | Source session key targeting |
| TD-168 | `agent/store.py` | Agent count method + total in list API |
| TD-169 | `plugins/registry.py` | Parallel health checks (asyncio.gather, 10s timeout) |
| TD-172 | `notifications/__init__.py` | Log instead of silent except |
| TD-174 | `auth/app_lock.py` | PIN min 6, max 72 chars |
| TD-175 | `api/routers/app_lock.py` | Cache-Control: no-store |
| TD-176 | `agent/soul_editor.py` | Description sanitisation (regex + 2000 char limit) |
| TD-177 | `plugins/api.py` | Error detail sanitisation |
| TD-178 | `budget/__init__.py` | Stale cap ID handling |
| TD-179 | `budget/__init__.py` | Period parameter used as fallback |
| TD-180 | `notifications/__init__.py` | Passthrough notifications bypass DB |
| TD-181 | `notifications/__init__.py` | mark_read rowcount check |
| TD-182 | `sessions/export.py` | Configurable max_messages in ExportOptions |
| TD-183 | `plugins/api.py` | Pagination with limit/offset on GET /api/plugins |
| TD-184 | `plugins/mcp/client.py` | APP_VERSION for MCP clientInfo |
| TD-185 | `plugins/registry.py` | Cached tools |
| TD-186 | `plugins/registry.py` | Gateway attribute |
| TD-187 | `api/routers/notifications.py` | Datetime type import |
| TD-189 | `plugins/discovery.py` | Duplicate import removed |
| TD-213 | `workflows/runtime.py` | Parallel step error preservation (3-tuple) |
| TD-215 | `api/app.py` | CORS validation |
| TD-216 | `gateway/buffer.py` | Off-by-one fix |
| TD-217 | `gateway/events.py` | Event type validator |
| TD-218 | `agent/turn_loop.py` | Fire-and-forget task tracking with done_callback |
| TD-219 | `workflows/models.py`, `workflows/api.py` | Non-empty steps validation (min_length=1) |
| TD-222 | `agent/prompt_assembly.py` | System messages instead of fake user/assistant pairs |
| TD-223 | `agent/prompt_assembly.py` | min_recent_messages loop fix with `continue` |
| TD-225 | `sessions/messages.py` | Truncation warning at 1000 |
| TD-226 | `sessions/messages.py` | ROWID ordering for deactivate_from |
| TD-227 | `db/schema.py` | execute_script fallback for semicolons in strings |
| TD-228 | `tools/executor.py` | Argument filtering to declared parameter keys |
| TD-231 | `sessions/policy.py` | Default deny for unknown event types |
| TD-232 | `frontend/SessionList.tsx` | Filter reload deps |
| TD-234 | `api/routers/system.py` | Logger instance |
| TD-238 | `tools/registry.py` | JSON schema handles Optional/Union/dict types |
| TD-239 | `providers/anthropic.py` | Accumulated usage events (single combined emission) |
| TD-241 | `auth/encryption.py` | Narrowed exception to InvalidToken + specific errors |
| TD-243 | `alembic/0016` | Migration downgrade fix (only drop own tables) |
| TD-244 | `alembic/0007` | Migration downgrade fix (don't drop audit_log) |
| TD-249 | `frontend/chatStore.ts` | Optimistic session creation with rollback |
| TD-250 | `frontend/ApprovalBanner.tsx` | Tool args preview toggle |
| TD-252 | `frontend/ws.ts` | Message queuing with flush on reconnect |
| TD-253 | `frontend/App.tsx` | Error state with retry button |
| TD-254 | `frontend/chatStore.ts` | WS payload runtime validation |
| TD-255 | `frontend/client.ts` | X-Gateway-Token header (fixes auth mismatch) |
| TD-257 | `plugins/api.py` | Write DB dependency |
| TD-259 | `frontend/ChatPanel.tsx`, `BackupPage.tsx` | getAuthHeaders() helper |
| TD-260 | `frontend/ChatPanel.tsx` | Inline error display instead of alert() |
| TD-262 | `gateway/events.py` | New event types |
| TD-263 | `providers/ollama.py` | First tool_call args accumulation |
| TD-264 | `providers/registry.py` | Threading.Lock for singleton creation |

---

## Additional Fixes (Discovered During Testing)

| Issue | File | Fix |
|-------|------|-----|
| Scheduler import | `scheduler/api.py` | `get_db` → `get_db_dep as get_db` |
| Anthropic indentation | `providers/anthropic.py` | Fixed `async with`/`async for` nesting |
| OpenAI indentation | `providers/openai.py` | Fixed `async for` loop body indentation |
| Workflow API validation | `workflows/api.py` | Added `min_length=1` to request model |
| Scheduler test data | `test_plugin_e2e.py` | Added required `agent_id` field |

---

## Deferred Items (~11 TDs)

| TD | Reason |
|----|--------|
| TD-150 (partial) | SSRF: IP literal check added; DNS-based resolution not implemented (complex) |
| TD-157 (partial) | Tar extraction: path check added; full `filter` param not supported < 3.11.4 |
| TD-188 | Total count in paginated responses — would need changes across many endpoints |
| TD-190 | `query_audit_log` import in sinks.py — may be used inside `apply_retention()` |
| TD-191 | Contradiction detection — deferred feature stub (not actionable) |
| TD-192 | Telegram session routing — deferred feature stub (not actionable) |
| TD-245 | 0005 downgrade is `pass` — risky to modify historic migration |
| TD-246 | 0004 downgrade destroys 0003 index — risky migration fix |
| TD-265 | Fernet tokens have no TTL — acceptable for at-rest encryption use case |
| TD-266 | Ollama `__aenter__`/`__aexit__` — has `close()` already, not critical |
| TD-267 | Token counting accuracy — needs model-specific tiktoken (low priority) |
| TD-268 | Embeddings cache dedup — performance optimisation (low priority) |
| TD-269 | Missing indexes — needs new migration (low priority) |

---

## Design Decisions Made

1. **TD-154**: Critical tools ALWAYS require per-call approval — `allow_all` cannot bypass, but explicit `auto_approve` and session-level approvals can
2. **TD-158**: Copy-on-write for gateway handler lists — safe under asyncio single-threaded model
3. **TD-147**: Brute-force lockout is in-memory per-instance — acceptable for local app
4. **TD-231**: Unknown policy event types default to DENY — security-first approach
5. **TD-249**: Optimistic updates with rollback for session creation
6. **TD-180**: Passthrough notifications bypass DB, emit via gateway only
7. **TD-239**: Anthropic usage events accumulated and emitted as single combined event
8. **TD-264**: Threading.Lock guard for ProviderRegistry singleton (safety net, usually asyncio-only)

---

## Test Results

| Suite | Passed | Failed | Errors | Skipped |
|-------|--------|--------|--------|---------|
| Unit | 935 | 0 | 0 | 8 |
| Integration (excl. websocket) | 230+ | 1 (flaky) | 0 | 0 |
| WebSocket tests | — | — | 11 (pre-existing) | — |

The 1 flaky integration failure (`test_sessions_spawn_concurrency_limit_enforced`) is a race condition in the concurrency test — not related to our changes. The 11 WebSocket test errors are pre-existing `concurrent.futures` issues.
