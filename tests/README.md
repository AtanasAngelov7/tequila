# Tests — Developer Guide

**Updated**: March 16, 2026

---

## Running tests

```powershell
# Unit suite only (~6 s)
.venv\Scripts\python.exe -m pytest tests/unit/ -q

# Integration suite only (~30–60 s — starts the full FastAPI app)
.venv\Scripts\python.exe -m pytest tests/integration/ -q

# Full suite
.venv\Scripts\python.exe -m pytest tests/ -q
```

All tests are async-aware (`asyncio_mode = "auto"` in `pyproject.toml`).
No `@pytest.mark.asyncio` decorator is needed on individual tests.

---

## Test infrastructure — fixtures

All shared fixtures live in [`tests/conftest.py`](conftest.py).

### `migrated_db` (function-scoped)

Yields an `aiosqlite.Connection` connected to a fresh, fully-migrated SQLite
database. Each test that uses this fixture gets its own **isolated copy** of
the database — writes in one test never affect another.

**How it works (Golden DB pattern):**

A session-scoped helper fixture (`_golden_db_bytes`) runs `alembic upgrade head`
**once** at the start of the pytest session. Every `migrated_db` call then
copies those bytes into a new temp file instead of re-running all migrations.

```
pytest session starts
  └─ _golden_db_bytes: alembic upgrade head → ~164 ms (once)
       └─ test_db_path: write_bytes(golden)  → <1 ms (per test)
            └─ migrated_db: open connection  → per test
```

This reduced the unit suite from **38 s → ~6 s** (6.7×) with zero change to
individual tests.

### `test_db_path` (function-scoped)

Returns a `Path` pointing to the per-test DB file, pre-populated with the
migrated schema. Use this instead of `migrated_db` if you need the raw file
path only (e.g., to pass to `startup()` directly).

### `config_store` (function-scoped)

Returns a hydrated `ConfigStore` backed by `migrated_db`. Requires the
`migrated_db` fixture.

### `test_gateway` (function-scoped)

Returns a fresh `GatewayRouter` (not the process-level singleton). Does **not**
require a database.

### `test_app` (function-scoped)

Returns an `httpx.AsyncClient` pointed at a running FastAPI app (via
`asgi-lifespan`). Used for end-to-end integration tests. The app's lifespan
runs `alembic upgrade head` as a subprocess — since `test_db_path` already
provides a fully-migrated file, this is a fast no-op.

---

## Adding a new Alembic migration

No special steps are needed for tests.

1. Create your migration in `alembic/versions/`.
2. Run `alembic upgrade head` locally to verify it.
3. Re-run the test suite — `_golden_db_bytes` always runs `alembic upgrade head`
   fresh at the start of each session, so it will automatically include your new
   migration.

**No test code needs to change** when a migration is added.

---

## Adding a new test

### Unit test (no DB needed)

Place the file in `tests/unit/`. Just write an `async def test_*` function.

### Unit test (requires DB)

```python
async def test_something(migrated_db):
    # migrated_db is a ready-to-use aiosqlite.Connection
    ...
```

### Integration test

Place the file in `tests/integration/`. Use the `test_app` fixture:

```python
async def test_something(test_app):
    response = await test_app.get("/api/health")
    assert response.status_code == 200
```

---

## Environment variables managed by fixtures

The following environment variables are set and cleaned up automatically by
fixtures — **do not set them in individual tests**:

| Variable | Set by | Purpose |
|----------|--------|---------|
| `TEQUILA_DATA_DIR` | `_golden_db_bytes`, `migrated_db`, `test_app` | Points `db_path()` / `data_dir()` at the temp directory |

---

## Known issues

| Test | Status | Notes |
|------|--------|-------|
| `test_list_providers` (integration) | Pre-existing failure | Provider registry singleton state leaks between test sessions; not introduced by any TD sprint |
