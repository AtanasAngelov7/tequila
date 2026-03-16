# TD-S1 — Security Hardening

**Focus**: Knowledge source attack chain, authentication gaps, error information leakage
**Items**: 9 (TD-43, TD-44, TD-45, TD-46, TD-55, TD-56, TD-66, TD-91, TD-108)
**Severity**: 4 Critical, 3 High, 2 Medium
**Status**: ✅ Complete
**Estimated effort**: ~40 minutes
**Completed**: 2026-03-16 — 505 unit + 202 integration passing (1 pre-existing failure: `test_list_providers`)

---

## Goal

Close the complete attack chain in the knowledge source subsystem (unauthenticated API → SQL injection / SSRF / path traversal) and harden related security gaps across sessions, error responses, and rate limiting.

---

## Items

| TD | Title | Severity | File(s) |
|----|-------|----------|---------|
| TD-43 | SQL injection in pgvector adapter | **Critical** | `app/knowledge/sources/adapters/pgvector.py` |
| TD-44 | SSRF in HTTP knowledge source adapter | **Critical** | `app/knowledge/sources/adapters/http.py` |
| TD-45 | Path traversal in FAISS adapter | **Critical** | `app/knowledge/sources/adapters/faiss.py` |
| TD-46 | Knowledge source API unauthenticated | **Critical** | `app/api/routers/knowledge_sources.py` |
| TD-55 | No schema validation on `connection` config | **High** | `app/knowledge/sources/models.py`, `app/api/routers/knowledge_sources.py` |
| TD-56 | `backend` field not validated | **High** | `app/knowledge/sources/models.py` |
| TD-66 | Session tools have no authorization | **Medium** | `app/tools/builtin/sessions.py` |
| TD-91 | Internal exception details leaked in API responses | **Medium** | `app/api/routers/knowledge_sources.py` |
| TD-108 | No rate limiting on `/api/graph/rebuild` | **Medium** | `app/api/routers/graph.py` |

---

## Tasks

### T1: Add authentication to knowledge source router (TD-46)

**File**: `app/api/routers/knowledge_sources.py`

- [x] Add `dependencies=[Depends(require_gateway_token)]` to the `APIRouter()` constructor
- [x] Verify `require_gateway_token` is imported from `app.api.deps`
- [x] Confirm all 14 endpoints now require auth by checking the router's dependency list

### T2: Validate `backend` field on knowledge source registration (TD-56)

**File**: `app/knowledge/sources/models.py`

- [x] Change `backend: str` to `backend: Literal["chroma", "pgvector", "faiss", "http"]` on the `KnowledgeSource` model (or on the request model in the router)
- [x] Import `Literal` from `typing`
- [x] Invalid backends will now raise a Pydantic validation error at API time

### T3: Add per-backend connection config schemas (TD-55)

**File**: `app/knowledge/sources/models.py`, `app/api/routers/knowledge_sources.py`

- [x] Define Pydantic models for each backend's connection config:
  ```python
  class PgVectorConnectionConfig(BaseModel):
      host: str
      port: int = 5432
      database: str
      user: str
      password: str
      table: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")
      content_col: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")
      emb_col: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")
      meta_cols: list[str] = Field(default_factory=list)

  class HttpConnectionConfig(BaseModel):
      url: HttpUrl
      headers: dict[str, str] = Field(default_factory=dict)

  class FaissConnectionConfig(BaseModel):
      index_path: str
      metadata_path: str | None = None

  class ChromaConnectionConfig(BaseModel):
      collection_name: str
      host: str | None = None
      port: int | None = None
  ```
- [x] In the registration endpoint, validate `connection` against the appropriate schema based on `backend`
- [x] For `meta_cols` in PgVector config, validate each column name matches the identifier regex

### T4: Sanitize SQL identifiers in pgvector adapter (TD-43)

**File**: `app/knowledge/sources/adapters/pgvector.py`

- [x] Add an identifier validation function:
  ```python
  import re
  _IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")

  def _validate_ident(name: str, label: str) -> str:
      if not _IDENT_RE.match(name):
          raise ValueError(f"Invalid SQL identifier for {label}: {name!r}")
      return name
  ```
- [x] Call `_validate_ident()` for `table`, `content_col`, `emb_col`, and each item in `meta_cols` during adapter initialization (in `activate()` or `__init__`)
- [x] This provides defense-in-depth even after TD-55's schema validation

### T5: Add SSRF protection to HTTP adapter (TD-44)

**File**: `app/knowledge/sources/adapters/http.py`

- [x] Add a URL validation function:
  ```python
  import ipaddress
  import socket
  from urllib.parse import urlparse

  _BLOCKED_NETS = [
      ipaddress.ip_network("10.0.0.0/8"),
      ipaddress.ip_network("172.16.0.0/12"),
      ipaddress.ip_network("192.168.0.0/16"),
      ipaddress.ip_network("169.254.0.0/16"),
      ipaddress.ip_network("127.0.0.0/8"),
      ipaddress.ip_network("::1/128"),
  ]

  def _validate_url(url: str) -> str:
      parsed = urlparse(url)
      if parsed.scheme not in ("http", "https"):
          raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
      # Resolve hostname to check for private IPs
      try:
          addr = ipaddress.ip_address(socket.gethostbyname(parsed.hostname or ""))
      except (socket.gaierror, ValueError):
          raise ValueError(f"Cannot resolve hostname: {parsed.hostname}")
      for net in _BLOCKED_NETS:
          if addr in net:
              raise ValueError(f"URL resolves to blocked network: {addr}")
      return url
  ```
- [x] Call `_validate_url()` in `activate()` and before each `client.post()` call
- [x] Wrap `socket.gethostbyname` in `asyncio.to_thread()` since it blocks

### T6: Add path traversal protection to FAISS adapter (TD-45)

**File**: `app/knowledge/sources/adapters/faiss.py`

- [x] Define an allowed data directory constant (e.g., `DATA_DIR = Path("data")`)
- [x] After resolving paths, verify they're within the data directory:
  ```python
  resolved = Path(index_path).resolve()
  allowed = DATA_DIR.resolve()
  if not resolved.is_relative_to(allowed):
      raise ValueError(f"Path {index_path} is outside allowed data directory")
  ```
- [x] Apply the same check to `metadata_path` if present

### T7: Sanitize error responses in knowledge source API (TD-91)

**File**: `app/api/routers/knowledge_sources.py`

- [x] Find all `except` blocks that return `str(e)` or `repr(e)` in HTTP responses
- [x] Replace with generic messages:
  ```python
  except Exception:
      logger.exception("Knowledge source operation failed")
      raise HTTPException(status_code=500, detail="Internal error — check server logs")
  ```
- [x] Ensure SQL errors, connection strings, file paths are never leaked to the client

### T8: Add session policy checks to session tools (TD-66)

**File**: `app/tools/builtin/sessions.py`

- [x] In `sessions_list`, `sessions_history`, `sessions_send`: retrieve the calling agent's session policy
- [x] Before allowing cross-session operations, check `policy.can_send_inter_session` (or equivalent)
- [x] Return a permission error when the policy denies access
- [x] Add a comment documenting the auth model for future reference

### T9: Add concurrency guard to graph rebuild endpoint (TD-108)

**File**: `app/api/routers/graph.py`

- [x] Add a module-level `asyncio.Lock`:
  ```python
  _rebuild_lock = asyncio.Lock()
  ```
- [x] In the rebuild endpoint handler:
  ```python
  if _rebuild_lock.locked():
      raise HTTPException(status_code=429, detail="Rebuild already in progress")
  async with _rebuild_lock:
      result = await graph_store.rebuild_semantic_edges(...)
  ```

---

## Testing

### Existing tests to verify
- [x] All existing knowledge source tests still pass
- [x] All existing session tool tests still pass
- [x] All existing graph API tests still pass

### New tests to add
- [x] Test that knowledge source endpoints return 401/403 without auth token
- [x] Test that invalid `backend` values are rejected (Pydantic validation error)
- [x] Test that SQL-injection-like table names are rejected by pgvector adapter
- [x] Test that private/loopback URLs are rejected by HTTP adapter
- [x] Test that paths outside data directory are rejected by FAISS adapter
- [x] Test that error responses don't contain internal exception details
- [x] Test that concurrent rebuild requests get HTTP 429

---

## Definition of Done

- [x] All 9 items (TD-43, TD-44, TD-45, TD-46, TD-55, TD-56, TD-66, TD-91, TD-108) resolved
- [x] No endpoint in the system is unauthenticated (except `GET /api/health`)
- [x] Knowledge source adapters validate all user-supplied identifiers/paths/URLs
- [x] Error responses contain no internal details (SQL, paths, stack traces)
- [x] All existing tests pass (683+, 1 pre-existing failure)
- [x] New security tests added and passing
