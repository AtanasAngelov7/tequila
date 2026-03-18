# Sprint 16 — Future: Image Generation, Additional Connectors & Auto-Update

**Phase**: 7 – Future Additions (open-ended)
**Duration**: 2 weeks (initial; ongoing)
**Status**: ✅ Done
**Build Sequence Items**: BS-60, BS-61, BS-62
> **📖 Spec reference**: For full design context, data models, and acceptance details, consult [tequila_v2_specification.md](../tequila_v2_specification.md) at the §-sections listed in the Spec References table below.
---

## Goal

Implement forward-looking features: an image generation plugin (DALL-E / Stable Diffusion), additional messaging connector plugins (Slack, Discord, WhatsApp, Signal), and a full auto-update mechanism. These features extend Tequila's reach without changing the core architecture.

---

## Spec References

| Section | Topic |
|---------|-------|
| §8.6 (future) | Image generation plugin (image_generate, image_edit, image_variations) |
| §8.6 (future) | Additional connector plugins (Slack, Discord, WhatsApp, Signal) |
| §29.5 | Auto-update mechanism (version check, notification, in-place patching) |

---

## Prerequisites

- Requires Sprint 15 deliverables and the Phase 6 gate to be completed before this sprint begins.

---

## Deliverables

### D1: Image Generation Plugin
- `app/plugins/builtin/image_gen/` — AI image generation:
  - `image_generate(prompt, style?, size?, model?)` → generated image path
  - `image_edit(image_path, prompt, mask_path?)` → edited image path
  - `image_variations(image_path, count?)` → variation images
  - Provider support:
    - **DALL-E** (OpenAI API): generation, editing, variations
    - **Stable Diffusion** (local or API): txt2img, img2img, inpainting
  - Config: default provider, default size, default style, API key
  - Image output: saved to `data/files/generated/`, tracked in session_files
  - Safety: `side_effect` (creates files, costs API credits)
- Frontend: image result display with gallery view, regenerate/edit actions

**Acceptance**: Agent generates images via prompt. Edits existing images. Multiple providers supported.

### D2: Slack Connector Plugin
- `app/plugins/builtin/slack/` — Slack integration:
  - Channel: Slack Bot (websocket or Events API)
  - Tools: `slack_send(channel, text)`, `slack_search(query)`, `slack_react(channel, ts, emoji)`
  - Config: Bot token, App token, allowed channels
  - Message routing: Slack messages mentioning bot → agent session
  - Thread awareness: conversations stay in threads

**Acceptance**: Mention bot in Slack → agent responds in thread. Agent sends messages to channels.

### D3: Discord Connector Plugin
- `app/plugins/builtin/discord/` — Discord integration:
  - Channel: Discord Bot (discord.py or raw API)
  - Tools: `discord_send(channel_id, text)`, `discord_react(message_id, emoji)`
  - Config: Bot token, allowed servers/channels
  - Message routing: mentions or DMs → agent session
  - Thread/forum support

**Acceptance**: Message bot in Discord → agent responds. Agent can send to channels.

### D4: WhatsApp Connector Plugin
- `app/plugins/builtin/whatsapp/` — WhatsApp integration:
  - Channel: WhatsApp Business API (or unofficial bridge)
  - Tools: `whatsapp_send(number, text)`, `whatsapp_send_media(number, file_path)`
  - Config: API credentials, allowed contacts
  - Note: WhatsApp Business API has strict requirements; this may use a bridge service

**Acceptance**: Receive WhatsApp message → agent responds. Agent sends messages.

### D5: Signal Connector Plugin
- `app/plugins/builtin/signal/` — Signal integration:
  - Channel: Signal CLI or signal-cli-rest-api bridge
  - Tools: `signal_send(number, text)`, `signal_send_file(number, file_path)`
  - Config: signal-cli path or API endpoint, registered phone number
  - Privacy-focused: E2E encrypted messaging

**Acceptance**: Receive Signal message → agent responds. Agent sends messages.

### D6: Auto-Update Mechanism
- `app/update/` — keep Tequila current:
  - **Version check**: on startup, check GitHub releases API (or custom endpoint) for new version
  - **Update notification**: if new version found → notification with changelog summary
  - **Download**: download new installer in background
  - **In-place patching**: shut down → replace binaries → restart (or prompt user to run new installer)
  - Config: check frequency (daily), auto-download (on/off), update channel (stable/beta)
  - Rollback: keep previous version for manual rollback
  - API: `GET /api/update/check`, `POST /api/update/download`, `POST /api/update/apply`
- Frontend: update notification banner, settings page for update preferences

**Acceptance**: New version available → notification shown → user downloads → installs update → app restarts with new version.

---

## Tasks

### Backend — Image Generation
- [x] Create `app/plugins/builtin/image_gen/` package
- [x] Implement DALL-E provider (OpenAI API)
- [x] Implement Stable Diffusion provider (API + optional local)
- [x] Image generation tools: generate, edit, variations
- [x] Image output tracking (session_files)

### Backend — Slack
- [x] Create `app/plugins/builtin/slack/` package
- [x] Implement Slack Bot channel (WebSocket or Events API)
- [x] Implement slack tools (send, search, react)
- [x] Thread-aware routing

### Backend — Discord
- [x] Create `app/plugins/builtin/discord/` package
- [x] Implement Discord Bot channel
- [x] Implement discord tools (send, react)
- [x] DM and mention routing

### Backend — WhatsApp
- [x] Create `app/plugins/builtin/whatsapp/` package
- [x] Implement WhatsApp Business API or bridge channel
- [x] Implement whatsapp tools (send, send_media)

### Backend — Signal
- [x] Create `app/plugins/builtin/signal/` package
- [x] Implement signal-cli channel
- [x] Implement signal tools (send, send_file)

### Backend — Auto-Update
- [x] Create `app/update/` — version check logic
- [x] GitHub releases API integration
- [x] Background download
- [x] In-place update (shutdown → replace → restart)
- [x] Rollback logic (keep previous version)
- [x] Update API endpoints

### Frontend
- [ ] Image generation: gallery view, regenerate/edit actions in chat
- [ ] Connector plugin config UIs (Slack, Discord, WhatsApp, Signal)
- [x] Auto-update notification banner
- [ ] Update settings page (channel, auto-download, check frequency)

### Tests
- [x] `tests/unit/test_image_gen.py` — generate, edit, variations (mocked API)
- [x] `tests/unit/test_slack_plugin.py` — routing, tools (mocked)
- [x] `tests/unit/test_discord_plugin.py` — routing, tools (mocked)
- [x] `tests/unit/test_auto_update.py` — version check, download, apply

---

## Testing Requirements

- Image gen: mock DALL-E API → generate returns image → saved to files. Stable Diffusion mock works.
- Connectors: mock each platform API → inbound message routed → outbound message sent.
- Auto-update: mock releases API → new version detected → notification shown → download → apply.

---

## Definition of Done

- [x] Image generation plugin: DALL-E + Stable Diffusion, generate/edit/variations
- [x] Slack connector: send/receive messages, thread awareness
- [x] Discord connector: send/receive messages, DMs
- [x] WhatsApp connector: send/receive messages
- [x] Signal connector: send/receive messages
- [x] Auto-update: version check, notification, download, apply, rollback
- [x] All tests pass

---

## Risks & Notes

- **Open-ended phase**: This sprint marks the beginning of ongoing development. Not all items need to ship in the initial 2-week window. Prioritize: Auto-update → Image gen → Slack → Discord → WhatsApp → Signal.
- **WhatsApp Business API costs**: Official API has costs and approval process. A bridge (e.g., whatsapp-web.js) is unofficial but free. Document tradeoffs.
- **Signal dependency**: signal-cli requires Java runtime. Consider docker-based signal-cli-rest-api as a cleaner option.
- **Auto-update security**: Verify downloaded updates via checksums/signatures. Prevent MITM attacks on update channel.
- **Connector maintenance burden**: Each connector's API evolves independently. Budget ongoing maintenance time for API changes.
