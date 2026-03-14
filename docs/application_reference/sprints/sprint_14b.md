# Sprint 14b — Notifications, Budget, Audit, Backup & Export

**Phase**: 6 – Polish (I)
**Duration**: 2 weeks
**Status**: ⬜ Not Started
**Build Sequence Items**: BS-50, BS-51, BS-52, BS-53, BS-54, BS-55

> **📖 Spec reference**: For full design context, data models, and acceptance details, consult [tequila_v2_specification.md](../tequila_v2_specification.md) at the §-sections listed in the Spec References table below.

---

## Goal

Add the quality-of-life systems that make Tequila production-ready: notifications with proactive injection, audit log with configurable sinks, budget/cost tracking, app lock, backup & restore, and session transcript export. By sprint end, the platform is polished and self-managing.

---

## Spec References

| Section | Topic |
|---------|-------|
| §24.1 | Notification events |
| §24.2 | Notification delivery channels (in-app, system tray, sound) |
| §24.3 | Notification preference model |
| §24.5 | Proactive session injection (notification → agent session) |
| §12.1 | Audit log (structured events) |
| §12.2 | Metrics (audit trail analytics) |
| §12.3 | Audit retention policies |
| §23.1 | Budget & cost tracking (per-session, per-model, daily/monthly limits) |
| §6.2 | Plugin authentication (API keys, tokens) |
| §26.1 | Backup — what's backed up (DB + vault + config, encrypted archive) |
| §26.2 | Backup format |
| §26.6 | Machine migration (frozen-mode path handling) |
| §13.4 | Session transcript export (markdown, JSON, PDF) |

---

## Prerequisites

- Requires Sprint 14a (Skills & Soul Editor) to be completed.

---

## Deliverables

### D1: Notifications
- `app/notifications/` — notification system:
  - `Notification` model: `id, type, title, body, priority, channel, read, created_at`
  - Channels: in-app (WS push), system tray (Windows toast notification), sound
  - Notification preference model: per-type channel preferences, quiet hours, DND mode
  - **Notification types must use §2.2 gateway event names** — e.g. `agent.run.error` (not `agent.error`), `agent.run.complete` (not `agent.task_complete`), `inbound.message` (not `message.channel`), `plugin.error` / `plugin.deactivated` (not `plugin.disconnected`). See §24.1 for the full mapping.
  - **Proactive session injection** (§24.5): notification → creates/opens agent session → injects context
    - Templates: extensible notification → injection templates
    - Examples: calendar reminder → agent session with "Upcoming meeting: {title}"
  - API: `GET /api/notifications`, `PATCH /api/notifications/{id}/read`, `GET /api/notifications/preferences`

**Acceptance**: Event triggers notification → appears in-app + system tray. Proactive injection creates agent session with context.

### D2: Audit Log
- `app/audit/` — comprehensive audit logging (expands Sprint 01 foundation):
  - Structured events: `AuditEvent(event_type, actor, target, detail, timestamp)`
  - Event types: auth, session CRUD, message, tool execution, approval, memory change, plugin lifecycle, error
  - Audit sinks: SQLite (default), file (JSON lines), external (webhook POST)
  - Sink plugins: configurable per event type
  - Retention policies: configurable per sink (days to retain, max size)
  - API: `GET /api/audit/events` (paginated, filterable), `GET /api/audit/stats`
- Frontend: audit log viewer with filters

**Acceptance**: All major actions logged. Multiple sinks working. Retention deletes old events. Viewer shows filtered events.

### D3: Budget & Cost Tracking
- `app/budget/` — track and limit LLM spending:
  - Cost per turn: calculate from model pricing × token counts
  - Per-session cost tracking
  - Per-model cost summary
  - Budget limits: daily, monthly, per-session (configurable)
  - Budget alerts: notification when approaching limit (80%, 100%)
  - Budget exceeded: prevent new turns (configurable: hard stop or warn-and-continue)
  - API: `GET /api/budget/summary`, `GET /api/budget/usage`, `PATCH /api/budget/limits`
- Frontend: budget dashboard (current spend, trends chart, limit configuration)

**Acceptance**: Turns tracked with cost. Budget limits enforced. Alert at 80%. Dashboard shows spending.

### D4: App Lock
- `app/auth/app_lock.py` — local application security:
  - PIN or password protection for app access
  - Lock screen on startup or after idle timeout
  - PIN stored as bcrypt hash
  - Auto-lock after configurable idle time
  - Emergency unlock: recovery key generated at setup

**Acceptance**: Set PIN → restart → lock screen appears → correct PIN unlocks. Idle timeout triggers lock.

### D5: Backup & Restore
- `app/backup/` — data protection:
  - Backup: create encrypted archive of DB + vault + config
  - Exclusions: logs, browser profiles, temp files (§26.2)
  - Archive format: ZIP with AES-256 encryption (password-protected)
  - Restore: extract archive, migrate DB if needed, restart
  - Machine migration: handle frozen-mode path resolution (§26.6)
  - Scheduled backups: configurable schedule (daily, weekly)
  - API: `POST /api/backup/create`, `POST /api/backup/restore`, `GET /api/backup/list`
- Frontend: backup management (create, restore, schedule, download)

**Acceptance**: Create backup → download archive. Restore on fresh install → all data recovered. Scheduled backups run.

### D6: Session Transcript Export
- `app/sessions/export.py` — export conversation transcripts:
  - Formats: Markdown, JSON, PDF
  - Content: all messages with metadata, tool calls, timestamps
  - Options: include/exclude tool results, include/exclude system messages
  - API: `GET /api/sessions/{id}/export?format=markdown|json|pdf`
- Frontend: export button on session header

**Acceptance**: Export session as markdown → readable conversation. JSON → structured data. PDF → formatted document.

---

## Tasks

### Backend — Notifications
- [ ] Create `app/notifications/` — Notification model + store
- [ ] In-app notification via WebSocket
- [ ] System tray notification (Windows toast)
- [ ] Notification preferences + quiet hours
- [ ] Proactive session injection with templates

### Backend — Audit
- [ ] Expand `app/audit/` — add audit sinks + retention
- [ ] SQLite sink (default, extends Sprint 01)
- [ ] File sink (JSON lines)
- [ ] External webhook sink
- [ ] Retention policies
- [ ] Audit API endpoints (`/api/audit/events`, `/api/audit/stats`)

### Backend — Budget
- [ ] Create `app/budget/` — cost tracking per turn/session/model
- [ ] Budget limits (daily, monthly, per-session)
- [ ] Budget alerts via notification system
- [ ] Budget enforcement (hard stop or warn)
- [ ] Budget API endpoints

### Backend — App Lock
- [ ] Create `app/auth/app_lock.py` — PIN/password lock
- [ ] Lock screen endpoint
- [ ] Idle timeout auto-lock
- [ ] Recovery key generation

### Backend — Backup
- [ ] Create `app/backup/` — backup creation (ZIP + AES)
- [ ] Backup exclusions
- [ ] Restore logic (extract, migrate, restart)
- [ ] Machine migration path handling
- [ ] Scheduled backup task
- [ ] Backup API endpoints

### Backend — Transcript Export
- [ ] Create `app/sessions/export.py`
- [ ] Markdown export
- [ ] JSON export
- [ ] PDF export (fpdf2)
- [ ] Export API endpoint

### Frontend
- [ ] Notification center (bell icon, dropdown, notification list)
- [ ] Notification preferences page
- [ ] Audit log viewer (table + filters)
- [ ] Budget dashboard (spend chart, limits config)
- [ ] Lock screen component
- [ ] Backup management page
- [ ] Export button on session header

### Tests
- [ ] `tests/unit/test_notifications.py` — create, deliver, preferences, injection
- [ ] `tests/unit/test_audit.py` — event creation, sinks, retention
- [ ] `tests/unit/test_budget.py` — cost calculation, limits, alerts
- [ ] `tests/unit/test_app_lock.py` — PIN hash, verify, timeout
- [ ] `tests/unit/test_backup.py` — create, restore, encryption
- [ ] `tests/unit/test_export.py` — markdown, JSON, PDF output

---

## Testing Requirements

- Notifications: event → in-app notification appears. Proactive injection → session created.
- Audit: perform actions → events logged → query returns them. Retention deletes old.
- Budget: spend exceeds limit → notification + enforcement.
- App lock: set PIN → restart → lock screen → correct PIN unlocks → idle timeout triggers lock.
- Backup: create → corrupt DB → restore → everything works.
- Export: session export as markdown/JSON/PDF produces correct output.

---

## Definition of Done

- [ ] Notifications: in-app, system tray, proactive injection
- [ ] Audit log: structured events, 3 sinks, retention
- [ ] Budget tracking: per-session/model costs, limits, alerts
- [ ] App lock: PIN/password with idle timeout
- [ ] Backup & restore: encrypted archives, scheduled backups
- [ ] Transcript export: markdown, JSON, PDF
- [ ] All tests pass

---

## Risks & Notes

- **Notifications depend on Sprint 14a**: budget alerts may reference skill-related events. Ensure notification types cover all Sprint 14a event types.
- **Windows toast notifications**: Use `win10toast` or `plyer` library. May require special handling for packaged apps.
- **PDF export**: Reuse fpdf2 from documents plugin. Keep formatting simple.
- **Backup encryption**: Use `cryptography` library's Fernet or AES-GCM. Ensure password derivation uses PBKDF2/scrypt.
- **Audit sink expansion**: Sprint 01 created the basic audit foundation (`app/audit/log.py`). This sprint adds configurable sinks and retention — extend, don't rewrite.
