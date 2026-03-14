# Sprint 12 — Plugins I: Plugin System, Auth, Telegram & Email

**Phase**: 5 – Plugins & Integrations (I)
**Duration**: 2 weeks
**Status**: ⬜ Not Started
**Build Sequence Items**: BS-34, BS-35, BS-36, BS-37, BS-38, BS-39, BS-40

> **📖 Spec reference**: For full design context, data models, and acceptance details, consult [tequila_v2_specification.md](../tequila_v2_specification.md) at the §-sections listed in the Spec References table below.

---

## Goal

Build the plugin system infrastructure and deliver the first wave of built-in connector plugins. By sprint end, the platform has a robust plugin lifecycle (install, enable, disable, health-check), auth flows for LLM providers, and working connector plugins for Telegram, Gmail, SMTP/IMAP, Google Calendar, and webhooks.

---

## Spec References

| Section | Topic |
|---------|-------|
| §8.0 | Plugin types (connector, tool-provider, pipeline-hook, audit-sink) |
| §8.1 | Auth & channel models (PluginAuth, ChannelCapabilities) |
| §8.7 | PluginBase ABC (lifecycle hooks, config schema, health check) |
| §8.8 | Plugin registry + CRUD API |
| §8.9 | Plugin dependency management (PluginDependencies, install flow, venv isolation) |
| §6.1 | Auth flows (OpenAI OAuth, Anthropic OAuth, API key management) |
| §8.6 | Built-in plugin catalog — Telegram (channel + tools) |
| §8.6 | Built-in plugin catalog — Gmail (channel + tools) |
| §8.6 | Built-in plugin catalog — SMTP/IMAP (channel + tools) |
| §8.6 | Built-in plugin catalog — Google Calendar (tools + optional trigger) |
| §8.6 | Built-in plugin catalog — Webhooks (inbound channel) |
| §20.4 | Idempotency (dedup keys for Telegram, email, webhooks) |

---

## Prerequisites

- Requires Sprint 11 deliverables and the Phase 4 gate to be completed before this sprint begins.

---

## Deliverables

### D1: Plugin System Core
- `app/plugins/base.py` — `PluginBase` ABC:
  - Lifecycle hooks: `on_install()`, `on_enable()`, `on_disable()`, `on_uninstall()`
  - Config schema: plugin declares `config_schema()` (JSON Schema for its settings)
  - Health check: `health() → PluginHealthStatus`
  - Tool registration: plugin declares tools via `get_tools() → list[ToolDefinition]`
  - Channel registration: plugin declares channels via `get_channels() → list[ChannelAdapter]`
- `app/plugins/registry.py` — plugin registry:
  - Register built-in plugins at startup
  - CRUD API for plugin management:
    - `GET /api/plugins` — list all plugins (installed, enabled, health)
    - `GET /api/plugins/{id}` — plugin detail + config
    - `POST /api/plugins/{id}/enable` — enable plugin
    - `POST /api/plugins/{id}/disable` — disable plugin
    - `PATCH /api/plugins/{id}/config` — update plugin config
  - Health check loop: periodic health check for enabled plugins, auto-disable on repeated failures
- Plugin dependency management:
  - `PluginDependencies` model: `pip_packages`, `system_packages`, `optional_packages`
  - Install flow: install pip packages into plugin venv on enable
  - Venv isolation: each plugin with dependencies gets its own venv (or shared if no conflicts)

**Acceptance**: Plugin lifecycle works (install/enable/disable). Health checks run. Dependencies installed. CRUD API operational.

### D2: Auth Flows
- `app/auth/providers.py` — LLM provider authentication:
  - API key management: store encrypted API keys per provider
  - OpenAI OAuth flow (if supported)
  - Anthropic OAuth flow (if supported)
  - Key validation: test key on save
- `app/auth/encryption.py` — encrypt at rest using platform keyring or derived key
- API:
  - `POST /api/auth/providers/{provider}/key` — save API key
  - `DELETE /api/auth/providers/{provider}/key` — revoke key
  - `GET /api/auth/providers` — list configured providers (key status, not actual keys)

**Acceptance**: Save API key → encrypted. Provider shows as configured. Invalid key → validation error.

### D3: Telegram Plugin
- `app/plugins/builtin/telegram/` — Telegram connector:
  - Channel: receive messages via Telegram Bot API (long polling or webhook)
  - Tools: `telegram_send(chat_id, text)`, `telegram_send_file(chat_id, file_path)`
  - Config: bot token, allowed chat IDs, webhook URL (optional)
  - Message routing: Telegram messages → gateway `inbound.message` → agent session
  - Session mapping: configurable (one session per chat, or single session for all)

**Acceptance**: Send message to Telegram bot → agent responds in Telegram. Agent sends messages via tool.

### D4: Gmail Plugin
- `app/plugins/builtin/gmail/` — Gmail connector:
  - Channel: poll Gmail inbox via API (OAuth2), route new emails to agent
  - Tools: `gmail_send(to, subject, body, attachments?)`, `gmail_search(query)`, `gmail_read(message_id)`
  - Config: OAuth2 credentials, poll interval, label filters
  - Email → session routing: configurable (per-sender session, single inbox session)

**Acceptance**: New email → agent notified. Agent sends email via tool. Search works.

### D5: SMTP/IMAP Plugin
- `app/plugins/builtin/smtp_imap/` — generic email connector:
  - Channel: IMAP polling for incoming emails
  - Tools: `email_send(to, subject, body)` via SMTP, `email_search(query)`, `email_read(message_id)`
  - Config: SMTP host/port/auth, IMAP host/port/auth, poll interval
  - Alternative to Gmail for non-Google email providers

**Acceptance**: IMAP polls inbox → new emails routed to agent. SMTP sends emails.

### D6: Google Calendar Plugin
- `app/plugins/builtin/google_calendar/` — Calendar integration:
  - Tools: `calendar_list_events(date_range)`, `calendar_create_event(title, start, end, attendees?)`, `calendar_update_event(event_id, updates)`, `calendar_delete_event(event_id)`
  - Optional trigger: upcoming event notification → proactive agent message
  - Config: OAuth2 credentials, calendar ID, notification lead time

**Acceptance**: Agent lists, creates, updates, deletes calendar events. Upcoming event trigger fires.

### D7: Webhooks Plugin
- `app/plugins/builtin/webhooks/` — inbound webhook channel:
  - Configurable endpoints: `POST /api/webhooks/{hook_id}` → route payload to agent session
  - Webhook registration: name, secret (HMAC validation), target session
  - Payload transformation: configurable JSONPath mapping to extract message text
  - Tools: `webhook_list()`, `webhook_create(name, config)`

**Acceptance**: External service POSTs to webhook → agent receives message. HMAC validation works.

---

## Tasks

### Backend — Plugin System
- [ ] Create `app/plugins/base.py` — PluginBase ABC
- [ ] Create `app/plugins/registry.py` — registry + CRUD API
- [ ] Implement lifecycle hooks (on_install, on_enable, on_disable, on_uninstall)
- [ ] Implement health check loop (periodic, auto-disable)
- [ ] Implement PluginDependencies + pip install flow
- [ ] Implement venv isolation for plugin dependencies
- [ ] Migration: plugins table (config, state, health)

### Backend — Auth
- [ ] Create `app/auth/providers.py` — API key management
- [ ] Create `app/auth/encryption.py` — key encryption at rest
- [ ] Auth API endpoints (save key, revoke, list providers)
- [ ] Key validation on save

### Backend — Telegram Plugin
- [ ] Create `app/plugins/builtin/telegram/` plugin package
- [ ] Implement Telegram Bot API channel (long polling)
- [ ] Implement telegram_send, telegram_send_file tools
- [ ] Session mapping (per-chat or single)

### Backend — Gmail Plugin
- [ ] Create `app/plugins/builtin/gmail/` plugin package
- [ ] Implement OAuth2 flow for Gmail
- [ ] Implement inbox polling channel
- [ ] Implement gmail_send, gmail_search, gmail_read tools

### Backend — SMTP/IMAP Plugin
- [ ] Create `app/plugins/builtin/smtp_imap/` plugin package
- [ ] Implement IMAP polling channel
- [ ] Implement SMTP send tool
- [ ] email_search, email_read tools

### Backend — Google Calendar Plugin
- [ ] Create `app/plugins/builtin/google_calendar/` plugin package
- [ ] Implement calendar tools (list, create, update, delete)
- [ ] Implement upcoming event trigger
- [ ] OAuth2 flow for Google Calendar

### Backend — Webhooks Plugin
- [ ] Create `app/plugins/builtin/webhooks/` plugin package
- [ ] Implement webhook endpoint router
- [ ] HMAC validation
- [ ] Payload transformation (JSONPath)

### Frontend
- [ ] Plugin management page (list, enable/disable, configure, health status)
- [ ] Auth settings page (provider keys, OAuth flow triggers)
- [ ] Telegram config UI
- [ ] Email config UI (Gmail + SMTP/IMAP)
- [ ] Calendar config UI
- [ ] Webhook config UI (create, list, copy URL)

### Tests
- [ ] `tests/unit/test_plugin_system.py` — lifecycle, registry, health
- [ ] `tests/unit/test_auth.py` — key encryption, validation
- [ ] `tests/unit/test_telegram_plugin.py` — message routing, tools (mocked API)
- [ ] `tests/unit/test_gmail_plugin.py` — OAuth, polling, tools (mocked)
- [ ] `tests/unit/test_smtp_imap.py` — send, receive (mocked)
- [ ] `tests/unit/test_calendar_plugin.py` — tools (mocked API)
- [ ] `tests/unit/test_webhooks.py` — routing, HMAC, payload transform
- [ ] `tests/integration/test_plugin_lifecycle.py` — install → enable → health → disable

---

## Testing Requirements

- Plugin system: register → enable → health check passes → disable → re-enable.
- Auth: save key → encrypted in DB → not retrievable as plaintext. Validation rejects bad keys.
- Telegram: mock Bot API → inbound message routed → agent response sent back.
- Gmail: mock Gmail API → new email → agent notified → send reply.
- Webhooks: POST payload → HMAC valid → agent receives message. Invalid HMAC → rejected.

---

## Definition of Done

- [ ] Plugin system: PluginBase ABC, registry, CRUD API, health checks, dependency management
- [ ] Auth: API key management with encryption, validation
- [ ] Telegram plugin: send/receive messages via Bot API
- [ ] Gmail plugin: OAuth, inbox polling, send/search/read
- [ ] SMTP/IMAP plugin: IMAP polling, SMTP send
- [ ] Google Calendar plugin: CRUD events, upcoming event trigger
- [ ] Webhooks plugin: inbound routing with HMAC validation
- [ ] All tests pass

---

## Risks & Notes

- **7 BS items — heavy sprint**: Core plugin system makes all connector plugins straightforward once done. Prioritize plugin system core (D1) first.
- **OAuth complexity**: Gmail and Calendar OAuth flows require redirect handling. Consider using `google-auth-oauthlib` for standard flows.
- **Telegram rate limits**: Respect Telegram's rate limits (30 msgs/sec globally, 1 msg/sec to groups). Implement send queue.
- **Venv isolation performance**: Creating venvs per plugin is slow on Windows. Consider shared venvs with conflict detection as a faster alternative.
- **Security**: API keys encrypted at rest, but also ensure they're never logged or returned in API responses.
