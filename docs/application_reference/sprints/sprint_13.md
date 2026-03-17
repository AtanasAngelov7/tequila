# Sprint 13 — Plugins II: Documents, Browser, MCP & Scheduler

**Phase**: 5 – Plugins & Integrations (II) (**Phase Gate Sprint**)
**Duration**: 2 weeks
**Status**: ✅ Done
**Build Sequence Items**: BS-41, BS-42, BS-43, BS-44, BS-45, BS-46, BS-47

> **📖 Spec reference**: For full design context, data models, and acceptance details, consult [tequila_v2_specification.md](../tequila_v2_specification.md) at the §-sections listed in the Spec References table below.

---

## Goal

Deliver the second wave of plugins: documents (PDF, Office, HTML presentations, CSV, data analysis), browser automation (Playwright), web access polish (additional search providers), MCP (Model Context Protocol) support, pipeline hook plugins, custom plugin auto-discovery, and the scheduler/cron system. By sprint end, the agent can work with documents, create presentations, browse the web, connect to MCP servers, and run scheduled sessions.

---

## Spec References

| Section | Topic |
|---------|-------|
| §8.6 | Built-in plugin catalog — Documents plugin (PDF, Word, Excel, PowerPoint, HTML presentations, CSV/TSV, charts, data analysis) |
| §21.4 | Smart context injection routing (MIME-type → document tool auto-preview) |
| §17.3 | Browser plugin (Playwright-based automation — 25 tools) |
| §17.1 | Additional search providers (Brave, Tavily, Google, Bing, SearXNG) |
| §17.5 | WebPolicy UI |
| §17.6 | Web cache admin |
| §8.6 | Built-in plugin catalog — MCP connectors (external tool servers) |
| §8.0 | Plugin types (pipeline-hook plugin type) |
| §8.7 | Custom plugin auto-discovery (§8.7 Custom Plugin Contract) |
| §7.1–7.3 | Scheduler runtime, API, background agent runs |
| §20.8 | Scheduler & cron isolation (turn contention, deferral, skip) |

---

## Prerequisites

- Requires Sprint 12 deliverables to be completed before this sprint begins.

---

## Deliverables

### D1: Documents Plugin
- `app/plugins/builtin/documents/` — comprehensive document tools:
  - **PDF reading** (PyMuPDF + pymupdf4llm):
    - `pdf_open(path)` → document handle with metadata (pages, title, author)
    - `pdf_read_pages(path, pages?)` → text content (with markdown formatting)
    - `pdf_extract_tables(path, pages?)` → structured tables
    - `pdf_extract_images(path, pages?)` → extracted images (saved to temp)
    - `pdf_page_to_image(path, page)` → rendered page as image (for vision)
    - `pdf_search(path, query)` → search within PDF
  - **PDF manipulation** (pypdf):
    - `pdf_merge(paths)` → merged PDF
    - `pdf_split(path, page_ranges)` → split PDFs
    - `pdf_edit(path, operations)` → rotate, reorder, extract pages
  - **PDF creation** (fpdf2):
    - `pdf_create(content, options?)` → new PDF from text/HTML
    - `pdf_from_markdown(markdown, options?)` → PDF from markdown
  - **PowerPoint** (python-pptx):
    - `pptx_create(slides, theme?)` → new presentation from structured slide specs
    - `pptx_open(path)` → structured data (slide count, text, shapes, images, notes, layout metadata)
    - `pptx_edit(path, operations)` → add/remove/reorder slides, edit text, replace images, update charts
    - `pptx_list_templates()` → list available `.pptx` templates from `data/pptx_templates/`
    - `pptx_from_markdown(markdown, theme?)` → presentation from markdown outline
  - **HTML presentations** (reveal.js — bundled static assets, no pip dependency):
    - `html_presentation_create(slides, theme?)` → self-contained reveal.js `.html` file from structured slide specs (same layouts/themes as PPTX)
    - `html_presentation_from_markdown(markdown, theme?)` → reveal.js HTML from markdown outline
    - `html_presentation_preview(path)` → localhost preview URL with live-reload
  - **Word documents** (python-docx):
    - `docx_create(content)` → Word document from structured content
    - `docx_open(path)` → structured content data
    - `docx_edit(path, operations)` → append/insert/replace sections
    - `docx_from_markdown(markdown)` → Word document from markdown
  - **Spreadsheets** (openpyxl):
    - `xlsx_create(data)` → Excel workbook from structured data
    - `xlsx_open(path)` → sheet names, headers, row data, formulas
    - `xlsx_edit(path, operations)` → add/remove sheets, update cells, add formulas
  - **CSV/TSV** (DuckDB):
    - `csv_open(path)` → schema + preview rows
    - `csv_query(path, sql)` → SQL query on CSV (via DuckDB)
    - `csv_to_xlsx(path)` → convert CSV to Excel
  - **Data analysis**:
    - `data_analyze(path, question?)` → statistical summary, LLM-guided analysis
    - `data_to_chart(path, chart_type, x_col, y_col)` → chart image (matplotlib)
  - **Smart context injection**: on file upload, detect MIME type → auto-call appropriate document tool for preview

**Acceptance**: Agent reads PDFs, creates/edits PowerPoint and Word documents, creates HTML presentations, queries CSVs with SQL, creates charts. MIME-based auto-preview on upload.

### D2: Browser Plugin
- `app/plugins/builtin/browser/` — Playwright-based browser automation:
  - 25 tools including: `browser_launch`, `browser_navigate`, `browser_click`, `browser_type`, `browser_screenshot`, `browser_evaluate`, `browser_wait`, `browser_scroll`, `browser_select`, `browser_fill_form`, etc.
  - Browser profiles: named profiles with persistent cookies/localStorage
  - Vision-based interaction: screenshot → vision model → determine click coordinates
  - Full-mode web_fetch: Playwright-rendered pages (JavaScript-heavy sites)
  - Session management: one browser instance per agent session
  - Configurable: headless/headed, viewport size, timeout
- Dependencies: Playwright (optional install — installed only when plugin enabled)

**Acceptance**: Agent launches browser, navigates, interacts with pages, takes screenshots. Vision-based click works.

### D3: Web Access Polish
- Additional search providers:
  - `app/tools/builtin/web_search_providers/` — provider implementations:
    - Brave Search (API key)
    - Tavily (API key)
    - Google Custom Search (API key)
    - Bing Search (API key)
    - SearXNG (self-hosted, no key)
  - Search provider selector: per-search-type default, user preference
- **WebPolicy UI**: frontend settings for web access:
  - URL blocklist/allowlist
  - Search provider preference
  - Content extraction settings
  - Rate limit configuration
- **Web cache admin**: UI to view cache stats, clear cache, set TTL

**Acceptance**: User can switch search providers. Web policy settings enforced. Cache admin works.

### D4: MCP Plugin Type
- `app/plugins/mcp/` — Model Context Protocol support:
  - MCP client: connect to external MCP servers (stdio, HTTP/SSE transport)
  - Auto-discover tools from MCP server → register in tool registry
  - MCP server config: `{name, transport, url_or_command, auth?}`
  - Tool proxying: agent calls MCP tool → proxy to external server → return result
  - Health check: periodic ping to MCP servers

**Acceptance**: Configure MCP server → tools auto-discovered → agent can call external MCP tools.

### D5: Pipeline Hook Plugin Type
- `app/plugins/hooks/` — hook into agent pipeline:
  - Hook points: `pre_prompt`, `post_prompt`, `pre_tool`, `post_tool`, `pre_response`, `post_response`
  - Hook interface: `async def hook(context: HookContext) → HookResult`
  - Hooks can modify context (e.g., inject content, filter tools, transform response)
  - Priority ordering: hooks execute in declared priority order
  - Example use cases: content filtering, response formatting, custom logging

**Acceptance**: Register hook plugin → hook fires at correct point → can modify context.

### D6: Custom Plugin Auto-Discovery
- `app/plugins/discovery.py` — scan plugin directories for custom plugins:
  - Scan `data/plugins/` directory for Python packages with `__plugin__.py`
  - `__plugin__.py` must export a `PluginBase` subclass
  - Auto-register on startup, honor enable/disable state
  - Hot reload: detect new plugins without restart (file watcher)

**Acceptance**: Drop plugin folder into `data/plugins/` → appears in plugin list → can enable.

### D7: Scheduler & Cron Sessions
- `app/scheduler/` — scheduled task execution:
  - Cron-like scheduling: run agent sessions on schedule
  - `ScheduledTask` model: `name, cron_expression, agent_id, prompt_template, enabled`
  - Task execution: create ephemeral session → inject prompt → agent runs → session archived
  - API:
    - `GET /api/scheduled-tasks` — list tasks
    - `POST /api/scheduled-tasks` — create task
    - `PATCH /api/scheduled-tasks/{id}` — update/disable
    - `DELETE /api/scheduled-tasks/{id}` — remove task
  - Built on `APScheduler` or lightweight cron parser + asyncio scheduling

**Acceptance**: Create scheduled task → fires at cron time → agent executes → results in session history.

---

## Tasks

### Backend — Documents Plugin
- [x] Create `app/plugins/builtin/documents/` package
- [x] Implement PDF reading tools (PyMuPDF + pymupdf4llm)
- [x] Implement PDF manipulation tools (pypdf)
- [x] Implement PDF creation tools (fpdf2)
- [x] Implement PowerPoint tools (python-pptx): create, open, edit, templates, from_markdown
- [x] Implement HTML presentation tools (reveal.js): create, from_markdown, preview — bundle reveal.js assets in `documents/reveal_assets/`
- [x] Implement Word document tools (python-docx): create, open, edit, from_markdown
- [x] Implement Spreadsheet tools (openpyxl): create, open, edit
- [x] Implement CSV/TSV tools (DuckDB for SQL queries)
- [x] Implement data analysis + charting (matplotlib)
- [x] Smart context injection routing (MIME → tool auto-preview)

### Backend — Browser Plugin
- [x] Create `app/plugins/builtin/browser/` package
- [x] Implement core browser tools (launch, navigate, click, type, screenshot)
- [x] Implement advanced tools (evaluate, wait, scroll, form fill)
- [x] Implement browser profiles (persistent cookies)
- [x] Vision-based interaction (screenshot → vision → coordinates)
- [x] Full-mode web_fetch via Playwright

### Backend — Web Access Polish
- [x] Implement additional search providers (Brave, Tavily, Google, Bing, SearXNG)
- [x] Search provider selector in SearchConfig
- [x] URL blocklist/allowlist enforcement

### Backend — MCP
- [x] Create `app/plugins/mcp/client.py` — MCP client
- [x] Implement stdio transport
- [x] Implement HTTP/SSE transport
- [x] Auto-discover tools → register in tool registry
- [x] Health check for MCP servers

### Backend — Pipeline Hooks
- [x] Create `app/plugins/hooks/` — hook framework
- [x] Define hook points (pre/post prompt, tool, response)
- [x] Hook execution engine with priority ordering

### Backend — Plugin Discovery
- [x] Create `app/plugins/discovery.py` — directory scanner
- [x] __plugin__.py convention + auto-register
- [x] File watcher for hot reload

### Backend — Scheduler
- [x] Create `app/scheduler/` — cron scheduling engine
- [x] ScheduledTask model + migration
- [x] Task execution: ephemeral session creation + prompt injection
- [x] Scheduler API endpoints

### Frontend
- [x] Document tools result display (tables, charts, PDF preview)
- [x] Browser session viewer (show screenshots, current URL)
- [x] Web settings page (search provider, web policy, cache admin)
- [x] MCP server configuration UI
- [x] Scheduler UI (task list, create, cron expression builder)

### Tests
- [x] `tests/unit/test_documents_plugin.py` — PDF, PPTX, HTML presentation, DOCX, XLSX, CSV, chart tools (with sample files)
- [x] `tests/unit/test_browser_plugin.py` — tool definitions, profile management
- [x] `tests/unit/test_search_providers.py` — each provider (mocked)
- [x] `tests/unit/test_mcp_client.py` — connect, discover, proxy (mocked)
- [x] `tests/unit/test_hooks.py` — hook registration, execution order
- [x] `tests/unit/test_discovery.py` — scan, register, hot reload
- [x] `tests/unit/test_scheduler.py` — cron parsing, task execution
- [x] `tests/integration/test_plugin_e2e.py` — complete plugin lifecycle

---

## Testing Requirements

- Documents: read PDF → extract tables. Create/edit PPTX. Create HTML presentation from markdown → preview in browser. Create Word doc. Query CSV with SQL. Generate chart. Create PDF from markdown.
- Browser: navigate to page → take screenshot → click element (mocked Playwright).
- MCP: mock MCP server → tools discovered → agent calls tool → result returned.
- Scheduler: create cron task → simulate trigger → session created → agent runs.

---

## Definition of Done

- [x] Documents plugin: PDF (read/manipulate/create), PPTX (create/open/edit/templates), HTML presentations (create/from_markdown/preview), DOCX (create/open/edit), XLSX (create/open/edit), CSV/TSV (open/query/convert), data analysis + charts
- [x] Browser plugin: 25 tools, profiles, vision interaction
- [x] Additional search providers configured and working
- [x] MCP client connects to external servers, proxies tool calls
- [x] Pipeline hooks fire at correct points with priority ordering
- [x] Custom plugin auto-discovery from `data/plugins/`
- [x] Scheduler creates and runs cron-based sessions
- [x] All tests pass
- [x] **Phase 5 gate**: Full plugin ecosystem operational

---

## Risks & Notes

- **7 BS items — very heavy sprint**: Prioritize: Documents → Scheduler → MCP → Browser → Web polish → Hooks → Discovery. If needed, defer browser plugin to early S14.
- **Playwright installation size**: ~150 MB for browser binaries. Install lazily only when browser plugin is enabled.
- **DuckDB for CSV**: Excellent for SQL on CSVs, but adds a dependency (~40 MB). Worth it for the querying power.
- **MCP stability**: MCP protocol is evolving. Pin to a specific spec version. Test with reference MCP servers.
- **Phase gate**: This sprint gates Phase 5. All plugin types (connector, tool, MCP, hook, custom) must be demonstrably working.
