# Sprint 06 — Core Tools: Filesystem, Web Access & Vision

**Phase**: 2 – Agent Core
**Duration**: 2 weeks
**Status**: ✅ Done
**Build Sequence Items**: BS-12, BS-13, BS-14, BS-15

> **📖 Spec reference**: For full design context, data models, and acceptance details, consult [tequila_v2_specification.md](../tequila_v2_specification.md) at the §-sections listed in the Spec References table below.

---

## Goal

Equip the agent with its first real tools: filesystem operations (read, write, list, search), code execution, web search, web fetch with content extraction, and vision capabilities. By sprint end the agent can autonomously read/write local files, search the web, extract content from URLs, and describe images.

---

## Spec References

| Section | Topic |
|---------|-------|
| §16.1 | Filesystem concepts (path policy, sandboxing) |
| §16.2 | Working directory model |
| §16.3 | Filesystem tools (fs_list_dir, fs_read_file, fs_write_file, fs_search) |
| §16.7 | Code execution tool (code_exec) |
| §17.1 | Web search tool (web_search, DuckDuckGo default, SearchConfig) |
| §17.2 | Web fetch tool (web_fetch, httpx + trafilatura, content extraction pipeline) |
| §17.4 | Vision pipeline & tools (vision_describe, vision_extract_text, vision_compare, vision_analyze) |
| §17.6 | Web cache table |

---

## Prerequisites

- Requires Sprint 05 deliverables to be completed before this sprint begins.

---

## Deliverables

### D1: Filesystem Tools
- `app/tools/builtin/filesystem.py` — register tools:
  - `fs_list_dir(path, recursive?, pattern?)` → directory listing
  - `fs_read_file(path, start_line?, end_line?)` → file content (with line range support)
  - `fs_write_file(path, content, mode: "create"|"overwrite"|"append")` → written file path
  - `fs_search(pattern, path?, max_results?)` → matching files (glob + ripgrep if available)
- Working directory: configurable per session, defaults to user home
- Path policy: `allowed_roots` whitelist, deny absolute paths outside roots, deny `..` traversal above root
- Safety: `fs_read_file`, `fs_list_dir`, `fs_search` = `read_only`; `fs_write_file` = `side_effect`

**Acceptance**: Agent can list, read, write, and search files within allowed paths. Paths outside policy are rejected.

### D2: Code Execution Tool
- `app/tools/builtin/code_exec.py` — `code_exec(language, code, timeout_s?)`:
  - Runs in sandboxed subprocess (`subprocess.run` with resource limits)
  - Captures stdout, stderr, exit code
  - Primary language: Python (detects user's interpreter)
  - Timeout: configurable, default 30 seconds
  - Safety: `destructive` (requires approval by default)
- Returns: `{stdout, stderr, exit_code, runtime_ms}`

**Acceptance**: Agent can execute Python code, get output. Timeout kills runaway processes. Approval required.

### D3: Web Search Tool
- `app/tools/builtin/web_search.py` — `web_search(query, max_results?, search_type?)`
  - Default provider: DuckDuckGo (duckduckgo-search library, no API key)
  - `SearchConfig` model: default_provider, max_results, safe_search
  - Search provider registry: extensible for future providers (Brave, Tavily, etc.)
  - Search types: `general`, `news`, `academic`
  - Safety: `read_only`
- Returns: `[{title, url, snippet, source}]`

**Acceptance**: Agent searches DuckDuckGo, returns structured results. Provider is swappable.

### D4: Web Fetch Tool
- `app/tools/builtin/web_fetch.py` — `web_fetch(url, extract_mode?)`
  - HTTP fetch via `httpx` (async, timeout 30s, respect robots.txt)
  - Content extraction: `trafilatura` (light mode — main article text, strip boilerplate)
  - Extract modes: `article` (default, trafilatura), `raw_html`, `markdown`
  - HTML → markdown conversion via `html2text` or `markdownify`
  - Content truncation: configurable max chars (default 50,000)
  - Safety: `read_only`
- `web_cache` table: URL → extracted content, TTL (default 1 hour), ETag/Last-Modified

**Acceptance**: Agent fetches URL, extracts clean article text. Cached results served on repeat fetch within TTL.

### D5: Vision Pipeline & Tools
- `app/tools/builtin/vision.py` — vision tools:
  - `vision_describe(image_source)` — natural language description of image
  - `vision_extract_text(image_source)` — OCR/text extraction from image
  - `vision_compare(image_sources[])` — compare multiple images
  - `vision_analyze(image_source, question)` — answer a question about an image
- `VisionConfig`: default model, max image size, auto-resize settings
- Image sources: local file path, URL, base64, clipboard
- Provider integration: route to vision-capable model (detected via ModelCapabilities from S04)
- Image preprocessing: resize if > max dimensions, format conversion

**Acceptance**: Agent describes images, extracts text, compares, answers questions. Vision model auto-selected.

### D6: Web Cache
- `app/storage/web_cache.py` — SQLite table for caching web fetch results
- Schema: `url, content, content_type, fetched_at, ttl_s, etag, last_modified`
- Cache hit: return stored content if within TTL; conditional GET with ETag if expired
- Cleanup: periodic purge of expired entries

**Acceptance**: Repeated web_fetch for same URL within TTL returns cached content. Expired entries cleaned.

---

## Tasks

### Backend — Filesystem
- [x] Create `app/tools/builtin/filesystem.py` with all 4 tools
- [x] Implement path policy engine (allowed_roots, traversal protection)
- [x] Add working directory per-session config
- [x] Register tools with correct safety classifications

### Backend — Code Execution
- [x] Create `app/tools/builtin/code_exec.py`
- [x] Implement subprocess sandbox with timeout and resource limits
- [x] Auto-detect Python interpreter path
- [x] Register as `destructive` safety level

### Backend — Web Search
- [x] Create `app/tools/builtin/web_search.py`
- [x] Implement DuckDuckGo provider using `duckduckgo-search`
- [x] Create SearchConfig model
- [x] Create search provider registry for extensibility

### Backend — Web Fetch
- [x] Create `app/tools/builtin/web_fetch.py`
- [x] Implement httpx fetch with timeout, redirect handling
- [x] Integrate trafilatura for article extraction
- [x] Add html2text/markdownify for markdown mode
- [x] Content truncation at configurable max chars
- [x] Create web_cache table + migration
- [x] Implement cache lookup, conditional GET

### Backend — Vision
- [x] Create `app/tools/builtin/vision.py` with all 4 tools
- [x] Implement VisionConfig model
- [x] Image preprocessing (resize, format normalisation)
- [x] Multi-source input handling (file, URL, base64, clipboard)
- [x] Route to vision-capable model via ModelCapabilities

### Frontend
- [ ] Tool result display: file listing, code output, search results, fetched content *(deferred — frontend sprint)*
- [ ] Image preview for vision tools in chat *(deferred — frontend sprint)*
- [ ] Code execution output formatting *(deferred — frontend sprint)*

### Tests
- [x] `tests/unit/test_filesystem_tools.py` — read, write, list, search, path policy (21 tests)
- [x] `tests/unit/test_code_exec.py` — execution, timeout, safety (11 tests)
- [x] `tests/unit/test_web_search.py` — DuckDuckGo mock, provider registry (11 tests)
- [x] `tests/unit/test_web_fetch.py` — fetch, extraction, caching (17 tests)
- [x] `tests/unit/test_vision.py` — image preprocessing, tool routing (14 tests)
- [x] `tests/integration/test_agent_tools.py` — agent uses tools end-to-end (5 tests)

---

## Testing Requirements

- Filesystem: read/write/list in allowed path. Write outside path → error. Traversal attack → blocked.
- Code exec: simple script returns stdout. Infinite loop → timeout. Approval required.
- Web search: DuckDuckGo mock returns structured results.
- Web fetch: mock HTTP → trafilatura extraction → clean text. Cache hit on repeat.
- Vision: mock vision model response for describe/extract/compare/analyze.

---

## Definition of Done

- [x] Agent uses filesystem tools within path policy (violations rejected)
- [x] Code execution runs sandboxed Python, captures output, respects timeout
- [x] Web search returns structured results from DuckDuckGo
- [x] Web fetch extracts clean content, caches results
- [x] Vision tools describe/extract/compare/analyze images
- [x] All tools registered with correct safety levels
- [x] All tests pass — **328 total (80 new in Sprint 06), 0 failures**

---

## Risks & Notes

- **File tracking deferred**: Filesystem tools in this sprint create and manipulate files on disk, but formal file tracking (`session_files` table, file cards in chat, file cleanup) is not built until Sprint 15. For now, files are referenced by path only. Do not build a file tracking system in this sprint — it will be implemented later.
- **trafilatura quality**: Article extraction quality varies by site. May need fallback to raw markdown mode. Test with diverse URLs.
- **Vision model availability**: Not all providers support vision. Graceful error if no vision-capable model configured.
- **Code exec security**: Even with subprocess isolation, code_exec is inherently risky. Keep approval gate mandatory for now; evaluate tighter sandboxing (Docker, nsjail) later.
- **DuckDuckGo rate limits**: The duckduckgo-search library uses scraping; rate limits may apply. Consider exponential backoff.
