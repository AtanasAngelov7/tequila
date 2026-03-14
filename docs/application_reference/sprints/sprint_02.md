# Sprint 02 — Sessions, WebSocket & React Shell

**Phase**: 1 – Foundation
**Duration**: 2 weeks
**Status**: ⬜ Not Started
**Build Sequence Items**: BS-4, BS-5, BS-5a

> **📖 Spec reference**: For full design context, data models, and acceptance details, consult [tequila_v2_specification.md](../tequila_v2_specification.md) at the §-sections listed in the Spec References table below.

---

## Goal

Implement the session model with full CRUD and lifecycle, the WebSocket endpoint with reconnection support, and the initial React frontend shell. By sprint end, a user can open the browser, see a chat UI, create a session, and send/receive messages over WebSocket (echoed, no LLM yet).

---

## Spec References

| Section | Topic |
|---------|-------|
| §2.4 | Plugins (replaces channel adapters — webchat is built-in) |
| §2.5 | Wire protocol (typed JSON frames) |
| §2.5a | WS reconnection, event buffer, heartbeat |
| §2.6 | Skip list |
| §2.7 | Session policy presets |
| §3.1 | Session key format |
| §3.2 | Session record model |
| §3.7 | Session lifecycle (active → idle → archived) |
| §9.1 | Frontend architecture (React, Zustand, TanStack Query) |
| §9.3 | Theming (dark/light/system) |
| §9.4 | Keyboard shortcuts |
| §13.2 | WebSocket endpoint |
| §20.3 | Atomic updates & state transitions (session lifecycle) |
| §20.4 | Idempotency (WebSocket frame dedup) |
| §20.6 | Turn queuing |

---

## Prerequisites

- Requires Sprint 01 deliverables to be completed before this sprint begins.

---

## Deliverables

### D1: Session Store & CRUD
- `app/sessions/models.py` — Session Pydantic model (§3.2: key, agent_id, kind, status, title, summary, policy, timestamps)
- `app/sessions/store.py` — Session CRUD (create, list, get, update, delete, archive)
- Session lifecycle state machine: `active → idle → archived`
- Idle detection timer (configurable, default 7 days)
- `app/api/routers/sessions.py` — full REST API

**Acceptance**: Sessions can be created, listed, updated, archived, and deleted via REST API.

### D2: Message Store
- `app/sessions/models.py` (extended) — `Message` model stub (§3.4: id, session_id, role, content, timestamps). Full model in S05.
- Messages table CRUD: insert, list by session, paginate
- `app/api/routers/messages.py` — `GET /api/sessions/{id}/messages`, `POST /api/sessions/{id}/messages`

**Acceptance**: Messages can be posted to a session and retrieved via API.

### D3: WebSocket Endpoint
- `app/api/ws.py` — WebSocket handler
- Connect handshake: session create/resume via WS frame
- Typed JSON frames per §2.4 wire protocol
- `app/gateway/buffer.py` — `EventBuffer` for reconnection (§2.5a: seq-based replay, bounded 200 events / 120s)
- Heartbeat ping/pong (30s interval)
- Reconnection: client sends `last_seq` → server replays missed events

**Acceptance**: WS connection established. Messages sent via WS are persisted. Reconnection replays missed events.

### D4: WebChat Adapter
- Built-in `webchat` plugin (always-active channel adapter)
- Routes WS inbound messages → gateway `inbound.message` events
- Routes gateway `agent.run.stream` events → WS outbound frames
- Session routing: WS connection tracks active session

**Acceptance**: Message sent via WS triggers gateway event; gateway event delivered back via WS.

### D5: Turn Queue
- Per-session async turn queue (depth 1, §20.6)
- Queue overflow: max 10 pending, returns `status: "busy"` when full
- Queue wired into session message flow

**Acceptance**: Concurrent messages queued correctly. Overflow returns busy status.

### D6: React Frontend Shell
- `frontend/` — Vite + React 18 + TypeScript setup
- `frontend/src/api/client.ts` — HTTP client wrapper
- `frontend/src/api/ws.ts` — WebSocket connection with reconnection logic, seq tracking
- `frontend/src/stores/uiStore.ts` — sidebar, theme state (Zustand)
- `frontend/src/stores/wsStore.ts` — WS state, event stream, seq tracking (Zustand)
- `frontend/src/stores/chatStore.ts` — active session, messages (Zustand)
- Tailwind CSS v4 configured + shadcn/ui components initialized
- Basic layout: sidebar (session list) + main panel (chat messages + input)
- Session list: create, switch, basic display
- Chat panel: message list (scrollable), text input, send button
- Vite dev proxy: `/api` → `http://localhost:8000`

**Acceptance**: Browser shows chat UI. User can create session, type message, see it echoed back.

### D7: Theming
- `frontend/src/lib/theme.ts` — theme initialization
- 3 modes: light / dark / system (CSS custom properties, §9.3)
- Theme stored in `localStorage`, applied in `<head>` before React hydrates
- Theme toggle component in UI

**Acceptance**: Theme switcher changes appearance. No flash on page reload.

### D8: Keyboard Shortcuts (Foundation)
- `frontend/src/lib/shortcuts.ts` — shortcut manager
- Global shortcuts: `Ctrl+K` (command palette stub), `Ctrl+N` (new session), `Ctrl+/` (toggle sidebar), `Escape` (close modal)
- Chat shortcuts: `Enter` (send), `Shift+Enter` (newline)
- `Ctrl+Shift+?` — shortcuts help overlay

**Acceptance**: Shortcuts trigger expected actions. Help overlay lists all shortcuts.

---

## Tasks

### Backend — Sessions
- [ ] Create `app/sessions/models.py` — Session + Message models
- [ ] Create `app/sessions/store.py` — Session CRUD + lifecycle
- [ ] Create `app/api/routers/sessions.py` — session REST API
- [ ] Create `app/api/routers/messages.py` — message REST API
- [ ] Implement idle detection background task
- [ ] Add `sessions` and `messages` indexes to migration

### Backend — WebSocket
- [ ] Create `app/api/ws.py` — WebSocket handler with typed frames
- [ ] Create `app/gateway/buffer.py` — EventBuffer (seq-based, bounded)
- [ ] Implement connect handshake (session create/resume)
- [ ] Implement heartbeat ping/pong
- [ ] Implement reconnection replay (`last_seq` → catch-up)
- [ ] Wire WebChat adapter into gateway

### Backend — Turn Queue
- [ ] Implement per-session async turn queue in session store
- [ ] Queue overflow handling (max 10, busy response)

### Frontend
- [ ] Initialize Vite + React + TypeScript project
- [ ] Configure Tailwind CSS v4 + shadcn/ui
- [ ] Create HTTP client (`api/client.ts`)
- [ ] Create WebSocket client (`api/ws.ts`) with reconnection
- [ ] Create Zustand stores (ui, ws, chat)
- [ ] Build layout: sidebar + main chat panel
- [ ] Build session list component (create, switch, display)
- [ ] Build chat message list + input components
- [ ] Implement theme system with toggle
- [ ] Implement shortcut manager + help overlay
- [ ] Configure Vite proxy for API

### Tests
- [ ] `tests/unit/test_session_store.py` — CRUD, lifecycle states
- [ ] `tests/integration/test_api_sessions.py` — REST endpoints
- [ ] `tests/integration/test_websocket.py` — WS connect, message send, reconnection replay
- [ ] `tests/__tests__/` (frontend) — basic component render tests

---

## Testing Requirements

- Session CRUD: create, list, get, update, delete, archive all tested.
- WebSocket: connect, send message, receive event, reconnect with replay all tested.
- Frontend: renders without errors, session creation works end-to-end.

---

## Definition of Done

- [ ] Browser at `http://localhost:8000` shows chat UI
- [ ] User can create a session and see it in the sidebar
- [ ] Messages sent via chat input appear in the message list (echo, no LLM)
- [ ] WebSocket reconnection replays missed events
- [ ] Theme toggle works (light/dark/system) without flash
- [ ] Keyboard shortcuts functional (Ctrl+N, Ctrl+/, Enter, Shift+Enter)
- [ ] All tests pass
- [ ] Session lifecycle states: active → idle → archived (via API)

---

## Risks & Notes

- **No LLM yet**: messages are just persisted and echoed back. The turn loop (S05) will add LLM calls.
- **Message model stub**: Only `id`, `session_id`, `role`, `content`, `created_at` needed now. Full model (tool_calls, branching, provenance, etc.) added in S05.
- **Frontend test setup**: Decide on Vitest for frontend unit tests. E2E tests (Playwright) deferred to S15.
