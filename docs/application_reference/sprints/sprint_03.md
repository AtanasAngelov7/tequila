# Sprint 03 — Setup Wizard, Health Dashboard & Session UX

**Phase**: 1 – Foundation
**Duration**: 2 weeks
**Status**: ⬜ Not Started
**Build Sequence Items**: BS-5b, BS-5c, BS-5d

> **📖 Spec reference**: For full design context, data models, and acceptance details, consult [tequila_v2_specification.md](../tequila_v2_specification.md) at the §-sections listed in the Spec References table below.

---

## Goal

Complete the foundation phase with the first-run setup wizard, health/status endpoints with frontend integration, session title auto-generation, and session search & filtering. By sprint end, a fresh install guides the user through provider setup and the session list is fully functional with search and filters.

---

## Spec References

| Section | Topic |
|---------|-------|
| §3.2 | Session title auto-generation, summary |
| §9.5 | Session search & filtering |
| §13.3 | Health & status endpoints |
| §15.1 | First-run setup wizard |
| §15.2 | Startup / initialization sequence |

---

## Prerequisites

- Requires Sprint 02 deliverables to be completed before this sprint begins.

---

## Deliverables

### D1: First-Run Setup Wizard
- `POST /api/setup` endpoint — detects first run (no config / no agents)
- Setup flow: 
  1. Welcome screen
  2. Provider selection (OpenAI / Anthropic / Ollama / API key)
  3. API key or OAuth entry + validation
  4. Model selection (list available models from chosen provider)
  5. Main agent creation (name, optional persona customization)
  6. Done → redirect to chat
- `frontend/src/pages/SetupWizard.tsx` — multi-step wizard UI
- Auto-redirect: on first load, if no setup complete → show wizard

**Acceptance**: Fresh database → browser shows setup wizard → user enters API key → main agent created → chat ready.

### D2: Health & Status Endpoints
- `GET /api/health` — lightweight liveness probe (200 OK, uptime, version)
- `GET /api/status` — full system status dashboard (`SystemStatus` model §13.3)
  - Provider status (available, circuit state — stub)
  - Plugin status (stub — no plugins yet)
  - DB size, WAL size
  - Active session/turn counts
  - Scheduler status (stub)
- Frontend: connection status indicator (green/yellow/red) in top bar
- `frontend/src/pages/DiagnosticsPage.tsx` — system status panel (reads `/api/status`)

**Acceptance**: `/api/health` returns 200 with version. `/api/status` returns full dashboard data. Frontend shows connection status.

### D3: Session Title & Rename
- New sessions start with default title "New Session"
- Manual rename: `PATCH /api/sessions/{id}` with `{"title": "..."}`
- Channel/cron sessions: default title from channel + sender or job name
- Title field in session model, editable via API and frontend inline edit
- **Deferred to Sprint 04**: LLM-based title auto-generation (after first exchange), title re-generation on topic shift, and periodic summary generation. These features require the full provider abstraction built in S04.

**Acceptance**: New session starts as "New Session". Manual rename works via API and inline edit. Channel sessions have descriptive default titles.

### D4: Session Search & Filtering
- Session sidebar search bar with debounced FTS across title, summary, agent name (§9.5)
- Filter controls: status (active/idle/archived/all), kind (user/channel/cron/etc.), agent dropdown, date range
- Sort options: last activity, created, message count, title A-Z
- `GET /api/sessions` extended with `q`, `status`, `kind`, `agent_id`, `sort`, `order`, `limit`, `offset` params
- Filter state stored in Zustand (ephemeral, not persisted to server)

**Acceptance**: User can search sessions by title. Filters narrow the list. Sort changes ordering.

### D5: Startup Sequence Hardening
- Startup initialization order (§15.2): DB check → migrations → config load → gateway init → plugin scan (stub) → scheduler start (stub)
- Pre-migration backup trigger (stub — actual backup in S14)
- Graceful error handling if DB is locked or corrupt

**Acceptance**: Server starts cleanly from empty state. Handles missing DB gracefully (creates it).

---

## Tasks

### Backend — Setup Wizard
- [ ] Create `POST /api/setup` endpoint — first-run detection, validation
- [ ] Implement provider validation: test API key, list models
- [ ] Implement main agent auto-creation from wizard input
- [ ] Add `setup_complete` flag to config table

### Backend — Health & Status  
- [ ] Extend `app/api/routers/system.py` — `/api/health` (lightweight), `/api/status` (full)
- [ ] Create `SystemStatus`, `ProviderStatus`, `PluginStatus` response models
- [ ] Collect DB stats (file size, WAL size)
- [ ] Collect active session / turn counts

### Backend — Session UX
- [ ] Implement default title ("New Session") + manual rename via `PATCH /api/sessions/{id}`
- [ ] Implement channel/cron default titles (channel + sender, job name)
- [ ] Extend `GET /api/sessions` with search, filter, sort parameters
- [ ] Add FTS support for session search (title + summary)

### Backend — Startup
- [ ] Implement startup initialization sequence in lifespan handler
- [ ] Add error handling for corrupt/missing DB
- [ ] Add startup log output (version, config summary, DB path, provider status)

### Frontend — Setup Wizard
- [ ] Create `SetupWizard.tsx` — multi-step form
- [ ] Provider selection step (cards for OpenAI, Anthropic, Ollama, API key)
- [ ] API key entry + real-time validation indicator
- [ ] Model selection step (dropdown populated from API)
- [ ] Agent creation step (name, optional persona)
- [ ] Auto-redirect logic: check setup status on app load

### Frontend — Session UX
- [ ] Add search bar to session sidebar with debounce
- [ ] Add filter bar (status, kind, agent, date range dropdowns)
- [ ] Add sort dropdown (last activity, created, message count, title)
- [ ] Highlight matching text in search results
- [ ] Store filter/sort state in Zustand

### Frontend — Health
- [ ] Add connection status indicator to top bar
- [ ] Create DiagnosticsPage with system status panel
- [ ] Add route: `/diagnostics`

### Tests
- [ ] `tests/integration/test_setup_wizard.py` — first-run flow, validation, agent creation
- [ ] `tests/integration/test_api_sessions.py` — search, filter, sort params
- [ ] `tests/unit/test_session_title.py` — default title, manual rename, channel/cron defaults
- [ ] Frontend tests for wizard step navigation

---

## Testing Requirements

- Setup wizard: fresh DB → wizard completes → agent exists → chat functional.
- Session search: queries return matching sessions, filters narrow results.
- Health endpoint: returns correct structure and live data.

---

## Definition of Done

- [ ] Fresh install shows setup wizard, completes successfully
- [ ] After setup, user lands in chat with a working main agent
- [ ] Session titles: default "New Session", manual rename works, channel/cron default titles set
- [ ] Session sidebar: search, filter by status/kind/agent, sort by 4 criteria
- [ ] `/api/health` and `/api/status` return correct data
- [ ] Connection status indicator shows green when connected
- [ ] All tests pass
- [ ] **Phase 1 gate**: full foundation demoable — start → setup → chat → session management

---

## Risks & Notes

- **FTS for sessions**: Consider adding a `sessions_fts` virtual table now, or implement simple `LIKE` search and upgrade to FTS5 in S09 when the search system is built.
