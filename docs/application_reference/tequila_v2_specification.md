# Tequila v2 — Unified Application Specification

Last updated: March 13, 2026
Status: **Design-locked** — ready for implementation task breakdown.

---

## 1) Product Definition

Tequila is a local-first personal AI agent platform. One user, one machine, many agents working together through a unified gateway.

### 1.1 What It Does
- Conversational AI assistant with streaming chat
- Multi-agent system: main agent + specialized sub-agents
- Persistent memory and knowledge base across sessions
- Scheduled/background automation
- Multi-channel communication (web UI, Telegram, email)
- Tool execution with safety controls

### 1.2 Design Principles
- **Gateway-centric**: every event in the system flows through one routing layer
- **Session-based**: every interaction (user chat, agent-to-agent, cron trigger) is a session
- **Hierarchical agents**: main agent is admin, sub-agents are scoped
- **Local-first**: SQLite, local filesystem, no cloud dependency
- **Multi-user-ready**: single-user now, but architecture supports adding users without structural changes

### 1.3 Tech Stack
- **Backend**: Python 3.12, FastAPI, SQLite (WAL mode), Pydantic
- **Frontend**: React + Vite SPA, Tailwind CSS v4, shadcn/ui, Zustand, TanStack Query, Lucide icons
- **Deployment**: Local desktop — development via `.venv`, production via Windows installer (PyInstaller + Inno Setup, §29)
- **LLM Providers**: OpenAI, Anthropic (OAuth or API key)
- **Embeddings**: Local or provider-backed

---

## 2) Gateway Architecture

The gateway is the core of Tequila v2. It replaces the current scattered integration pattern with a single unified event routing layer.

### 2.1 What the Gateway Is

A Python async singleton that lives inside the FastAPI process. Not a separate daemon. All events — user messages, agent runs, Telegram inbound, email delivery, cron triggers, UI updates — flow through a single routing layer.

```
┌────────────────────────────────────────────────────────────────┐
│                       TEQUILA GATEWAY                          │
│                (in-process async event router)                 │
│                                                                │
│  Plugins (inbound):       Core:            Outbound:          │
│  ┌──────────────────┐    ┌──────────┐    ┌─────────────────┐   │
│  │ webchat (built-in)│───▶│          │───▶│ Agent Runner    │   │
│  │ [WS ↔ React UI]  │    │          │    │ (turn loop)     │   │
│  ├──────────────────┤    │  Event   │    ├─────────────────┤   │
│  │ telegram          │───▶│  Router  │───▶│ WS Streaming   │   │
│  │ [polling/webhook] │    │          │    │ (to React UI)  │   │
│  ├──────────────────┤    │          │    ├─────────────────┤   │
│  │ gmail             │───▶│          │───▶│ Plugin Send     │   │
│  │ [IMAP/push]       │    │          │    │ (routed by      │   │
│  ├──────────────────┤    │          │    │  channel name)  │   │
│  │ smtp_imap         │───▶│          │    ├─────────────────┤   │
│  │ [IMAP poll]       │    │          │    │ Notifications   │   │
│  ├──────────────────┤    │          │    └─────────────────┘   │
│  │ google_calendar   │───▶│          │                         │
│  │ [API poll/push]   │    │          │                         │
│  ├──────────────────┤    │          │                         │
│  │ webhooks          │───▶│          │                         │
│  │ [HTTP trigger]    │    │          │                         │
│  ├──────────────────┤    │          │                         │
│  │ MCP servers       │───▶│          │                         │
│  │ [external tools]  │    │          │                         │
│  ├──────────────────┤    │          │                         │
│  │ cron/scheduler    │───▶│          │                         │
│  └──────────────────┘    └──────────┘                         │
│                                                                │
│  Plugin Registry │ Session Store │ Policy Engine │ Audit Log     │
└────────────────────────────────────────────────────────────────┘
```

### 2.2 Event Model

Every event is a Pydantic model. Runtime validation + automatic JSON Schema export.

```python
class GatewayEvent(BaseModel):
    event_id: str                    # UUID, used for correlation and future dedup
    event_type: str                  # e.g. "inbound.message", "agent.run", "delivery.send"
    source: EventSource              # who/what emitted this event
    session_key: str                 # which session this belongs to
    timestamp: datetime
    payload: dict                    # event-type-specific data

class EventSource(BaseModel):
    kind: Literal["user", "agent", "channel", "scheduler", "webhook", "system"]
    id: str                          # agent_id, channel_id, etc.
```

Core event types:

| Event Type | Direction | Description |
|---|---|---|
| `inbound.message` | Adapter → Router | User/channel message received |
| `agent.run.start` | Router → Agent | Trigger agent turn execution |
| `agent.run.stream` | Agent → Router | Streaming token/tool events |
| `agent.run.complete` | Agent → Router | Turn finished |
| `agent.run.error` | Agent → Router | Turn failed |
| `delivery.send` | Agent → Router | Agent wants to send to a channel |
| `delivery.result` | Adapter → Router | Send succeeded/failed |
| `session.created` | Router → Subscribers | New session opened |
| `session.updated` | Router → Subscribers | Session state changed |
| `ui.event` | Router → WS | Frontend-specific event (typing, status, progress) |
| `plugin.installed` | System → Subscribers | New plugin registered |
| `plugin.activated` | System → Subscribers | Plugin started successfully |
| `plugin.error` | Plugin → Router | Plugin encountered an error |
| `plugin.deactivated` | System → Subscribers | Plugin stopped |
| `plugin.health_changed` | System → Subscribers | Plugin health check result changed |
| `notification.push` | System → Router → WS | User-facing notification (see §24.5) |
| `escalation.triggered` | Agent → Router | Sub-agent escalation handoff (see §4.2a) |
| `budget.turn_cost` | System → Subscribers | Per-turn cost recorded (see §23.2) |
| `budget.warning` | System → Router → WS | Spend reached warning threshold (see §23.3) |
| `budget.exceeded` | System → Router → WS | Spend reached cap limit (see §23.3) |
| `provider.unavailable` | System → Subscribers | Provider circuit breaker opened (see §19.3) |
| `transcription.complete` | System → Router | Audio transcription finished (see §22.1) |
| `scheduler.skipped` | System → Subscribers | Cron job skipped due to contention (see §20.8) |

### 2.3 Streaming Event Payload Schema

`agent.run.stream` events carry a typed payload that the frontend uses to render real-time output:

```python
class StreamPayload(BaseModel):
    kind: Literal[
        "text_delta",             # incremental text token
        "tool_call_start",        # tool call detected, name + ID
        "tool_call_input_delta",  # streaming tool input JSON
        "tool_result",            # tool execution result
        "approval_request",       # tool needs user approval before executing
        "approval_resolved",      # user approved or denied
        "thinking",               # model thinking/reasoning (if exposed)
        "error",                  # non-fatal error during turn
    ]
    text: str | None = None                # for text_delta, thinking
    tool_name: str | None = None           # for tool_call_start, tool_result, approval_request
    tool_call_id: str | None = None        # correlates start → input → result
    tool_input: dict | None = None         # for tool_call_input_delta (partial JSON)
    tool_result: dict | None = None        # for tool_result (success/error payload)
    approval_action: Literal["approve", "deny"] | None = None  # for approval_resolved
    error_message: str | None = None       # for error kind
```

### 2.4 Plugins (Replaces Channel Adapters)

All external integrations and internal extensions are **plugins**. A plugin is a self-contained package that registers with the gateway and declares what it provides (tools, channel adapter, pipeline hooks, or any combination), what auth it needs, and what config it exposes. Connectors (external service integrations) are one type of plugin.

See **§8 Plugin System** for the full architecture, model, registry, and catalog.

### 2.5 Wire Protocol (WebSocket to Frontend)

The React frontend connects to a single WebSocket endpoint. The protocol is typed JSON frames:

```python
# Client → Server
class WSClientFrame(BaseModel):
    id: str                          # request correlation ID
    method: str                      # "connect", "message.send", "session.create", etc.
    params: dict = {}

# Server → Client (response)
class WSServerResponse(BaseModel):
    id: str                          # matches request ID
    ok: bool
    payload: dict = {}
    error: str | None = None

# Server → Client (push event)
class WSServerEvent(BaseModel):
    event: str                       # "agent.stream", "agent.complete", "session.updated", etc.
    payload: dict
    seq: int                         # monotonic sequence number for ordering
```

**Connect handshake**:
```python
class ConnectParams(BaseModel):
    token: str | None = None         # GATEWAY_TOKEN auth (unused locally, ready for future)
    client_id: str | None = None     # client identifier (ready for multi-client dedup)
```

The `token` field and `client_id` are present in the schema from day one but not enforced in single-user local mode. When multi-user or remote access is added, enforcement is a one-line config check.

### 2.5a WebSocket Reconnection & State Recovery

WebSocket connections drop frequently — sleep/wake, network changes, browser tab suspension. The protocol supports seamless reconnection with event replay so users never lose streaming content.

#### Reconnection sequence

```
1. Client detects WS close (onerror / onclose)
2. Client enters reconnection state:
    → Show "Reconnecting..." indicator in UI
    → Exponential backoff: 1s → 2s → 4s → 8s → 15s → 30s (max)
    → Max attempts: unlimited (keep trying until user navigates away)
3. Client opens new WS connection:
    → Send connect frame with:
        { method: "connect", params: { last_seq: <last received seq number> } }
4. Server receives connect with last_seq:
    → Look up buffered events with seq > last_seq
    → If events found: replay them in order (fast burst, no delays)
    → If last_seq is too old (outside buffer window): send { event: "resync_required" }
5. Client receives replayed events:
    → Process normally (text_delta, tool_result, etc.)
    → UI catches up seamlessly — user sees streaming resume
6. If resync_required:
    → Client fetches current session state via REST: GET /api/sessions/{id}/messages?limit=50
    → Rebuilds message list from REST response
    → Subscribes to live events from current seq onward
    → Any in-flight turn's partial streaming content is lost (recovered when turn completes)
```

#### Server-side event buffer

```python
class EventBuffer:
    """Ring buffer of recent WS events per session, keyed by seq number."""
    max_events: int = 200              # keep last 200 events
    max_age_s: int = 120               # expire events older than 2 minutes
    # Stores: { seq: WSServerEvent } — pruned on insert
```

**Buffer sizing**: 200 events × ~120 seconds covers typical streaming content (a 2-minute tool-call-heavy turn produces ~100–150 events). If the client reconnects within 2 minutes, replay is seamless. Beyond that, full resync.

#### Client-side state

```typescript
interface ReconnectionState {
    lastSeq: number;                    // last seq received from server
    attempt: number;                    // current retry attempt (for backoff)
    reconnecting: boolean;              // UI indicator
    pendingUserMessages: WSClientFrame[]; // messages typed while disconnected (sent on reconnect)
}
```

**Pending messages**: If the user types a message while disconnected, it's queued locally. On reconnect, queued messages are sent after event replay completes. The UI shows a subtle "queued" indicator on the message.

#### In-flight turn recovery

| Scenario | Recovery |
|---|---|
| WS drops mid-stream, reconnects within buffer window | Events replayed from `last_seq` — streaming resumes seamlessly |
| WS drops mid-stream, reconnects outside buffer window | `resync_required` → REST fetch. Turn's partial content is lost but the complete response will be in messages once the turn finishes. UI shows "Reconnected — loading messages..." |
| WS drops while tool approval is pending | Approval request is replayed on reconnect. If the turn timed out waiting, the agent received a timeout error and the turn failed gracefully (§19.4). |
| WS drops during idle (no active turn) | Silent reconnect. No visible impact. |

#### Heartbeat

- Server sends `{ event: "ping", seq: N }` every 30 seconds.
- Client responds with `{ method: "pong" }` (not sequenced — fire-and-forget).
- If server receives no pong for 90 seconds, it cleans up the WS connection (frees buffer memory).
- If client receives no ping for 45 seconds, it assumes the connection is dead and starts reconnection.

### 2.6 What We Skip (vs OpenClaw) and Why

| OpenClaw Feature | Tequila Decision | Reason |
|---|---|---|
| JSON Schema wire validation library | **Skip** — Pydantic does the same job natively | All in-process Python; no cross-language boundary |
| Device pairing / crypto handshake | **Skip** — `GATEWAY_TOKEN` field reserved in connect frame | Local-only; no remote clients to authenticate |
| Multi-client deduplication cache | **Skip** — request IDs present for future use | Single client (React frontend); no duplicate requests |
| TLS / Tailscale tunnel management | **Skip** — configurable bind host (`127.0.0.1` default) | Reverse proxy (nginx/caddy) handles TLS if ever needed |
| Send policy per channel/chat-type | **Replaced** — per-session `SessionPolicy` (see §2.7) | Reframed as agent capability control, not routing rules |

### 2.7 Session Policy Engine

Per-session policy controlling what an agent can and cannot do. Enforced at the gateway level before any tool execution or delivery.

```python
class SessionPolicy(BaseModel):
    allowed_channels: list[str] = ["*"]          # channels agent can deliver to
    allowed_tools: list[str] = ["*"]             # tool names agent can invoke
    allowed_paths: list[str] = ["*"]             # filesystem path whitelist
    can_spawn_agents: bool = True                # can this session spawn sub-agents
    can_send_inter_session: bool = True          # can send to other sessions
    max_tokens_per_run: int | None = None        # token budget cap per turn
    max_tool_rounds: int = 25                    # max tool calls per turn
    require_confirmation: list[str] = []         # tool names that need user approval first
    auto_approve: list[str] = []                 # tools that skip approval in this session

class SessionPolicyPresets:
    ADMIN = SessionPolicy()                      # full access — no restrictions
    STANDARD = SessionPolicy(                    # default for user sessions
        require_confirmation=["code_exec", "fs_write_file", "fs_delete"],
    )
    WORKER = SessionPolicy(                      # sub-agent: no external delivery
        can_spawn_agents=False,
        can_send_inter_session=False,
        allowed_channels=[],
    )
    CODE_RUNNER = SessionPolicy(                 # restricted to code + file tools
        can_spawn_agents=False,
        can_send_inter_session=False,
        allowed_channels=[],
        allowed_tools=["code_exec", "fs_read_file", "fs_write_file", "fs_list_dir"],
    )
    READ_ONLY = SessionPolicy(                   # no writes, no tool execution
        allowed_tools=[],
        can_spawn_agents=False,
        can_send_inter_session=False,
        allowed_channels=[],
    )
    CHAT_ONLY = SessionPolicy(                   # text conversation only, no tools
        allowed_tools=[],
        can_spawn_agents=False,
    )
```

**Enforcement points**:
- Tool execution: gateway checks `allowed_tools` before running any tool
- Filesystem access: gateway checks `allowed_paths` before file operations
- Delivery: gateway checks `allowed_channels` before routing `delivery.send`
- Agent spawn: gateway checks `can_spawn_agents` before `session_spawn`
- Tool rounds: gateway enforces `max_tool_rounds` per turn
- Confirmation: gateway injects approval gate for tools in `require_confirmation` unless listed in `auto_approve`

---

## 3) Session Model

Every interaction in Tequila is a session. Sessions are the universal unit of conversation, context, and routing.

### 3.1 Session Keys

```
user:main                           # user's primary chat (direct with main agent)
user:agent:<agent_id>               # user chatting directly with a specific agent
agent:<agent_id>:sub:<uuid>         # sub-agent spawned session
channel:telegram:<chat_id>          # inbound Telegram conversation
channel:email:<account>:<thread_id> # inbound email thread
cron:<job_id>                       # scheduled task execution
webhook:<uuid>                      # webhook-triggered execution
```

### 3.2 Session Record

```python
class Session(BaseModel):
    session_key: str                 # unique key (see above)
    session_id: str                  # UUID
    kind: Literal["user", "agent", "channel", "cron", "webhook"]
    agent_id: str                    # which agent handles this session
    channel: str                     # "webchat", "telegram", "email", "internal"
    policy: SessionPolicy            # what this session is allowed to do
    status: Literal["active", "idle", "archived"]
                                     # active → idle (auto, §3.7) → archived (manual/auto)
                                     # deletion is a hard DELETE, not a status value
    parent_session_key: str | None   # if this was spawned by another session
    title: str | None = None         # auto-generated or user-set display title
    summary: str | None = None       # LLM-generated summary of conversation so far
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None  # for sorting session list
    message_count: int = 0           # for display in session list
    version: int = 1                 # optimistic concurrency control (§20.3b)
    metadata: dict = {}              # flexible storage for channel-specific data
```

#### Session title generation

Sessions get human-readable titles for the session list sidebar:

1. **Auto-generation**: After the first assistant response in a user session, the agent generates a short title (≤ 8 words) from the conversation so far via a lightweight LLM call: *"Summarize this conversation start as a short title (max 8 words)."*
2. **Update heuristic**: Title is re-generated if the conversation topic shifts significantly (detected during memory extraction — if extracted memories are in a different domain than the title suggests). Maximum one re-generation per 20 messages.
3. **Manual rename**: User can rename any session via `PATCH /api/sessions/{id}` with `{"title": "My custom title"}`.
4. **Channel sessions**: use the channel + sender as default title (e.g., "Telegram: Alice", "Email: Project Update thread").
5. **Cron/webhook sessions**: use the job name or webhook label as title.

**Summary**: Updated periodically (every 20 messages or on session archive) via an LLM call that produces a 2–3 sentence summary of the conversation. Stored for quick preview on hover in the session list.

### 3.3 Session Tools (Agent-to-Agent Communication)

Agents communicate through session tools — the same pattern OpenClaw uses, adapted for our in-process model.

| Tool | Purpose | Behavior |
|---|---|---|
| `sessions_list` | Discover active sessions | Returns list filtered by kind, agent, recency. Visibility scoped by policy. |
| `sessions_history` | Read another session's transcript | Returns messages. Respects visibility scope. |
| `sessions_send` | Send message to another session | `timeout=0`: fire-and-forget. `timeout>0`: wait for reply. |
| `sessions_spawn` | Create sub-agent session | Returns immediately. Sub-agent runs async. Result announced back. |

**`sessions_send` behavior**:
- Enqueues message into target session
- If `timeout > 0`: waits for target agent to complete, returns reply
- If `timeout = 0`: returns `{status: "accepted", run_id}` immediately
- Inter-session messages tagged with `provenance: "inter_session"` for transcript clarity
- Reply-back ping-pong: up to `max_ping_pong_turns` (default 3) alternating turns. Either side returns `REPLY_SKIP` to stop.

**`sessions_spawn` behavior**:
- Creates isolated `agent:<id>:sub:<uuid>` session
- Sub-agent gets full tool set MINUS session tools (no sub-sub-agent spawning)
- Sub-agent inherits a scoped-down `SessionPolicy` (e.g., `WORKER` preset)
- Result announced back to parent session on completion
- Auto-archived after configurable timeout (default 60 minutes)

**Visibility scopes**:
- `self`: only the current session
- `tree`: current session + sessions spawned by it
- `agent`: any session belonging to the same agent
- `all`: cross-agent access (requires explicit policy)

Default: `tree` for spawned sub-agents. `agent` for main agent.

### 3.4 Message Model

The `Message` model is the core data unit flowing through sessions, prompt assembly, extraction, and the frontend. Every message in every session is a `Message`.

```python
class Message(BaseModel):
    id: str                              # UUID
    session_id: str                      # which session this belongs to
    role: Literal["system", "user", "assistant", "tool_result"]
    content: str                         # text content (markdown for assistant, plain for user)
    content_blocks: list[ContentBlock] = []  # structured content (images, files) — for multi-modal messages

    # --- Tool calls (assistant messages only) ---
    tool_calls: list[ToolCallRecord] | None = None  # tool calls made in this response
    tool_call_id: str | None = None      # for role="tool_result": which tool call this responds to

    # --- File references ---
    file_ids: list[str] = []             # files attached to or generated by this message

    # --- Branching (§3.5) ---
    parent_id: str | None = None         # previous message in the conversation thread
    active: bool = True                  # False = message is in an inactive branch (replaced by edit/regen)

    # --- Provenance ---
    provenance: Literal[
        "user_input",                    # typed by the user
        "assistant_response",            # generated by the agent
        "tool_result",                   # tool execution result
        "system_injected",               # system message (approval, notification, etc.)
        "inter_session",                 # received from another session via sessions_send
        "channel_inbound",               # received from an external channel (Telegram, email)
        "transcription",                 # audio transcription result
        "file_context",                  # auto-injected file preview (§21.4)
    ] = "user_input"

    # --- Compression ---
    compressed: bool = False             # True = this message replaced a batch of older messages
    compressed_source_ids: list[str] = []  # original message IDs that were compressed into this one

    # --- Cost tracking ---
    turn_cost_id: str | None = None      # reference to TurnCost record (assistant messages only)

    # --- Feedback (§3.6) ---
    feedback: MessageFeedback | None = None

    # --- Timestamps ---
    created_at: datetime
    updated_at: datetime | None = None

    # --- Model info (assistant messages only) ---
    model: str | None = None             # which model generated this (e.g., "anthropic:claude-sonnet-4-20250514")
    input_tokens: int | None = None
    output_tokens: int | None = None

class ContentBlock(BaseModel):
    type: Literal["text", "image", "file_ref"]
    text: str | None = None              # for type="text"
    file_id: str | None = None           # for type="image" or "file_ref"
    mime_type: str | None = None
    alt_text: str | None = None          # image description (from vision pipeline or user)

    # Frontend rendering by type:
    #   "text"     → rendered as markdown (same as message content)
    #   "image"    → inline thumbnail, click opens lightbox (§9.2a)
    #   "file_ref" → rendered as FileCard (§21.6) with type-appropriate
    #                preview and quick actions (open, reveal, download, view)

class ToolCallRecord(BaseModel):
    tool_call_id: str
    tool_name: str
    arguments: dict
    result: str | dict | None = None
    success: bool | None = None
    execution_time_ms: int | None = None
    approval_status: Literal["auto_approved", "user_approved", "user_denied"] | None = None

class MessageFeedback(BaseModel):
    rating: Literal["up", "down"]
    note: str | None = None              # optional text explanation
    created_at: datetime
```

**SQL schema** (extends the `messages` entry in §14.1):

```sql
CREATE TABLE messages (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(session_id),
    role            TEXT NOT NULL,       -- "system", "user", "assistant", "tool_result"
    content         TEXT NOT NULL DEFAULT '',
    content_blocks  TEXT,                -- JSON array of ContentBlock
    tool_calls      TEXT,                -- JSON array of ToolCallRecord
    tool_call_id    TEXT,                -- for tool_result messages
    file_ids        TEXT,                -- JSON array of file ID strings
    parent_id       TEXT REFERENCES messages(id),
    active          BOOLEAN NOT NULL DEFAULT 1,
    provenance      TEXT NOT NULL DEFAULT 'user_input',
    compressed      BOOLEAN NOT NULL DEFAULT 0,
    compressed_source_ids TEXT,          -- JSON array
    turn_cost_id    TEXT,
    feedback_rating TEXT,                -- "up" or "down"
    feedback_note   TEXT,
    feedback_at     TEXT,
    model           TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT
);
CREATE INDEX idx_messages_session ON messages(session_id, created_at);
CREATE INDEX idx_messages_parent ON messages(parent_id);
CREATE INDEX idx_messages_active ON messages(session_id, active);
```

### 3.5 Conversation Branching & Regeneration

Users can edit previous messages and regenerate assistant responses, creating a linear rewind model (not a full branch tree).

#### Supported operations

| Operation | Trigger | Behavior |
|---|---|---|
| **Regenerate** | User clicks "regenerate" on any assistant message | Mark that assistant message and all subsequent messages as `active=False`. Re-run the turn with the same preceding user message. New response gets `parent_id` pointing to the same parent as the original. |
| **Edit & resubmit** | User clicks "edit" on any user message | UI shows the message content in an editable input. On submit: mark the original user message and all subsequent messages as `active=False`. Insert a new user message with the edited content (`parent_id` = same parent as original). Trigger a new agent turn. |

#### How it works

```
Original conversation (all active=True):
    msg_1 (user)  →  msg_2 (assistant)  →  msg_3 (user)  →  msg_4 (assistant)

User edits msg_3:
    msg_1 (user, active)  →  msg_2 (assistant, active)
    msg_3 (user, active=False)  →  msg_4 (assistant, active=False)   ← deactivated
    msg_3b (user, active, parent=msg_2)  →  msg_4b (assistant, active)  ← new branch

Prompt assembly always uses: active=True messages only (in parent_id chain order)
```

#### Prompt assembly impact

The prompt assembly pipeline (§4.3a step 7 — session history) loads messages filtered by `active=True`. This naturally excludes replaced branches. The `parent_id` chain ensures correct ordering even when messages were inserted out of sequence.

#### Frontend UX

- **Regenerate button**: visible on every assistant message (refresh icon).
- **Edit button**: visible on every user message (pencil icon). Shows inline editor.
- Deactivated messages are hidden by default. A "show previous versions" toggle reveals them (grayed out, with timestamp).
- **No branch navigation**: this is a linear rewind, not ChatGPT-style branch switching. The active thread is always the latest.

#### API

```
POST /api/sessions/{id}/regenerate      — body: { "message_id": "msg_4" }
POST /api/sessions/{id}/edit            — body: { "message_id": "msg_3", "content": "new text" }
```

Both return the new turn's first `agent.run.stream` event via the WebSocket.

### 3.6 Message Feedback

Users can provide quality signals on assistant messages to help with memory extraction prioritization and future agent improvement.

| Action | UI Element | Effect |
|---|---|---|
| **Thumbs up** | 👍 icon on assistant message | Sets `feedback.rating = "up"` on the message |
| **Thumbs down** | 👎 icon on assistant message | Sets `feedback.rating = "down"`, optionally opens a text input for a note |

**Storage**: Feedback is stored directly on the `messages` table (`feedback_rating`, `feedback_note`, `feedback_at` columns) — no separate table needed.

**Effects**:
- **Memory extraction**: Messages with `rating = "up"` get a +0.2 confidence boost during extraction (§5.5 step 2). Messages with `rating = "down"` get a −0.3 confidence penalty (less likely to be extracted as memories).
- **Analytics**: `GET /api/sessions/analytics` includes feedback distribution (thumbs up/down counts per agent, per model) for quality tracking.
- **Future**: feedback data can inform model selection, soul tuning, and skill effectiveness metrics.

**API**:
```
POST /api/messages/{id}/feedback        — body: { "rating": "up" | "down", "note": "optional text" }
DELETE /api/messages/{id}/feedback       — remove feedback
```

### 3.7 Session Lifecycle & Idle Management

Sessions accumulate messages indefinitely unless the user explicitly archives or deletes them. This section defines the automated lifecycle behaviors that keep the session list manageable without data loss.

**Session states**:

| State | Meaning | Transitions |
|---|---|---|
| `active` | Session is in regular use | → `idle` (auto) or `archived` (manual) |
| `idle` | No messages for `session.idle_timeout` duration | → `active` (new message) or `archived` (manual/auto) |
| `archived` | Removed from active session list; data preserved | → `active` (manual unarchive) or deleted (manual) |

**Idle detection**:
- A background task checks `last_message_at` on all active sessions every 15 minutes.
- Sessions with `last_message_at` older than `session.idle_timeout` (default: 7 days) transition to `idle`.
- Idle sessions remain fully accessible but are visually de-emphasized in the sidebar (grayed out, sorted below active sessions).

**Auto-summarization on idle**:
- When a session transitions to `idle`, the system generates an auto-summary if `session.summary` is null or stale (last summary older than the most recent messages).
- Summary is generated via a lightweight LLM call (same as session title generation, §3.2) and stored in `session.summary`.
- This summary is used in the sidebar hover tooltip and in the session search results.

**Sub-agent session timeout**:
- Sub-agent sessions (non-user-initiated, spawned by workflows or agent delegation) have a separate timeout: `sub_agent_session_timeout` (default: 60 minutes).
- After timeout, the sub-agent session is automatically archived.
- If the sub-agent is mid-turn when timeout fires, the current turn completes before archival.

**Channel session accumulation**:
- Channel-bound sessions (Telegram, email, etc.) follow the same idle rules but are never auto-archived — channels expect persistent sessions.
- Instead, channel sessions that exceed `channel_session_message_cap` (default: 500 messages) trigger in-session compression (§5.12) automatically.

**Manual operations**:
```
POST /api/sessions/{id}/archive         — archive a session
POST /api/sessions/{id}/unarchive       — restore to active
DELETE /api/sessions/{id}               — permanent deletion (requires confirmation)
```

**Configuration** (`session.*` namespace):

```python
class SessionLifecycleConfig(BaseModel):
    idle_timeout_days: int = 7                    # days of inactivity before idle state
    auto_summarize_on_idle: bool = True           # generate summary when going idle
    sub_agent_session_timeout_min: int = 60       # sub-agent session timeout in minutes
    channel_session_message_cap: int = 500        # trigger compression after this many messages
    archive_idle_after_days: int | None = None    # auto-archive idle sessions after N additional days (null = never)
```

---

## 4) Agent Runtime

### 4.1 Agent Model

```python
class AgentConfig(BaseModel):
    agent_id: str
    name: str
    role: str                        # "main", "research", "code", "calendar", etc.
    soul: SoulConfig                 # personality, system prompt template, behavior rules
    default_model: str               # provider + model identifier
    fallback_provider_id: str | None = None  # fallback provider for circuit-breaker failover
    tools: list[str]                 # enabled tool group names
    skills: list[str]                # attached skill IDs
    default_policy: SessionPolicy    # default policy for sessions owned by this agent
    memory_scope: MemoryScope        # what memory this agent can access
    is_admin: bool = False           # can modify other agents' configs
    version: int = 1                 # optimistic concurrency control (§20.3b)
```

### 4.1a Soul Configuration

`SoulConfig` defines the agent's personality, behavioral rules, and system prompt template. It is the primary mechanism for shaping how an agent thinks, speaks, and behaves.

```python
class SoulConfig(BaseModel):
    # --- Identity ---
    persona: str = ""                    # who the agent is: name, personality, tone, style
                                         # e.g., "You are Tequila, a warm but efficient personal assistant..."
    instructions: list[str] = []         # behavioral rules and constraints
                                         # e.g., ["Always confirm before sending emails",
                                         #        "Prefer concise responses unless asked for detail"]

    # --- System prompt template ---
    system_prompt_template: str = DEFAULT_SYSTEM_PROMPT
                                         # Jinja2 template with variables:
                                         #   {{ persona }}      — persona text above
                                         #   {{ instructions }} — formatted instruction list
                                         #   {{ datetime }}     — current date/time
                                         #   {{ user_name }}    — user's name (from identity memories)
                                         #   {{ tools }}        — available tool descriptions (auto-injected)
                                         #   {{ skill_index }}  — Level 1 skill summaries (all assigned skills)
                                         #   {{ active_skills }}— Level 2 instructions for active skills
                                         #   {{ memory }}       — recalled memory context block
                                         #   {{ custom }}       — custom variables from metadata dict

    # --- Behavior modifiers ---
    tone: Literal["professional", "casual", "friendly", "formal", "custom"] = "friendly"
    verbosity: Literal["concise", "balanced", "detailed"] = "balanced"
    language: str = "en"                 # preferred response language (ISO 639-1)
    emoji_usage: Literal["none", "minimal", "normal"] = "minimal"

    # --- Response formatting ---
    prefer_markdown: bool = True         # use markdown formatting in responses
    prefer_lists: bool = False           # prefer bullet points over prose when applicable
    code_block_style: Literal["fenced", "inline"] = "fenced"

    # --- Safety & boundaries ---
    refuse_topics: list[str] = []        # topics the agent should decline to engage with
    escalation_phrases: list[str] = []   # phrases that trigger handoff to main agent (sub-agents only)

    # --- Custom metadata ---
    metadata: dict = {}                  # arbitrary key-value pairs available in template as {{ custom.key }}
```

#### Default system prompt template

```
DEFAULT_SYSTEM_PROMPT = """
{{ persona }}

{% if instructions %}
## Rules
{% for rule in instructions %}
- {{ rule }}
{% endfor %}
{% endif %}

## Current context
- Date/time: {{ datetime }}
{% if user_name %}- User: {{ user_name }}{% endif %}

{% if skill_index %}
## Available Skills
{{ skill_index }}
{% endif %}

{% if active_skills %}
## Active Skills
{{ active_skills }}
{% endif %}

{% if memory %}
## Memory
{{ memory }}
{% endif %}

## Available tools
{{ tools }}
"""
```

The template is rendered at prompt assembly time (§4.3). Users can fully customize the template via the **Soul Editor** in the UI, or use the `POST /api/agents/{id}/soul/generate` endpoint for LLM-assisted soul generation.

#### Soul generation flow

1. User provides a free-text description: *"I want an agent that helps me manage my freelance business. Professional but friendly tone."*
2. LLM generates a `SoulConfig` from the description: persona, instructions, tone, verbosity.
3. User reviews and edits in the Soul Editor.
4. Saved to `AgentConfig.soul`.

### 4.2 Agent Hierarchy

- **Main agent**: `is_admin=True`. Can modify any agent's config. Sees all sessions. Default policy is `ADMIN`. User's primary conversational interface.
- **Sub-agents**: `is_admin=False`. Can only modify their own state. Visibility scoped to their session tree. Default policy is restrictive (per agent config).

### 4.2a Escalation Protocol

When a sub-agent encounters a situation it cannot handle, the conversation must be handed off to the main agent (or the user's designated escalation target). This applies to both automated detection and explicit user requests.

**Trigger conditions**:

| Trigger | Detection Method | Example |
|---|---|---|
| **Phrase match** | Substring/regex match against `SoulConfig.escalation_phrases` | User says "let me talk to the main agent" |
| **Explicit tool call** | Sub-agent calls `escalate()` tool | Agent determines the task is outside its scope |
| **Repeated failure** | 3 consecutive tool errors or 2 provider failures within one turn | Sub-agent is stuck in a loop |
| **Policy violation attempt** | Sub-agent requests a tool/action blocked by its `SessionPolicy` | Research agent tries to send an email |

**Escalation flow**:

```
1. Trigger detected (phrase / tool call / failure count / policy block)
2. Sub-agent turn is interrupted (current streaming response is finalized with an escalation notice)
3. Gateway emits `escalation.triggered` event:
   {
     "type": "escalation.triggered",
     "source_agent_id": "research-agent",
     "source_session_id": "sess_abc",
     "target_agent_id": "main",          // or null → route to main by default
     "reason": "phrase_match",            // | "tool_call" | "repeated_failure" | "policy_block"
     "summary": "User asked to speak to main agent after research question about legal advice.",
     "last_n_messages": 5                 // number of recent messages included for context
   }
4. Gateway creates or resumes a session with the target agent
5. Context injection: the target agent receives a system-level context block:
   "Escalated from [Research Agent] in session sess_abc.
    Reason: User requested handoff.
    Recent conversation summary: [auto-generated summary of last N messages]"
6. Target agent responds, acknowledging the handoff
```

**Context transfer strategy**:
- **Default**: Auto-generated summary of the last N messages (configurable, default 5) plus the escalation reason. Keeps context compact.
- **Full history**: If `escalation.include_full_history = true` in config, the entire sub-agent session message list is appended to the target session as a compressed context block (§5.12).
- **Attachments**: Any files or uploads from the sub-agent session are linked to the target session via `file_ids`.

**What the user sees**:
- In the sub-agent's chat: a system message — *"This conversation has been escalated to [Main Agent]. Switching now..."*
- The UI automatically switches to the target agent's session.
- In the target agent's chat: a system message — *"Conversation escalated from [Research Agent]: [reason]. Here's what was discussed: [summary]"*
- The target agent then continues the conversation seamlessly.

**Configuration** (in `SoulConfig`):
- `escalation_phrases`: list of trigger phrases (already defined)
- Additional config in the `escalation.*` namespace (see §14.4):

```python
class EscalationConfig(BaseModel):
    enabled: bool = True                        # enable/disable escalation for this agent
    target_agent_id: str | None = None          # override: escalate to specific agent (default: main)
    include_full_history: bool = False           # transfer full session history vs summary
    context_message_count: int = 5              # how many recent messages to summarize
    max_consecutive_failures: int = 3           # failure count before auto-escalation
    notify_user: bool = True                    # show UI notification on escalation
```

**API**:
```
POST /api/sessions/{id}/escalate       — manually trigger escalation from a session
  Body: { "reason": "optional user-provided reason" }
  Response: { "target_session_id": "...", "target_agent_id": "..." }
```

### 4.3 Turn Loop

The core agent execution cycle, unchanged in concept from v1 but now session-routed:

1. Gateway routes `inbound.message` to the correct session's agent
2. Agent runtime assembles prompt (see §4.3a Prompt Assembly Pipeline below)
3. Provider streaming call with tool definitions
4. Stream tokens emitted as `agent.run.stream` events (gateway forwards to subscribers)
5. If tool call detected in stream:
   a. Parse tool name + arguments from provider-specific format (§4.6a)
   b. Gateway checks `SessionPolicy.allowed_tools`
   c. If tool in `require_confirmation` → emit `approval_request` event, wait for user response
   d. Execute tool, inject `tool_result` message, **loop back to step 2** (re-assemble prompt with tool result)
6. If no tool call → final response persisted to session, emitted as `agent.run.complete`
7. Post-turn: trigger memory extraction check (§5.5), update budget tracker (§23), emit audit event (§12)

**Max iterations**: the tool-call loop is capped at `max_tool_rounds` (default: 25) per turn. If exceeded, the agent receives a system message: *"Tool call limit reached for this turn. Please provide your response."*

### 4.3a Prompt Assembly Pipeline

Prompt assembly is the most critical runtime operation. It converts the agent's configuration, memory, session history, and current message into a provider-ready message list within the context budget.

**Assembly order** (each step produces a block; blocks are assembled into the final message list):

```
Step 1: SYSTEM PROMPT RENDER
    → Render SoulConfig.system_prompt_template (Jinja2)
    → Inject: persona, instructions, datetime, user_name, tone/verbosity directives
    → This becomes the system message (message[0])

Step 2: ALWAYS-RECALL MEMORIES
    → Load all memories with always_recall=True (identity, preferences)
    → Load all pinned memories for this session
    → Load active unexpired task memories
    → Format as a "## Memory" block inside the system message
    → Budget: ContextBudget.memory_always_recall_budget (default 500 tokens)

Step 3: PER-TURN MEMORY RECALL
    → Run recall pipeline stage 2 (§5.6) against the current user message
    → Vector search + FTS + entity-aware expansion
    → Deduplicate against step 2 results
    → Format as additional memory context
    → Budget: ContextBudget.memory_recall_budget (default 2000 tokens)

Step 3a: KNOWLEDGE SOURCE CONTEXT
    → Results from knowledge source federation (§5.14, recall pipeline step 4a–4b)
    → Only sources with auto_recall=True and agent access
    → Format as a "## Knowledge Sources" block (separate from "## Memory")
    → Each chunk attributed: [source_id] content...
    → Budget: ContextBudget.knowledge_source_budget (default 1500 tokens)

Step 4: SKILL CONTEXT — THREE-LEVEL PROGRESSIVE DISCLOSURE (see §4.5.2 for full logic)

    Step 4a: SKILL INDEX (Level 1 — always loaded)
    → For ALL skills assigned to this agent (regardless of activation_mode):
      → Render compact index: skill_id, name, summary, activation_mode
      → If skill has Level 3 resources: append "(has N resources)" hint
    → Format as "## Available Skills" indexed list in system prompt
    → Budget: ContextBudget.skill_index_budget (default 500 tokens)
    → If index exceeds budget: prioritize by priority, drop lowest-priority summaries

    Step 4b: SKILL INSTRUCTIONS (Level 2 — loaded for active skills)
    → Collect always-on skills (activation_mode="always")
    → Evaluate trigger patterns against current user message → add matched skills
    → Include manually activated / agent-requested skills (session-scoped)
    → Exclude manually deactivated skills
    → Verify required_tools availability for each candidate skill
    → Sort by priority → inject instructions until budget exhausted
    → Budget: ContextBudget.skill_instruction_budget (default 1500 tokens)

    Note: Level 3 resources are NOT loaded in prompt assembly.
    The agent fetches them on-demand via skill_read_resource tool (tool result, not system prompt).

Step 5: TOOL DEFINITIONS
    → Gather all enabled tools (core + plugin tool groups)
    → Filter by SessionPolicy.allowed_tools
    → Format as provider-specific tool schema (§4.6a)
    → Budget: ContextBudget.tool_schema_budget (default 2000 tokens)
    → If over budget: prioritize recently-used tools, drop least-used

Step 6: FILE CONTEXT INJECTION
    → If current message has file_ids: run MIME-type routing (§21.4)
    → Inject structured previews (PDF summary, CSV schema, image description, etc.)
    → Budget: ContextBudget.file_context_budget (default 3000 tokens)

Step 7: SESSION HISTORY
    → Load session messages (newest first, up to remaining budget)
    → Apply compression summaries where available (replace raw messages with summaries)
    → Always include: most recent N messages (configurable, default 4)
    → Budget: remaining tokens after steps 1–6 (including step 3a)

Step 8: CURRENT MESSAGE
    → Append the incoming user message (always included, never trimmed)
```

**Final message list structure** sent to the provider:

```python
messages = [
    {"role": "system", "content": rendered_system_prompt},    # steps 1–4 merged
    # ... session history messages (step 7) ...
    {"role": "user", "content": current_message},             # step 8
]
# tool definitions passed separately via provider API (step 5)
```

**Budget allocation and priority trimming**:

When the assembled prompt exceeds `ContextBudget.max_context_tokens - reserved_for_response`:

```
Priority (never trimmed → first to trim):
  NEVER trimmed:
    1. Current user message
    2. System prompt (persona + rules)  — template can be shortened but not removed
    3. Most recent N messages            — default N=4

  Trimmed (first to trim → last to trim):
    4. Older session history             — trim first (replaced by compression summary)
    5. File context injections           — reduce: shorter previews
    6. Skill instructions (Level 2)      — reduce: keep most relevant active skills only
    7. Knowledge source results          — reduce: fewer chunks, higher threshold (§5.14)
    8. Per-turn recalled memories        — reduce: fewer results, higher similarity threshold
    9. Tool definitions                  — reduce: drop least-used tools first
   10. Skill index (Level 1 summaries)   — reduce: keep highest-priority skills only
   11. Always-recall memories            — last resort: trim lowest-priority always-recall memories
```

### 4.4 Agent CRUD

- Create / list / get / update / delete agents
- Clone agent (deep copy with new ID)
- Import / export agent config (JSON)
- Reset agent (clear session history, keep config)
- Agent soul read / update / generate (LLM-assisted setup)

### 4.5 Skills and Tool Groups

#### 4.5.0 Three-Level Progressive Disclosure

Skills use a **three-level progressive disclosure** model to minimize baseline token cost while giving the agent full awareness of its capabilities. This is inspired by Claude Code's SKILL.md pattern but adapted for Tequila's in-process architecture.

```
Level 1 — SKILL INDEX (always loaded)
    Every assigned skill contributes a compact summary (~20-50 tokens) to the system prompt.
    The agent always knows what skills exist and when each is relevant.
    Cost: ~30 tokens × N skills. With 20 skills ≈ 600 tokens baseline.

Level 2 — INSTRUCTIONS (loaded on activation or agent request)
    The detailed how-to text: step-by-step procedures, output formats, constraints.
    Loaded when a skill's trigger fires, it's always-on, or the agent proactively
    requests it via skill_get_instructions. Injected into the system prompt.
    Cost: ~100-300 tokens per activated skill. Typically 1-3 active per turn.

Level 3 — RESOURCES (loaded only on explicit agent request)
    Deep reference material: style guides, checklists, templates, example outputs.
    Never auto-loaded. The agent navigates to them via skill_read_resource tool.
    Returned as tool results, not system prompt injection.
    Cost: 0 tokens in prompt unless agent explicitly fetches.
```

**Token efficiency comparison** (15 assigned skills, 2 active per turn):

| Model | Baseline cost | Active skill cost | Total |
|---|---|---|---|
| Flat (old) | 0 tokens (no index) | 2 × 200 = 400 tokens | ~400 tokens, but agent blind to 13 other skills |
| Three-level | 15 × 30 = 450 tokens | 2 × 200 = 400 tokens | ~850 tokens, full skill awareness |

The three-level model costs ~450 more tokens for the index but gains: (a) agent can proactively load any skill it deems relevant, (b) Level 3 resources avoid bloating prompts with reference material, (c) skill count scales linearly at ~30 tokens per skill instead of all-or-nothing.

#### 4.5.1 Skill Data Model

A **skill** is a reusable, structured prompt package that teaches the agent *how* to perform a specific kind of task. Skills are the bridge between raw tools and effective behavior — a tool provides the capability, a skill provides the know-how.

The model is organized around the three disclosure levels:

```python
class SkillDef(BaseModel):
    skill_id: str                        # unique identifier (e.g., "code_review", "meeting_notes")
    name: str                            # display name (e.g., "Code Review")
    description: str                     # one-line label for UI lists and search results
    version: str = "1.0.0"              # semver for import/export compatibility

    # --- Level 1: Skill Index (always in system prompt) ---
    summary: str                         # 1-3 sentence description of what this skill does and
                                         # when the agent should use it. This is ALL the agent sees
                                         # by default in the ## Available Skills index block.
                                         # Target: 20-50 tokens. Write for the agent, not the user.
                                         # Example: "Code review skill. Use when the user asks to
                                         #   review code, a PR, or analyze code quality. Provides
                                         #   structured severity-rated findings."

    # --- Level 2: Instructions (loaded when skill activates) ---
    instructions: str                    # detailed how-to text injected into the system prompt
                                         # when this skill is active. Supports Jinja2 variables:
                                         #   {{ tools }} — list of this skill's required tool names
                                         #   {{ config }} — skill-specific config values
                                         # Example: "When asked to review code, follow these steps:\n
                                         #           1. Read the file with fs_read_file\n
                                         #           2. Analyze for bugs, style issues, and improvements\n
                                         #           3. Provide a structured review with severity levels"

    # --- Level 3: Resources (stored in skill_resources table, see SkillResource) ---
    # Not stored on this model. Agent accesses via skill_list_resources / skill_read_resource tools.
    # Resources are deep reference material: style guides, checklists, templates, examples.

    # --- Tool binding ---
    required_tools: list[str] = []       # tool names this skill depends on (e.g., ["fs_read_file", "fs_write_file"])
                                         # if any required tool is unavailable to the agent, skill is inactive
    recommended_tools: list[str] = []    # tools that enhance the skill but aren't required

    # --- Activation ---
    activation_mode: Literal["always", "trigger", "manual"] = "trigger"
    trigger_patterns: list[str] = []     # regex patterns matched against user messages (case-insensitive)
                                         # e.g., ["review.*code", "code.*review", "PR review", "pull request"]
    trigger_tool_presence: list[str] = [] # skill activates if ALL these tool groups are enabled on the agent
                                         # e.g., ["file_tools", "code_tools"] → auto-attach when agent has both
    priority: int = 100                  # lower = higher priority (for budget allocation when multiple skills match)

    # --- Metadata ---
    tags: list[str] = []                 # categorization tags (e.g., ["development", "analysis"])
    author: str = "system"               # "system" for built-in, "user" for user-created, or custom name
    is_builtin: bool = False             # True for skills shipped with Tequila
    created_at: datetime
    updated_at: datetime


class SkillResource(BaseModel):
    """Level 3 reference material linked to a skill. Fetched on-demand by the agent."""
    resource_id: str                     # UUID
    skill_id: str                        # parent skill ID
    name: str                            # display name (e.g., "Python Style Guide", "Review Checklist")
    description: str                     # brief description so agent knows what's inside
                                         # (shown in skill_list_resources output)
    content: str                         # the actual reference material (markdown)
    content_tokens: int | None = None    # pre-computed token count for budget awareness
    created_at: datetime
    updated_at: datetime
```

#### 4.5.2 Skill Activation & Loading (Three-Level)

The three-level model splits prompt assembly into two phases: an always-present **skill index** (Level 1) and **conditionally loaded instructions** (Level 2). Level 3 resources are never in the prompt — the agent fetches them via tools.

**What each level loads and when:**

| Level | What | When loaded | Where it appears |
|---|---|---|---|
| **1 — Index** | `summary` for ALL assigned skills | Every turn, unconditionally | `## Available Skills` block in system prompt |
| **2 — Instructions** | `instructions` for activated skills only | On activation (always/trigger/manual/agent-requested) | `## Active Skills` block in system prompt |
| **3 — Resources** | `content` of a `SkillResource` | Only when agent calls `skill_read_resource` | Tool result (not in system prompt) |

**Activation modes** (determine when Level 2 loads):

| Mode | When Level 2 instructions are injected | Use case |
|---|---|---|
| `always` | Every turn, unconditionally | Core behavioral skills (e.g., "response formatting", "safety guidelines") |
| `trigger` | When user message matches a `trigger_pattern` OR agent has all `trigger_tool_presence` groups enabled | Task-specific skills (e.g., "code review" activates on "review my code") |
| `manual` | Only when user explicitly enables via UI or agent activates via `skill_activate` tool | Specialized skills the user wants on-demand (e.g., "legal document review") |

**Agent-initiated loading**: Because the agent always sees the Level 1 index, it can proactively decide to load a skill's instructions even when no trigger fired. It does this by calling `skill_get_instructions` (returns instructions as a tool result for one-off reference) or `skill_activate` (loads instructions into the system prompt for the rest of the session). This is the key advantage over the old flat model — the agent has agency over which skills it uses.

**Per-turn skill resolution** (runs during prompt assembly step 4):

```
Step 4a: SKILL INDEX (Level 1 — always loaded)
    → For ALL skills assigned to this agent (regardless of activation_mode):
      → Render compact index: skill_id, name, summary, activation_mode
      → If skill has Level 3 resources: append "(has N resources)" hint
    → Format as "## Available Skills" indexed list in system prompt
    → Budget: ContextBudget.skill_index_budget (default 500 tokens)
    → If index exceeds budget: prioritize by priority, drop lowest-priority summaries

Step 4b: SKILL INSTRUCTIONS (Level 2 — loaded for active skills)
    1. ALWAYS SKILLS
       → Collect all skills assigned to this agent with activation_mode="always"
       → These always get Level 2 loaded (subject to budget)

    2. TRIGGER MATCHING
       → For each skill with activation_mode="trigger" assigned to this agent:
         a. Pattern match: test each trigger_pattern regex against the current user message
         b. Tool-presence match: check if agent's enabled tool groups ⊇ trigger_tool_presence
         c. If (a) matches OR (b) is satisfied → skill is activated for this turn

    3. MANUAL / AGENT-REQUESTED SKILLS
       → Check session state for manually activated skills (via UI toggle or agent tool)
       → These persist until deactivated (session-scoped, not per-turn)

    4. TOOL AVAILABILITY CHECK
       → For each candidate skill: verify required_tools are all available to the agent
       → If any required tool is missing/disabled → skip the skill, log a warning

    5. BUDGET FIT
       → Sort activated skills by priority (lower number = higher priority)
       → Inject instructions until skill_instruction_budget (default 1500 tokens) is reached
       → Skills that don't fit are dropped (lowest priority first)
       → If no skills are active, the ## Active Skills block is omitted

    Note: Level 3 resources are NEVER loaded in prompt assembly.
    The agent accesses them on-demand via skill_list_resources / skill_read_resource tools.
```

**System prompt rendering** (visual structure the agent sees):

```
## Available Skills
1. **code_review** — Code review skill. Use when the user asks to review code, a PR,
   or analyze code quality. Provides structured severity-rated findings. (has 2 resources)
2. **meeting_notes** — Meeting notes skill. Use after meetings to extract action items,
   decisions, and attendees. Saves structured task memories.
3. **email_drafting** — Email drafting skill. Use when composing professional emails.
   Structures subject, greeting, body, sign-off. Confirms before sending.
   [... more assigned skills ...]

## Active Skills
### Code Review (code_review)
When asked to review code, follow these steps:
1. Read the file with fs_read_file
2. Analyze for bugs, style issues, and improvements
3. Provide a structured review with severity levels
   [... full instructions ...]
```

**Session-level skill state:**

```python
class SessionSkillState(BaseModel):
    manually_activated: list[str] = []   # skill_ids toggled on by user or agent
    manually_deactivated: list[str] = [] # skill_ids explicitly suppressed for this session
    last_triggered: dict[str, datetime] = {}  # skill_id → last trigger time (for analytics)
```

Stored on the session record. Allows per-session overrides without changing the agent's global skill assignment.

#### 4.5.3 Skill Assignment

Skills are attached to agents via `AgentConfig.skills: list[str]` (skill IDs). An agent only considers skills in its assignment list during activation — global skills are not automatically available to all agents.

**Assignment rules:**
- **Admin agents** can be assigned any skill.
- **Sub-agents** can be assigned skills by the admin agent or user.
- **Auto-suggest**: when a new tool group is enabled on an agent, the UI suggests skills whose `trigger_tool_presence` matches. The user confirms attachment.
- **Skill removal**: removing a skill from an agent's list immediately stops it from activating. No data is lost — the skill definition remains in the skill store.

#### 4.5.4 Built-in Skills

Tequila ships with a starter set of built-in skills (`is_builtin=True`). These provide effective patterns for common tasks and serve as templates for user-created skills.

| Skill ID | Name | Summary (Level 1) | Activation | Required Tools | Resources (Level 3) |
|---|---|---|---|---|---|
| `code_review` | Code Review | Code review skill. Use when reviewing code, PRs, or analyzing code quality. Provides structured severity-rated findings. | trigger: `review.*code\|code.*review\|PR review` | `fs_read_file` | "Review Checklist", "Severity Definitions" |
| `meeting_notes` | Meeting Notes | Meeting notes skill. Use after meetings to extract action items, decisions, and attendees. Saves structured task memories. | trigger: `meeting.*notes\|summarize.*meeting\|minutes` | `memory_save` | — |
| `email_drafting` | Email Drafting | Email drafting skill. Use when composing professional emails. Structures subject, greeting, body, sign-off. Confirms before sending. | trigger: `draft.*email\|write.*email\|compose.*email` | `gmail_send` or `email_send` | "Tone Guide" |
| `research` | Research Assistant | Research skill. Use when the user asks to research, investigate, or find out about a topic. Multi-source synthesis with citations. | trigger: `research\|find out about\|look into\|investigate` | `web_search`, `web_fetch` | "Citation Format Guide" |
| `data_analysis` | Data Analysis | Data analysis skill. Use when analyzing data, CSVs, or spreadsheets. Explore schema, run queries, generate insights. | trigger: `analyze.*data\|data.*analysis\|csv.*query\|spreadsheet` | `csv_open`, `csv_query` | — |
| `document_creation` | Document Creation | Document creation skill. Use when creating reports, documents, presentations, or PDFs. Follows outline → draft → format → export workflow. | trigger: `create.*document\|write.*report\|generate.*pdf\|create.*presentation\|make.*slides` | `pdf_create` or `pptx_create` or `html_presentation_create` | "Document Templates" |
| `task_management` | Task Manager | Task management skill. Use when tracking tasks, todos, deadlines, or reminders. Stores tasks as memories with due dates. | trigger: `tasks?\b\|todo\|deadline\|remind me` | `memory_save`, `memory_search` | — |

Built-in skills cannot be deleted but can be deactivated per agent. Users can clone a built-in skill to customize it.

#### 4.5.5 Skill CRUD & Import/Export

**API:**

```
GET    /api/skills                       # list all skills (filter: builtin, tags, author)
POST   /api/skills                       # create a new skill
GET    /api/skills/{id}                  # skill detail
PATCH  /api/skills/{id}                  # update skill
DELETE /api/skills/{id}                  # delete skill (not built-in)
POST   /api/skills/import               # import skill from JSON/YAML
GET    /api/skills/{id}/export           # export skill as JSON/YAML
POST   /api/skills/{id}/clone           # clone skill (creates editable copy)
```

**Agent skill assignment:**

```
GET    /api/agents/{id}/skills           # list skills assigned to agent
POST   /api/agents/{id}/skills           # assign skill(s) to agent
DELETE /api/agents/{id}/skills/{skill_id} # remove skill from agent
```

**Import/export format** (JSON or YAML):

```json
{
  "tequila_skill": "1.1",
  "skill_id": "code_review",
  "name": "Code Review",
  "description": "Structured code review with severity ratings",
  "version": "1.0.0",
  "summary": "Code review skill. Use when reviewing code, PRs, or analyzing code quality. Provides structured severity-rated findings.",
  "instructions": "When asked to review code, follow these steps:\n1. Read the file with fs_read_file\n2. Analyze for bugs, style issues, and improvements\n3. Rate each finding: critical / warning / info\n4. Output a structured review with a summary",
  "resources": [
    {
      "name": "Review Checklist",
      "description": "Standard checklist covering security, performance, style, and correctness",
      "content": "## Code Review Checklist\n- [ ] No hardcoded secrets\n- [ ] Error handling covers edge cases\n..."
    }
  ],
  "required_tools": ["fs_read_file"],
  "recommended_tools": ["fs_write_file"],
  "activation_mode": "trigger",
  "trigger_patterns": ["review.*code", "code.*review", "PR review"],
  "trigger_tool_presence": ["file_tools"],
  "priority": 100,
  "tags": ["development", "code-quality"],
  "author": "Tequila Team"
}
```

Import validates the schema, checks for ID conflicts (prompt rename or overwrite), and registers the skill in the store. Resources in the import payload are created as `SkillResource` records linked to the skill. Format version `1.1` indicates three-level model; importers should accept `1.0` payloads (with `prompt_fragment` instead of `instructions` + `summary`) for backward compatibility.

#### 4.5.6 Agent Tools for Skill Management

Agents can navigate all three skill levels at runtime:

| Tool | Safety | Level | Description |
|---|---|---|---|
| `skill_list` | `read_only` | 1 | List skills assigned to this agent with Level 1 summaries and activation status |
| `skill_search` | `read_only` | 1 | Search all available skills by name, tags, or description |
| `skill_activate` | `side_effect` | 1→2 | Activate a skill for the current session — its Level 2 instructions will be injected into subsequent system prompts (adds to `manually_activated`) |
| `skill_deactivate` | `side_effect` | 2→1 | Deactivate a skill for the current session — removes Level 2 from prompt, Level 1 summary remains visible (adds to `manually_deactivated`) |
| `skill_get_instructions` | `read_only` | 2 | Read Level 2 instructions for a skill without activating it for the session. Returns instructions as a tool result for one-off reference. Useful when the agent wants to check a skill's procedure without committing to session-wide activation |
| `skill_list_resources` | `read_only` | 3 | List available Level 3 resources for a skill (names + descriptions). Helps the agent decide which resource to fetch |
| `skill_read_resource` | `read_only` | 3 | Fetch a Level 3 resource by skill_id + resource name. Returns the full resource content in the tool result |

**Agent navigation flow example:**

```
User: "Can you review my Python code?"

1. Agent sees Level 1 index → code_review skill summary is visible
2. Trigger pattern fires → Level 2 instructions auto-injected
3. Agent reads instructions, starts review
4. Agent decides it needs the style checklist → calls skill_list_resources("code_review")
5. Sees: [{"name": "Review Checklist", "description": "Standard checklist..."}, ...]
6. Agent calls skill_read_resource("code_review", "Review Checklist")
7. Receives full checklist content → uses it to structure the review
```

This three-level navigation gives the agent **agency** over its skill usage. It always knows what skills exist (Level 1), can load detailed instructions on demand (Level 2), and can drill into reference material when needed (Level 3) — without bloating every prompt with content that may not be relevant.

#### 4.5.7 Skill Store

Skills and their Level 3 resources are stored in two SQLite tables:

```sql
-- Skills table (Level 1 + Level 2 content)
CREATE TABLE skills (
    skill_id        TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL,              -- UI label / search text
    version         TEXT NOT NULL DEFAULT '1.0.0',
    summary         TEXT NOT NULL DEFAULT '',   -- Level 1: agent-facing index entry (20-50 tokens)
    instructions    TEXT NOT NULL DEFAULT '',   -- Level 2: detailed how-to text
    required_tools  TEXT NOT NULL DEFAULT '[]',       -- JSON array
    recommended_tools TEXT NOT NULL DEFAULT '[]',     -- JSON array
    activation_mode TEXT NOT NULL DEFAULT 'trigger',
    trigger_patterns TEXT NOT NULL DEFAULT '[]',      -- JSON array
    trigger_tool_presence TEXT NOT NULL DEFAULT '[]', -- JSON array
    priority        INTEGER NOT NULL DEFAULT 100,
    tags            TEXT NOT NULL DEFAULT '[]',       -- JSON array
    author          TEXT NOT NULL DEFAULT 'user',
    is_builtin      BOOLEAN NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_skills_tags ON skills(tags);
CREATE INDEX idx_skills_builtin ON skills(is_builtin);

-- Skill resources table (Level 3 content)
CREATE TABLE skill_resources (
    resource_id     TEXT PRIMARY KEY,
    skill_id        TEXT NOT NULL REFERENCES skills(skill_id) ON DELETE CASCADE,
    name            TEXT NOT NULL,              -- display name (e.g., "Review Checklist")
    description     TEXT NOT NULL DEFAULT '',   -- brief description for skill_list_resources output
    content         TEXT NOT NULL,              -- the actual reference material (markdown)
    content_tokens  INTEGER,                    -- pre-computed token count for budget awareness
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_skill_resources_skill ON skill_resources(skill_id);
```

Agent-to-skill assignment is stored on `AgentConfig.skills` (the agent config is already persisted). Session skill state is stored on the session record.

**Resource CRUD API:**

```
GET    /api/skills/{id}/resources                # list resources for a skill
POST   /api/skills/{id}/resources                # add resource to a skill
GET    /api/skills/{id}/resources/{resource_id}   # get resource content
PATCH  /api/skills/{id}/resources/{resource_id}   # update resource
DELETE /api/skills/{id}/resources/{resource_id}   # delete resource
```

#### 4.5.8 Tool Groups

Tools are organized into named **tool groups** for convenient enable/disable at the agent level:

| Group Name | Tools | Description |
|---|---|---|
| `file_tools` | `fs_list_dir`, `fs_read_file`, `fs_write_file`, `fs_search` | Local filesystem operations |
| `web_tools` | `web_search`, `web_fetch` | Web search and content extraction |
| `code_tools` | `code_exec` | Code execution |
| `vision_tools` | `vision_describe`, `vision_extract_text`, `vision_compare`, `vision_analyze` | Image understanding |
| `memory_tools` | `memory_save`, `memory_update`, `memory_forget`, `memory_search`, `memory_list`, `memory_pin`, `memory_unpin`, `memory_link`, `memory_extract_now` | Memory management |
| `entity_tools` | `entity_create`, `entity_merge`, `entity_update`, `entity_search` | Entity management |
| `session_tools` | `sessions_list`, `sessions_history`, `sessions_send`, `sessions_spawn` | Cross-session interaction |
| `knowledge_tools` | `kb_search`, `kb_list_sources` | External knowledge source access |
| `skill_tools` | `skill_activate`, `skill_deactivate`, `skill_list`, `skill_search`, `skill_get_instructions`, `skill_list_resources`, `skill_read_resource` | Skill navigation (3-level) |
| `plugin:<plugin_id>` | Per-plugin tool set | Dynamically created when a plugin registers tools |

**Agent configuration:**
- `AgentConfig.tools: list[str]` — enabled tool group names
- Per-agent granular override: enable/disable individual tools within a group via `SessionPolicy.allowed_tools` and `SessionPolicy.require_confirmation`
- Tool group listing API: `GET /api/tools/groups` — returns all groups with their tools and descriptions for the UI configuration panel

### 4.6 Provider Abstraction Layer

LLM providers are abstracted behind a common interface so agents can use different providers/models and failover is clean:

```python
class LLMProvider(ABC):
    provider_id: str                      # "openai", "anthropic", "ollama", etc.

    @abstractmethod
    async def stream_completion(
        self, messages: list[Message], model: str,
        tools: list[ToolDef] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        response_format: ResponseFormat | None = None,
    ) -> AsyncIterator[ProviderStreamEvent]: ...

    @abstractmethod
    async def count_tokens(self, messages: list[Message], model: str) -> int: ...

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]: ...

    def get_model_capabilities(self, model: str) -> ModelCapabilities: ...
    def cost_per_token(self, model: str) -> CostRate: ...
```

**Provider registry**:
- Providers registered at startup from config (API keys or OAuth tokens)
- Each agent config has `default_model` in format `provider:model` (e.g., `anthropic:claude-sonnet-4-20250514`)
- Provider failover: configurable fallback chain (`anthropic → openai → ollama`)
- Adding a new provider = implement `LLMProvider`, register in provider registry

**Future consideration**: LLM providers could become a plugin type (`plugin_type: "provider"`), making it possible to add Gemini, Mistral, or other custom providers without code changes. Currently they're registered in-code for simplicity. (Note: Ollama already has a first-class adapter — see §4.6c.)

### 4.6a Tool-Calling Protocol

The turn loop's tool-calling mechanism is the most complex part of the provider abstraction. Each provider uses a different wire format, but the agent runtime works with a unified internal representation.

#### Internal tool definition model

```python
class ToolDef(BaseModel):
    name: str                             # e.g., "fs_read_file"
    description: str
    parameters: dict                      # JSON Schema for the tool's input
    safety: Literal["read_only", "side_effect", "destructive", "critical"]

class ResponseFormat(BaseModel):
    type: Literal["text", "json_object"] = "text"
    json_schema: dict | None = None       # for structured output / JSON mode
```

#### Provider-specific formatting

Each `LLMProvider` implementation is responsible for converting `ToolDef` to the provider's native format:

| Provider | Tool format | Tool call format | Tool result format |
|---|---|---|---|
| **Anthropic** | `tools: [{ name, description, input_schema }]` | `content: [{ type: "tool_use", id, name, input }]` | `{ role: "user", content: [{ type: "tool_result", tool_use_id, content }] }` |
| **OpenAI** | `tools: [{ type: "function", function: { name, description, parameters } }]` | `tool_calls: [{ id, type: "function", function: { name, arguments } }]` | `{ role: "tool", tool_call_id, content }` |
| **Ollama** | Same as OpenAI format (OpenAI-compatible API) | Same as OpenAI | Same as OpenAI |

The provider adapter handles this translation transparently. The agent runtime never sees provider-specific formats.

#### Streaming event model

`stream_completion()` yields a sequence of `ProviderStreamEvent` objects. The agent runtime processes these to detect text output, tool calls, and errors:

```python
class ProviderStreamEvent(BaseModel):
    kind: Literal[
        "text_delta",         # incremental text token
        "tool_call_start",    # new tool call detected (name + call ID)
        "tool_call_delta",    # incremental tool call argument JSON
        "tool_call_end",      # tool call arguments complete, ready to execute
        "thinking_delta",     # reasoning/thinking tokens (extended thinking models)
        "usage",              # token usage report (sent at end of stream)
        "done",               # stream complete
        "error",              # provider error mid-stream
    ]
    text: str | None = None                # for text_delta, thinking_delta
    tool_call_id: str | None = None        # for tool_call_start/delta/end
    tool_name: str | None = None           # for tool_call_start
    tool_args_delta: str | None = None     # for tool_call_delta (partial JSON string)
    tool_args: dict | None = None          # for tool_call_end (fully parsed arguments)
    input_tokens: int | None = None        # for usage
    output_tokens: int | None = None       # for usage
    error_message: str | None = None       # for error
    error_code: str | None = None          # for error (e.g., "rate_limit", "context_length_exceeded")
```

#### Tool call execution flow

```
Provider stream yields events:
    │
    ├─ text_delta → forward to gateway as agent.run.stream (kind: "text_delta")
    │
    ├─ tool_call_start → buffer tool call, emit agent.run.stream (kind: "tool_call_start")
    │
    ├─ tool_call_delta → accumulate partial JSON args, emit agent.run.stream (kind: "tool_call_input_delta")
    │
    ├─ tool_call_end → full tool call ready:
    │     1. Check SessionPolicy.allowed_tools → reject if not allowed
    │     2. Check require_confirmation → if yes, emit approval_request, wait
    │     3. Execute tool handler → get ToolResult
    │     4. Emit agent.run.stream (kind: "tool_result")
    │     5. Inject tool result into message history
    │     6. Re-call stream_completion with updated messages (loop)
    │
    ├─ thinking_delta → emit agent.run.stream (kind: "thinking") if thinking exposure enabled
    │
    ├─ usage → record in budget tracker
    │
    └─ done → finalize turn
```

**Parallel tool calls**: Some providers (OpenAI, Anthropic) can return multiple tool calls in a single response. When multiple `tool_call_end` events arrive before `done`:
1. All tool calls are collected.
2. Policy checks run for each.
3. Approved tools execute concurrently (`asyncio.gather`).
4. All results injected together, then one re-call to the provider.

**Tool result model**:

```python
class ToolResult(BaseModel):
    tool_call_id: str
    success: bool
    result: str | dict | list             # tool output (stringified for injection)
    error: str | None = None              # error message if success=False
    execution_time_ms: int
```

### 4.6b Model Capability Registry

Each provider exposes per-model capabilities via `get_model_capabilities()`. This information is used by the prompt assembly pipeline, vision system, and context budget calculator.

```python
class ModelCapabilities(BaseModel):
    model_id: str                         # e.g., "claude-sonnet-4-20250514"
    provider_id: str                      # e.g., "anthropic"
    display_name: str                     # e.g., "Claude Sonnet 4"

    # --- Context ---
    context_window: int                   # max input tokens (e.g., 200000)
    max_output_tokens: int                # max response tokens (e.g., 8192)

    # --- Capabilities ---
    supports_tools: bool = True
    supports_vision: bool = False
    supports_structured_output: bool = False   # JSON mode / response_format
    supports_streaming: bool = True
    supports_thinking: bool = False       # extended thinking / reasoning tokens

    # --- Cost ---
    input_cost_per_1k: float = 0.0       # USD
    output_cost_per_1k: float = 0.0
    thinking_cost_per_1k: float = 0.0    # if supports_thinking

class ModelInfo(BaseModel):
    model_id: str
    provider_id: str
    capabilities: ModelCapabilities
    available: bool                       # currently accessible (auth valid, not deprecated)
    is_default: bool = False              # marked as agent's default model
```

**Registry population**:
- At startup, each provider calls `list_models()` → returns known models with capabilities.
- Capabilities are cached and refreshed daily (or on provider re-auth).
- The UI's model selector shows all available models grouped by provider, with capability badges (vision, tools, thinking).
- `ContextBudget.max_context_tokens` is auto-populated from `ModelCapabilities.context_window` if not explicitly set.

### 4.6c Local Model Providers (Ollama)

Ollama (and similar local model servers like LM Studio, llama.cpp server) is a first-class provider choice. It runs entirely on the user's machine — no API keys, no cost, no data leaving the device. However, it has unique constraints that the provider adapter must handle.

#### Ollama provider adapter

```python
class OllamaProvider(LLMProvider):
    provider_id: str = "ollama"
    base_url: str = "http://localhost:11434"   # default Ollama API server

    async def list_models(self) -> list[ModelInfo]:
        """Query GET /api/tags to discover locally installed models.
        Maps Ollama model metadata to ModelInfo + ModelCapabilities."""

    async def stream_completion(self, ...) -> AsyncIterator[ProviderStreamEvent]:
        """Uses POST /api/chat (OpenAI-compatible endpoint).
        Ollama implements the OpenAI chat completion format."""

    async def count_tokens(self, messages: list[Message], model: str) -> int:
        """Ollama does not expose a tokenizer API. Fallback strategy:
        1. Use tiktoken cl100k_base as approximation (works well for most models).
        2. For known model families (llama, mistral, gemma), use family-specific
           token/char ratios for better accuracy.
        3. Conservative: overcount by ~5% to avoid context overflow."""

    def get_model_capabilities(self, model: str) -> ModelCapabilities:
        """Infer capabilities from model metadata (GET /api/show):
        - context_window: from model's num_ctx parameter (default 4096 for most models)
        - supports_vision: check model family (llava, bakllava, moondream = True)
        - supports_tools: check model family (llama3+, mistral = True, older models = False)
        - supports_thinking: check model family (deepseek-r1, qwq = True)
        - All costs = 0.0 (free, runs locally)"""

    def cost_per_token(self, model: str) -> CostRate:
        return CostRate(input_cost_per_1k=0.0, output_cost_per_1k=0.0)
```

#### Ollama-specific concerns

| Concern | Handling |
|---|---|
| **Model discovery** | `GET /api/tags` returns all installed models with family, parameter size, and quantization. Refreshed on provider registry startup + daily + when user visits model selector. |
| **Model download** | `POST /api/pull` with `{"name": "model:tag"}`. The UI shows a model library with a "Download" button per model. Download progress streamed via Ollama's streaming pull response → shown as a progress bar in the UI. |
| **No native tokenizer** | Use `tiktoken` with `cl100k_base` (GPT-4 tokenizer) as a universal approximation. Overcount by 5% for safety margin. Token counts are used for budget allocation, not billing — approximate is fine. |
| **Context window** | Many local models default to 4096 or 8192 tokens. When `num_ctx` is low, the prompt assembly pipeline (§4.3a) must be more aggressive about trimming. The UI model selector shows context window size prominently. |
| **GPU vs CPU** | Not detected by Tequila — Ollama handles GPU allocation internally. If Ollama returns slow responses (>30s for short prompts), log a warning: *"Ollama response slow — model may be running on CPU. Consider using a smaller model or enabling GPU offloading."* |
| **$0 cost** | All Ollama model costs are $0. Budget tracker records turn_cost with `cost_usd=0.0`. Budget cap checks pass unconditionally. Budget reports show Ollama usage for token tracking (not cost tracking). |
| **Connection failure** | If `GET /api/tags` fails on startup, Ollama provider is marked `available=False` with error: *"Could not connect to Ollama at {base_url}. Is Ollama running?"* The setup wizard's provider step includes an Ollama connectivity check. |
| **Model not loaded** | Ollama loads models into memory on first use. First request to a model may be slow (10–60s for large models). The provider adapter handles this transparently — the streaming response just takes longer to start. |

#### First-run with Ollama

In the setup wizard (§15.1), if the user selects Ollama:
1. Check connectivity to `http://localhost:11434/api/tags`.
2. If connected: show installed models. If none installed, show a curated list of recommended starter models (e.g., `llama3.2:3b` for lightweight, `llama3.1:8b` for general, `deepseek-coder-v2:16b` for code).
3. User selects or downloads a model.
4. "API Key" step is skipped (Ollama needs no auth).
5. Setup proceeds to agent creation.

#### Configuration

```python
class OllamaConfig(BaseModel):
    base_url: str = "http://localhost:11434"
    request_timeout_s: int = 120          # longer timeout for large models / CPU inference
    num_ctx: int | None = None            # override context window per-request (None = model default)
    gpu_layers: int | None = None         # optional: pass to Ollama for GPU offloading control
```

Added to config namespace: `ollama.*` → `OllamaConfig` (hot-reloadable).

### 4.7 Context Window Management

The most critical runtime concern: assembling a prompt that fits within the model's context limit.

**Token budget allocation** (configurable per agent):

```python
class ContextBudget(BaseModel):
    max_context_tokens: int              # model's context window (e.g., 200000)
    reserved_for_response: int = 4096    # tokens reserved for model output
    system_prompt_budget: int = 2000     # system prompt + soul + instructions
    memory_always_recall_budget: int = 500  # always-recall + pinned memories (§4.3a step 2)
    memory_recall_budget: int = 2000     # per-turn recalled memories (§4.3a step 3)
    knowledge_source_budget: int = 1500  # external knowledge source results (§4.3a step 3a, §5.14)
    skill_index_budget: int = 500        # Level 1 skill summaries — all assigned skills (§4.5.2, step 4a)
    skill_instruction_budget: int = 1500 # Level 2 skill instructions — active skills only (§4.5.2, step 4b)
    tool_schema_budget: int = 2000       # tool definitions sent to model
    file_context_budget: int = 3000      # uploaded file previews (§4.3a step 6)
    max_tool_rounds: int = 25            # max tool-call loop iterations per turn
    compression_threshold: float = 0.6   # compress when history exceeds this fraction of history budget
    min_recent_messages: int = 4         # always keep the N most recent messages
    # Remaining = session history (messages)
```

**Priority trimming** (when over budget — matches §4.3a canonical ordering):
1. Drop oldest session history first (FIFO), replace with compression summary if available
2. If still over budget: reduce file context injections (shorter previews)
3. If still over budget: reduce `skill_instruction_budget` (fewer active skill instructions)
4. If still over budget: reduce `knowledge_source_budget` (fewer knowledge source chunks)
5. If still over budget: reduce `memory_recall_budget` (fewer memories, higher similarity threshold)
6. If still over budget: reduce tool definitions (drop least-used tools)
7. If still over budget: reduce `skill_index_budget` (fewer Level 1 summaries, lowest-priority first)
8. Last resort: reduce `memory_always_recall_budget` (trim lowest-priority always-recall memories)
9. Never trim: system prompt (persona + rules), most recent N messages (default 4), current user message

**Token counting**:
- Provider-specific tokenizer called via `provider.count_tokens()`
- Cached per-message to avoid recounting on every turn
- Budget check runs *before* the provider call, not after

**Compression trigger**:
- When session history exceeds `compression_threshold` (default: 60% of history budget)
- Oldest message batch summarized via provider call
- Summary replaces the batch in session history
- Original messages preserved in DB for audit (flagged as `compressed: true`)

---

## 5) Memory System

### 5.1 Architecture Overview

The memory system is a structured, multi-tier knowledge store with entity awareness, active agent curation, and a lifecycle pipeline. It is the agent's long-term brain — not just a bag of text chunks, but an interconnected graph of typed memories, extracted entities, and curated knowledge.

```
┌─────────────────────────────────────────────────────────┐
│                     MEMORY SYSTEM                        │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │         Tier 3: Knowledge Vault (permanent)       │   │
│  │    Markdown notes, ingested documents, curated    │   │
│  │    All agents read. Main agent + user write.      │   │
│  ├──────────────────────────────────────────────────┤   │
│  │         Tier 2: Memory Pool (semi-permanent)      │   │
│  │    Structured extracts: facts, preferences,       │   │
│  │    experiences, tasks, relationships, skills       │   │
│  │    + Entity model linking memories together        │   │
│  │    All agents read. Main agent curates.           │   │
│  ├──────────┬──────────┬────────────────────────┤   │
│  │ Agent A  │ Agent B  │ Agent C                 │   │
│  │ private  │ private  │ private                 │   │
│  │ memory   │ memory   │ memory                  │   │
│  │ (scratch,│ (scratch,│ (scratch,               │   │
│  │  session │  session │  session                │   │
│  │  context)│  context)│  context)               │   │
│  └──────────┴──────────┴────────────────────────┘   │
│                         │                            │
│  ┌──────────────────────▼───────────────────────┐    │
│  │            ENTITY GRAPH                       │    │
│  │   person, organization, project, location,    │    │
│  │   concept, event, tool, date                  │    │
│  │   entities link memories → structured web     │    │
│  └──────────────────────────────────────────────┘    │
│                         │                            │
│  ┌──────────────────────▼───────────────────────┐    │
│  │           RECALL PIPELINE                     │    │
│  │   Session init → Per-turn query → Background  │    │
│  └──────────────────────────────────────────────┘    │
│                         │                            │
│  ┌──────────────────────▼───────────────────────┐    │
│  │         EXTRACTION PIPELINE                   │    │
│  │   Classify → Extract → Dedup → Entity-link    │    │
│  │   → Graph-edge → Conflict-resolve             │    │
│  └──────────────────────────────────────────────┘    │
│                         │                            │
│  ┌──────────────────────▼───────────────────────┐    │
│  │       LIFECYCLE MANAGER                       │    │
│  │   Decay → Consolidate → Merge → Summarize    │    │
│  │   → Archive → Report orphans                  │    │
│  └──────────────────────────────────────────────┘    │
│                         │                            │
│  ┌──────────────────────▼───────────────────────┐    │
│  │          MEMORY AUDIT TRAIL                   │    │
│  │   Every create/update/merge/access logged     │    │
│  └──────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### 5.2 Memory Scope Model

```python
class MemoryScope(BaseModel):
    can_read_shared: bool = True          # read from shared knowledge/memory
    can_write_shared: bool = False         # only main agent (admin) = True
    private_namespace: str                 # agent-specific memory partition
```

### 5.3 Structured Memory Types

Each memory extract is a structured object with type-specific recall behavior, temporal metadata, provenance tracking, and entity links.

```python
class MemoryExtract(BaseModel):
    id: str
    content: str
    memory_type: Literal[
        "identity",       # who the user is, biographical facts
        "preference",     # likes/dislikes, settings, style preferences
        "fact",           # learned knowledge, definitions, references
        "experience",     # what happened, lessons learned, outcomes
        "task",           # commitments, deadlines, action items
        "relationship",   # connections between entities (person X works at Y)
        "skill",          # how to do something, procedures, recipes
    ]

    # --- Recall behavior ---
    always_recall: bool = False           # identity/preference → always in context
    recall_weight: float = 1.0            # boost/demote in ranking
    pinned: bool = False                  # user/agent pinned for persistent recall in session

    # --- Temporal ---
    created_at: datetime
    last_accessed: datetime
    access_count: int = 0
    expires_at: datetime | None = None    # tasks have deadlines; None = no expiration
    decay_score: float = 1.0             # current relevance (1.0 = fresh, decays over time)

    # --- Provenance ---
    source_type: Literal["extraction", "user_created", "agent_created", "promoted", "merged"]
    source_session_id: str | None = None
    source_message_id: str | None = None  # exact message it came from
    confidence: float = 1.0               # extraction confidence (LLM self-assessed)

    # --- Entity links ---
    entity_ids: list[str] = []            # entities this memory references
    tags: list[str] = []

    # --- Scope ---
    scope: Literal["global", "agent", "session"]
    agent_id: str | None = None           # for agent-scoped memories

    # --- Embedding ---
    embedding: list[float] | None = None

    # --- Lifecycle ---
    status: Literal["active", "archived", "deleted"] = "active"
    version: int = 1                      # optimistic concurrency control (§20.3b)
```

#### Default recall behavior by type:

| Memory type | `always_recall` | `recall_weight` | Typical `expires_at` | Decays? |
|---|---|---|---|---|
| `identity` | `True` | 1.5 | None | No |
| `preference` | `True` | 1.2 | None | No |
| `fact` | `False` | 1.0 | None | Slow |
| `experience` | `False` | 1.1 | None | Yes |
| `task` | `False` | 1.3 | Task deadline | Yes (fast after expiry) |
| `relationship` | `False` | 1.0 | None | Slow |
| `skill` | `False` | 0.9 | None | No |

### 5.4 Entity Model

The memory system maintains a first-class entity graph. Entities are the "things" that memories are about — people, projects, organizations, etc.

```python
class Entity(BaseModel):
    id: str
    name: str
    entity_type: Literal[
        "person", "organization", "project", "location",
        "tool", "concept", "event", "date"
    ]
    aliases: list[str] = []              # "Company X", "CompanyX", "CX"
    summary: str = ""                    # auto-generated from linked memories
    properties: dict = {}                # flexible key-value (email, role, URL, etc.)
    first_seen: datetime
    last_referenced: datetime
    reference_count: int = 0
    embedding: list[float] | None = None
    status: Literal["active", "merged", "deleted"] = "active"
    merged_into: str | None = None       # if merged, points to surviving entity ID
```

#### Entity extraction

When the extraction pipeline processes session messages or vault notes:
1. **NER pass** — the LLM identifies entity mentions with type classification.
2. **Resolution** — each mention is matched against existing entities by name, aliases, and embedding similarity.
3. **Create or link** — new entity if novel, otherwise link memory to existing entity.
4. **Alias learning** — if the LLM identifies a new way to refer to a known entity, add it to `aliases`.

#### Entity-aware recall

When the user says "What's the deadline for Company X?":
1. Parse mentions → resolve to entity `company_x`.
2. Pull all memories linked to `company_x` (regardless of embedding similarity to the query).
3. Traverse one hop: also pull memories linked to entities related to `company_x` (e.g., employees, projects).
4. Merge with standard vector recall results, deduplicate, rank.

### 5.5 Extraction Pipeline

Memory extraction converts raw session messages into structured memories, entities, and graph edges. It replaces the previous vague "LLM summarizes key information" with a well-defined 6-step pipeline.

#### Triggers

| Trigger | Condition |
|---|---|
| **Periodic** | Every N messages in an active session (configurable, default: 10) |
| **Session close** | On session archive or explicit close |
| **Context pressure** | Before context trimming (extract first, then trim) |
| **Manual** | User or agent invokes `memory_extract_now` tool or `POST /api/memory/extract` |

#### Pipeline Steps

```
Session messages (batch of N unprocessed messages)
    │
    ▼
Step 1: RELEVANCE CLASSIFICATION
    Prompt: "Which of these messages contain information worth
             remembering long-term? Ignore chitchat, acknowledgments,
             filler, and purely procedural messages."
    → Filter to relevant messages only
    │
    ▼
Step 2: STRUCTURED EXTRACTION
    Prompt: "For each relevant message, extract structured memories.
             Each memory must have: content, memory_type, confidence,
             entity mentions, optional expiration, optional tags."
    → List of candidate MemoryExtract objects (pending)
    │
    ▼
Step 3: DEDUPLICATION
    For each candidate, compare against existing memories:
    → Embedding similarity > 0.95: exact duplicate → skip
    → Embedding similarity 0.85–0.95: near duplicate → merge
       (keep more complete version, combine tags, bump confidence)
    → Embedding similarity < 0.85: novel → proceed
    │
    ▼
Step 4: CONTRADICTION DETECTION
    For near-matches with conflicting content:
    → If new memory is more recent + confidence ≥ old: update old memory
    → If uncertain: keep both, flag for user review
    → Log contradiction in memory audit trail
    │
    ▼
Step 5: ENTITY EXTRACTION & LINKING
    For each new/updated memory:
    → Extract entity mentions (NER)
    → Resolve against existing entities (name + alias + embedding)
    → Create new entities if novel
    → Create memory → entity link edges
    → Learn new aliases if detected
    │
    ▼
Step 6: GRAPH EDGE CREATION
    → extracted_from edges: memory → source session
    → entity_relationship edges: entity → entity (inferred from co-occurrence)
    → tagged_with edges: memory → tag
    → semantic_similar edges: computed for new memories against neighbors
    → wiki_link edges: if memory references a vault note by name
```

#### Extraction configuration

```python
class ExtractionConfig(BaseModel):
    trigger_interval_messages: int = 10    # extract every N messages
    trigger_on_session_close: bool = True
    trigger_on_context_pressure: bool = True
    min_confidence: float = 0.5            # discard extracts below this
    dedup_similarity_threshold: float = 0.95
    merge_similarity_threshold: float = 0.85
    max_extracts_per_batch: int = 20       # prevent runaway extraction
    entity_extraction_enabled: bool = True
    contradiction_auto_resolve: bool = False  # True = auto-update, False = flag for review
```

### 5.6 Recall Pipeline

Recall is the process of selecting and injecting relevant memories into the agent's context window at turn time. The v2 system uses a **3-stage pipeline** for maximum relevance with minimum latency.

#### Stage 1: Session Initialization (runs once per session start/resume)

When a session starts or is resumed:
1. Load all `always_recall=True` memories (identity, preferences).
2. Load all `pinned=True` memories for this session.
3. Load active `task` memories that haven't expired.
4. Inject as a `[Memory Context]` block in the system prompt.

This guarantees the agent always knows who the user is and what they prefer, even on the first turn before any query-specific recall.

#### Stage 2: Per-Turn Foreground Recall (runs on every turn)

For each incoming user message:
1. **Embed the message**.
2. **Vector search** across `memory_extracts` + `vault_notes` (existing behavior).
3. **FTS5 keyword search** as fallback.
4. **Entity-aware expansion**: parse entity mentions in the message → pull memories linked to those entities via the entity graph.
4a. **Knowledge source federation** (§5.14): for each active source with `auto_recall=True` that the agent can access, query in parallel via `KnowledgeSourceRegistry.search_auto_recall()`. Soft-fail on timeout/error.
4b. **Merge**: combine knowledge source `KnowledgeChunk` results with memory/vault results. Normalize scores per source, then weighted merge. Tag chunks with `source_id`.
5. **Rank results** using a composite score:
   ```
   score = (similarity × recall_weight × decay_score) + entity_match_bonus
   ```
6. **Deduplicate** against stage 1 results (don't re-inject what's already in context).
7. **Budget-fit**: select top-K results within `memory_recall_budget` token limit.

#### Stage 3: Background Pre-Fetch (runs asynchronously after turn dispatch)

After the turn is dispatched to the LLM:
1. **Entity graph traversal**: for entities mentioned in the current turn, pre-fetch memories linked to neighboring entities (1-hop).
2. **Update access metadata**: bump `last_accessed` and `access_count` on all recalled memories.
3. **Pre-compute likely queries**: based on conversation trajectory, prime the embedding cache for next turn.
4. Cache pre-fetched results → available instantly for the next turn's stage 2.

#### Recall configuration

```python
class RecallConfig(BaseModel):
    always_recall_types: list[str] = ["identity", "preference"]
    max_always_recall_tokens: int = 500
    max_per_turn_results: int = 15
    max_per_turn_tokens: int = 2000        # = memory_recall_budget in ContextBudget
    entity_expansion_hops: int = 1
    entity_match_bonus: float = 0.2        # added to score when entity matches
    similarity_threshold: float = 0.65     # minimum score to include
    prefetch_enabled: bool = True
```

### 5.7 Agent Memory Tools

Agents are **active curators** of their own memory, not just passive consumers. The following tools are available to every agent:

| Tool | Safety | Description |
|---|---|---|
| `memory_save` | `side_effect` | Explicitly store a memory: content, type, entities, tags, optional expiration. "I should remember this for later." |
| `memory_update` | `side_effect` | Modify an existing memory's content, type, tags, or expiration. "Actually the deadline moved to April." |
| `memory_forget` | `destructive` | Archive a memory (soft delete). "This is no longer relevant." Requires confirmation. |
| `memory_search` | `read_only` | Search memories by query (vector + FTS), optionally filtered by type, entity, tag, date range. |
| `memory_list` | `read_only` | List memories by entity, type, tag, scope, or date range. Returns structured results. |
| `memory_pin` | `side_effect` | Pin a memory to the current session for persistent recall (always in context for this session). |
| `memory_unpin` | `side_effect` | Unpin a memory from the current session. |
| `memory_link` | `side_effect` | Create an edge between two memories, or between a memory and an entity. |
| `entity_create` | `side_effect` | Create a new entity with type, properties, aliases. |
| `entity_merge` | `side_effect` | Merge two entities detected as the same thing (consolidates aliases, re-links memories). |
| `entity_update` | `side_effect` | Update entity properties (name, aliases, summary, properties). |
| `entity_search` | `read_only` | Search entities by name, type, or properties. |
| `memory_extract_now` | `side_effect` | Trigger extraction pipeline on the current session's unprocessed messages. |

Admin agents (`is_admin=True`) can operate on global and any agent's memories. Sub-agents can only operate on their own private namespace and read global memories.

### 5.8 Memory Lifecycle Manager

Over time, the memory pool grows. Without lifecycle management, recall degrades as thousands of stale extracts compete for context budget. The lifecycle manager runs as a periodic background job.

#### Decay

Memories lose relevance over time unless actively accessed:

```python
class MemoryDecayConfig(BaseModel):
    enabled: bool = True
    half_life_days: int = 90               # relevance halves every 90 days of non-access
    floor: float = 0.1                     # never fully decay (can always be found via explicit search)
    access_resets_decay: bool = True        # accessing a memory resets its decay clock
    always_recall_immune: bool = True       # identity/preference memories don't decay
    task_post_expiry_decay_days: int = 7    # expired tasks decay rapidly (7 days to floor)
```

Decay formula:
```
days_since_access = (now - last_accessed).days
decay_score = max(floor, 0.5 ^ (days_since_access / half_life_days))
```

Decay scores are recalculated in bulk during the lifecycle job and stored on the memory record.

#### Consolidation

Runs weekly (configurable). Steps:

1. **Merge near-duplicates**: memories with embedding similarity > `merge_threshold` (default: 0.92) are combined into one. The more complete version is kept; tags and entity links are union-merged. A `merged` event is logged.

2. **Summarize entity clusters**: if an entity has > `summarize_threshold` (default: 10) linked memories, generate a summary note from all linked memories and archive the individual extracts. The summary is stored as a new memory with `source_type: "merged"`.

3. **Archive decayed**: memories with `decay_score < archive_threshold` (default: 0.15) are moved to `status: "archived"`. Archived memories are still searchable via explicit `memory_search` but are never injected into context by the recall pipeline.

4. **Expire tasks**: `task` memories past their `expires_at` enter rapid decay. After `task_post_expiry_decay_days` they're archived.

5. **Report orphans**: memories with no entity links and no access in 60+ days are flagged in the Memory Explorer UI as candidates for deletion.

#### Consolidation configuration

```python
class ConsolidationConfig(BaseModel):
    enabled: bool = True
    schedule_cron: str = "0 4 * * 0"       # weekly, Sunday 4 AM
    merge_threshold: float = 0.92
    summarize_threshold: int = 10
    archive_threshold: float = 0.15
    orphan_report_after_days: int = 60
```

### 5.9 Memory Audit Trail

Every mutation to a memory or entity is logged:

```python
class MemoryEvent(BaseModel):
    id: str
    memory_id: str | None = None          # for memory events
    entity_id: str | None = None          # for entity events
    event_type: Literal[
        "created", "updated", "merged", "promoted",
        "archived", "deleted", "accessed", "pinned", "unpinned",
        "conflict_detected", "conflict_resolved",
        "entity_created", "entity_merged", "entity_updated",
        "decay_recalculated", "consolidated"
    ]
    timestamp: datetime
    actor: Literal["extraction_pipeline", "consolidation", "recall", "agent", "user"]
    actor_id: str | None = None           # agent_id or "user"
    old_content: str | None = None        # for updates/merges
    new_content: str | None = None
    reason: str | None = None             # why was this changed?
    metadata: dict = {}                   # additional context (e.g., similarity score for merges)
```

Stored in `memory_events` table. The UI shows a memory's full history: when it was learned, how it evolved, who changed it, and why. Entity merge events track which entity was absorbed and which survived.

### 5.10 Knowledge Vault

The vault is the agent's curated, permanent knowledge base — distinct from transient memory extracts.

- Markdown note storage on local filesystem (`data/vault/`)
- Note CRUD with wiki-link support (`[[note_name]]`)
- File watcher for external edits (live sync)
- Embedding index (via `EmbeddingStore` §5.13):
  - Index new notes
  - Reindex changed notes
  - Remove stale/deleted entries
- Search API: semantic + FTS search across vault
- Reindex API: manual trigger for full reindex
- Notes participate in the knowledge graph as `note` type nodes

### 5.11 Knowledge Graph

Tequila maintains a **knowledge graph** that maps relationships between all knowledge artifacts — notes, memories, entities, agents, sessions, files, and tags. This powers an interactive Obsidian-style graph visualization in the frontend and drives entity-aware recall.

#### Node Types

| Node type | Source | Description |
|---|---|---|
| `note` | Vault | A markdown note in the knowledge base |
| `memory` | Memory pool | A structured memory extract |
| `entity` | Entity store | A person, project, organization, etc. |
| `agent` | Agent config | An agent in the system |
| `session` | Session store | A conversation session (active or archived) |
| `file` | File uploads | An uploaded or generated file |
| `tag` | Note/memory/entity metadata | A user-defined or auto-extracted tag |

#### Edge Types

| Edge type | From → To | How it's created |
|---|---|---|
| `wiki_link` | note → note | Explicit `[[note_name]]` links in markdown (Obsidian-style) |
| `extracted_from` | memory → session | Memory was extracted from this session's conversation |
| `references` | note → note | Note mentions or cites another note |
| `semantic_similar` | any → any | Embedding cosine similarity above threshold (auto-discovered) |
| `tagged_with` | note/memory/entity → tag | Explicit tag assignment or auto-extraction |
| `authored_by` | note/memory → agent | Which agent created or curated this knowledge |
| `mentioned_in` | file/note → session | File or note was referenced in a session |
| `promotes_to` | memory (private) → memory (shared) | Memory promoted from agent-private to shared pool |
| `linked_to` | memory → entity | Memory references this entity |
| `entity_relationship` | entity → entity | Inferred relationship (works_at, located_in, part_of, etc.) |
| `merged_from` | entity → entity | Entity merge: source → surviving entity |
| `derived_from` | memory → memory | Summary memory was derived from these source memories |

#### Graph Data Model

```python
class GraphNode(BaseModel):
    id: str
    node_type: Literal["note", "memory", "entity", "agent", "session", "file", "tag"]
    label: str                           # display name
    metadata: dict = {}                  # type-specific fields (e.g., memory_type, entity_type, agent_name)
    created_at: str
    updated_at: str | None = None

class GraphEdge(BaseModel):
    source: str                          # node ID
    target: str                          # node ID
    edge_type: str                       # from edge types above
    weight: float = 1.0                  # strength (e.g., similarity score for semantic edges)
    label: str | None = None             # optional display label (e.g., "works_at" for entity relationships)
    metadata: dict = {}

class KnowledgeGraph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    stats: GraphStats

class GraphStats(BaseModel):
    total_nodes: int
    total_edges: int
    node_counts: dict[str, int]          # per node_type
    edge_counts: dict[str, int]          # per edge_type
    orphan_count: int                    # nodes with zero edges
    most_connected: list[str]            # top 10 node IDs by edge count
```

#### Graph Construction

The graph is built and maintained incrementally:

1. **Note events** (create, update, delete) → parser extracts `[[wiki_links]]` and `#tags` → upsert nodes/edges.
2. **Memory extraction** → new memory nodes + `extracted_from` edges + `linked_to` entity edges.
3. **Entity extraction** → new entity nodes + `entity_relationship` edges between co-occurring entities.
4. **Memory promotion** → `promotes_to` edge added.
5. **Consolidation** → `derived_from` edges when memories are merged/summarized, `merged_from` edges when entities merge.
6. **Embedding index updates** → periodic job computes pairwise similarity for new/changed nodes → `semantic_similar` edges above configurable threshold (default: 0.82).
7. **File/session references** → detected during turn processing when agents reference notes or files.

Stored in a `graph_edges` table:

```sql
CREATE TABLE graph_edges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT NOT NULL,
    source_type TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    target_type TEXT NOT NULL,
    edge_type   TEXT NOT NULL,
    weight      REAL NOT NULL DEFAULT 1.0,
    label       TEXT,                    -- display label for entity relationships
    metadata    TEXT,                    -- JSON
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_id, target_id, edge_type)
);
CREATE INDEX idx_graph_edges_source ON graph_edges(source_id);
CREATE INDEX idx_graph_edges_target ON graph_edges(target_id);
CREATE INDEX idx_graph_edges_type ON graph_edges(edge_type);
```

Nodes are not stored separately — they are resolved from their source tables (notes, memories, entities, agents, sessions, files) at query time.

#### Graph API

```
GET  /api/graph                          # full graph (nodes + edges), supports filters
GET  /api/graph/node/{id}                # single node + its direct connections (1-hop neighborhood)
GET  /api/graph/node/{id}/neighborhood?depth=2  # multi-hop neighborhood
GET  /api/graph/stats                    # graph statistics
GET  /api/graph/orphans                  # nodes with no connections
POST /api/graph/edges                    # manually create an edge (user-defined link)
DELETE /api/graph/edges/{id}             # remove an edge
POST /api/graph/rebuild                  # rebuild all auto-discovered edges (semantic similarity, wiki links)
```

**Filtering** (`GET /api/graph`):
- `node_types=note,memory,entity` — only include specific node types
- `edge_types=wiki_link,semantic_similar,entity_relationship` — only include specific edge types
- `min_weight=0.85` — filter edges by minimum weight
- `agent_id=...` — scope to a specific agent's knowledge
- `entity_id=...` — center on a specific entity's subgraph
- `since=2026-03-01` — only nodes created/updated after date
- `center_node={id}&depth=3` — ego-centric subgraph around a node

### 5.12 In-Session Compression

When the context window approaches its limit:
- Oldest message batch summarized via provider call
- Compression is loss-managed summarization, not silent discard
- **Before compressing**: the extraction pipeline runs on the to-be-compressed messages (extract first, compress second — no information loss)
- Compressed summaries persist in session record
- Original messages preserved in DB for audit (flagged as `compressed: true`)

### 5.13 Embedding Engine

The embedding engine powers vector search across memories, vault notes, entities, and knowledge graph semantic edges. It uses an abstract interface with a default SQLite + numpy implementation.

#### Embedding provider interface

```python
class EmbeddingProvider(ABC):
    """Generates embedding vectors from text."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns one vector per input text."""

    @abstractmethod
    def dimensions(self) -> int:
        """Return the dimensionality of this provider's embeddings."""

    @abstractmethod
    def model_id(self) -> str:
        """Return the model identifier (for cache invalidation on model change)."""
```

**Built-in embedding providers:**

| Provider | Model | Dimensions | Latency | Cost | Notes |
|---|---|---|---|---|---|
| `local` (default) | `sentence-transformers/all-MiniLM-L6-v2` | 384 | ~5ms/text (CPU) | Free | Runs via `sentence-transformers` package. ~90 MB model download on first use. Best default for privacy and offline use. |
| `openai` | `text-embedding-3-small` | 1536 | ~50ms/text (API) | $0.02/1M tokens | Higher quality for English text. Requires OpenAI API key (shared with LLM provider auth). |
| `openai_large` | `text-embedding-3-large` | 3072 | ~80ms/text (API) | $0.13/1M tokens | Highest quality. Only recommended for large knowledge bases with high retrieval demands. |
| `ollama` | Any Ollama model with embeddings | Model-dependent | ~10ms/text (local GPU) | Free | Uses `POST /api/embeddings`. Model must support embedding mode (e.g., `nomic-embed-text`, `mxbai-embed-large`). |

**Configuration:**

```python
class EmbeddingConfig(BaseModel):
    provider: Literal["local", "openai", "openai_large", "ollama"] = "local"
    ollama_model: str = "nomic-embed-text"   # used when provider="ollama"
    batch_size: int = 64                      # texts per embedding batch call
    cache_enabled: bool = True                # cache embeddings to avoid recomputation
    similarity_threshold: float = 0.65        # minimum cosine similarity for search results
    semantic_edge_threshold: float = 0.82     # minimum similarity for auto-generated graph edges
```

Added to config namespace: `embedding.*` → `EmbeddingConfig` (hot-reloadable; model change triggers full reindex).

#### Embedding storage (SQLite + numpy)

Embeddings are stored in a dedicated SQLite table alongside the source records:

```sql
CREATE TABLE embeddings (
    id              TEXT PRIMARY KEY,        -- matches source record ID (memory, note, entity)
    source_type     TEXT NOT NULL,           -- "memory", "note", "entity"
    source_id       TEXT NOT NULL,           -- ID in the source table
    model_id        TEXT NOT NULL,           -- embedding model used (for invalidation)
    vector          BLOB NOT NULL,           -- numpy float32 array, serialized via .tobytes()
    dimensions      INTEGER NOT NULL,
    text_hash       TEXT NOT NULL,           -- hash of embedded text (detect content changes)
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_type, source_id)
);
CREATE INDEX idx_embeddings_source ON embeddings(source_type, source_id);
CREATE INDEX idx_embeddings_model ON embeddings(model_id);
```

#### Embedding store interface

```python
class EmbeddingStore(ABC):
    """Abstract storage and search for embedding vectors."""

    @abstractmethod
    async def add(self, source_type: str, source_id: str, text: str) -> None:
        """Embed text and store the vector. Replaces existing if present."""

    @abstractmethod
    async def add_batch(self, items: list[EmbeddingItem]) -> None:
        """Embed and store a batch of items. More efficient than individual add() calls."""

    @abstractmethod
    async def search(
        self, query: str, source_types: list[str] | None = None,
        limit: int = 20, threshold: float | None = None,
    ) -> list[EmbeddingSearchResult]:
        """Embed the query, compute cosine similarity against stored vectors,
        return top-K results above threshold."""

    @abstractmethod
    async def delete(self, source_type: str, source_id: str) -> None:
        """Remove a stored embedding."""

    @abstractmethod
    async def reindex(self, source_type: str | None = None) -> ReindexResult:
        """Re-embed all items (or items of a specific type). Used when the
        embedding model changes or text content has been updated externally."""

class EmbeddingItem(BaseModel):
    source_type: str
    source_id: str
    text: str

class EmbeddingSearchResult(BaseModel):
    source_type: str
    source_id: str
    similarity: float                    # cosine similarity (0.0–1.0)

class ReindexResult(BaseModel):
    total: int
    updated: int
    errors: int
    duration_ms: int
```

#### Default implementation: SQLiteEmbeddingStore

The default implementation uses the `embeddings` table + numpy for similarity:

```python
class SQLiteEmbeddingStore(EmbeddingStore):
    \"\"\"
    Search strategy (brute-force cosine similarity):
    1. Load all vectors for the requested source_types into memory.
    2. Compute cosine similarity: query_vec @ matrix.T (single numpy operation).
    3. Filter by threshold, sort by similarity, return top-K.

    Performance at expected scale:
    - 10K memories + 1K notes + 500 entities = ~11.5K vectors
    - 11.5K × 384 dimensions × 4 bytes = ~17 MB in memory
    - Similarity computation: <10ms on any modern CPU
    - Even at 100K vectors: ~50ms — well within acceptable latency

    Vectors are lazy-loaded and cached in memory. Cache invalidated on add/delete.
    \"\"\"
```

#### Consumers

| Subsystem | What it embeds | When |
|---|---|---|
| Memory extraction (§5.5) | `MemoryExtract.content` | On extraction (step 3 dedup requires embedding) |
| Memory recall (§5.6) | User message (query) | Per-turn foreground recall |
| Entity store (§5.4) | `Entity.name + summary` | On entity create/update |
| Vault (§5.10) | Note content | On note create/update + file watcher |
| Knowledge graph (§5.11) | All node types | Periodic job for `semantic_similar` edge discovery |
| Unified search (§25) | Search query | On semantic/hybrid search |

#### Reindex triggers

- **Manual**: `POST /api/memory/reindex` or `POST /api/search/reindex`
- **Model change**: When `EmbeddingConfig.provider` changes, all existing embeddings are invalidated (different dimensions / different semantic space). A background reindex job starts automatically.
- **Startup check**: On startup, compare `model_id` in stored embeddings against current config. If mismatched, schedule background reindex.

#### Dependencies

| Dependency | Purpose | Required? |
|---|---|---|
| `numpy` | Vector storage serialization + cosine similarity computation | Yes |
| `sentence-transformers` | Local embedding model (default provider) | Yes (but lazy-loaded on first embed call) |
| `tiktoken` | Token counting for embedding batch sizing | Yes (already used for prompt assembly) |

### 5.14 Knowledge Source Registry

Tequila supports connecting to **external vector stores** as additional knowledge bases for RAG (Retrieval-Augmented Generation). The Knowledge Source Registry manages multiple external stores alongside the internal memory/vault embedding index, enabling federated retrieval across all sources.

#### Design Principles

1. **Hybrid access**: sources are queried automatically during recall (gateway-mediated) AND on-demand via agent tools
2. **Per-source query mode**: each source declares whether it accepts text queries or pre-embedded vectors — no embedding-model lock-in
3. **Budget-aware**: knowledge source results occupy a dedicated context budget, separate from memory recall
4. **Agent-scoped**: agents can be granted access to specific knowledge sources

#### Knowledge Source Model

```python
class QueryMode(str, Enum):
    text = "text"         # source accepts raw text, handles its own embedding
    vector = "vector"     # Tequila embeds the query via the specified provider, sends vector

class KnowledgeSource(BaseModel):
    source_id: str                        # unique identifier (e.g., "legal_docs", "product_catalog")
    name: str                             # display name
    description: str                      # what this source contains (shown to agent in tool descriptions)
    backend: Literal["chroma", "pgvector", "faiss", "http"]
    query_mode: QueryMode = QueryMode.text
    embedding_provider: str | None = None # required when query_mode="vector" — refs EmbeddingProvider id (§5.13)
    auto_recall: bool = False             # if True, queried automatically every turn via recall pipeline (§5.6)
    priority: int = 100                   # lower = higher priority (for budget allocation across sources)
    max_results: int = 5                  # max chunks returned per query
    similarity_threshold: float = 0.6     # minimum score to include results

    # Connection config (backend-specific, see schemas below)
    connection: dict = {}

    # Scoping
    allowed_agents: list[str] | None = None  # None = all agents; list = only these agent_ids

    # Runtime
    status: Literal["active", "error", "disabled"] = "disabled"
    error_message: str | None = None
    last_health_check: datetime | None = None

    created_at: datetime
    updated_at: datetime
```

#### Backend Connection Schemas

**Chroma** (local or remote):

```python
# connection dict for backend="chroma"
{
    "host": "localhost",               # Chroma server host (or "local" for in-process)
    "port": 8000,                      # Chroma server port (ignored when host="local")
    "collection": "legal_docs",        # collection name
    "tenant": "default_tenant",        # optional tenant
    "database": "default_database",    # optional database
    "api_key": null,                   # optional API key for remote Chroma
    "path": "data/chroma/",            # local storage path (only for host="local")
}
```

**pgvector** (PostgreSQL with pgvector extension):

```python
# connection dict for backend="pgvector"
{
    "dsn": "postgresql://user:pass@localhost:5432/mydb",
    "table": "documents",
    "content_column": "content",       # column containing text chunks
    "embedding_column": "embedding",   # column containing vectors
    "metadata_columns": ["title", "source", "page"],  # optional metadata columns to return
}
```

**FAISS** (local file-based):

```python
# connection dict for backend="faiss"
{
    "index_path": "data/faiss/legal_docs.index",    # path to FAISS index file
    "metadata_path": "data/faiss/legal_docs.json",  # chunk text + metadata sidecar
    "embedding_dimensions": 384,       # must match the model used to build the index
}
```

**Generic HTTP** (any API that accepts a query and returns scored chunks):

```python
# connection dict for backend="http"
{
    "url": "https://my-rag-api.com/search",
    "method": "POST",                 # HTTP method (GET or POST)
    "headers": {"Authorization": "Bearer xxx"},
    "query_param": "query",           # field name for the query text (body or query string)
    "results_path": "results",        # JSONPath to results array in response
    "content_field": "text",          # field name for chunk content within each result
    "score_field": "score",           # field name for relevance score
    "metadata_fields": ["title", "url"],  # optional metadata fields to extract
    "timeout_s": 10,
}
```

#### Knowledge Source Adapter ABC

```python
class KnowledgeSourceAdapter(ABC):
    """Base class for knowledge source backend adapters."""

    def __init__(self, source: KnowledgeSource):
        self.source = source

    @abstractmethod
    async def search(self, query: str, top_k: int = 5,
                     threshold: float = 0.6) -> list[KnowledgeChunk]:
        """Search the knowledge source. Returns ranked chunks."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Test connectivity to the backend. Returns True if healthy."""
        ...

    @abstractmethod
    async def count(self) -> int:
        """Return the approximate number of documents/chunks in the source."""
        ...


class KnowledgeChunk(BaseModel):
    source_id: str                     # which knowledge source produced this chunk
    content: str                       # the retrieved text
    score: float                       # relevance score (0–1, normalized)
    metadata: dict = {}                # backend-specific metadata (title, page, URL, etc.)
```

Built-in adapter implementations:

| Adapter | Backend | Dependencies | Default Query Mode |
|---|---|---|---|
| `ChromaAdapter` | `chroma` | `chromadb` | text (Chroma embeds via its configured embedding function) |
| `PgVectorAdapter` | `pgvector` | `asyncpg`, `pgvector` | vector (Tequila embeds the query, sends vector) |
| `FAISSAdapter` | `faiss` | `faiss-cpu` | vector (Tequila embeds the query, searches local index) |
| `HTTPAdapter` | `http` | `httpx` (already a dependency) | text (external API handles everything) |

All adapter dependencies are **optional** — installed on demand when a user configures a source of that type (same pattern as plugin dependencies §8.9).

#### Knowledge Source Registry

The `KnowledgeSourceRegistry` manages all registered sources and provides federated search:

```python
class KnowledgeSourceRegistry:
    async def register(self, source: KnowledgeSource) -> None:
        """Validate connection, health-check, persist to DB, instantiate adapter."""

    async def unregister(self, source_id: str) -> None:
        """Deactivate and remove source."""

    async def activate(self, source_id: str) -> None:
        """Health-check → status=active → start periodic health monitoring."""

    async def deactivate(self, source_id: str) -> None:
        """Set status=disabled, stop health monitoring."""

    async def search(
        self, query: str,
        source_ids: list[str] | None = None,
        agent_id: str | None = None,
        top_k: int = 10,
    ) -> list[KnowledgeChunk]:
        """Federated search across specified (or all active) sources.
        Filters by agent_id scope. Merges and re-ranks by score."""

    async def search_auto_recall(
        self, query: str, agent_id: str,
    ) -> list[KnowledgeChunk]:
        """Search only sources with auto_recall=True accessible to agent_id.
        Called by the recall pipeline (§5.6 Stage 2, step 4a)."""

    async def health_check_all(self) -> dict[str, bool]:
        """Run health checks on all active sources. Update status on failure."""

    def get_adapter(self, source_id: str) -> KnowledgeSourceAdapter:
        """Return the instantiated adapter for a source."""
```

#### Recall Pipeline Integration

When sources with `auto_recall=True` exist, Stage 2 of the recall pipeline (§5.6) gains two additional steps (inserted between entity-aware expansion and ranking):

```
Step 4a — KNOWLEDGE SOURCE FEDERATION
    → For each active source where auto_recall=True AND agent has access:
        → call source.search(query=user_message, top_k=source.max_results)
    → All source queries run in parallel (asyncio.gather, per-source timeout)
    → If a source times out or errors: skip it (soft failure), increment error count

Step 4b — MERGE
    → Combine knowledge source KnowledgeChunk results with memory/vault recall results
    → Normalize scores across sources (min-max normalization per source, then weighted merge)
    → Knowledge source results are tagged with source_id for attribution in the context block
```

After 5 consecutive query failures, a source is set to `status="error"` and excluded from auto-recall until manually reactivated via `POST /api/knowledge-sources/{id}/activate`.

Knowledge source results are rendered as a **`## Knowledge Sources`** block in the system prompt, separate from the `## Memory` block. Each chunk includes source attribution:

```
## Knowledge Sources
[legal_docs] Contract termination requires 30-day written notice per Section 12.4...
[product_catalog] Widget Pro X supports up to 10,000 concurrent connections...
```

#### Agent Tools

All agents with access to at least one knowledge source get two additional tools:

| Tool | Safety | Description |
|---|---|---|
| `kb_search` | `read_only` | Search one or more knowledge sources by query. Params: `query`, `source_ids` (optional — defaults to all accessible), `top_k`. Returns ranked chunks with source attribution. |
| `kb_list_sources` | `read_only` | List all knowledge sources accessible to this agent. Returns source_id, name, description, status, document count. |

These tools allow **on-demand** retrieval beyond what auto-recall provides — useful for targeted, deep searches the agent initiates during tool-call reasoning.

#### Configuration

```python
class KnowledgeSourceConfig(BaseModel):
    enabled: bool = True                            # master switch
    health_check_interval_s: int = 300              # periodic health-check interval (5 min)
    per_source_timeout_s: float = 5.0               # max wait for a single source query
    max_consecutive_failures: int = 5               # failures before auto-disable
    auto_recall_parallel: bool = True               # query auto-recall sources in parallel
```

Added to config namespace: `knowledge_sources.*` → `KnowledgeSourceConfig` (hot-reloadable).

#### API Endpoints

```
GET    /api/knowledge-sources                       # list all registered sources
POST   /api/knowledge-sources                       # register a new source
GET    /api/knowledge-sources/{id}                  # source details + status + health
PATCH  /api/knowledge-sources/{id}                  # update source config
DELETE /api/knowledge-sources/{id}                  # unregister source
POST   /api/knowledge-sources/{id}/activate         # activate source
POST   /api/knowledge-sources/{id}/deactivate       # deactivate source
POST   /api/knowledge-sources/{id}/test             # test connectivity + return sample results
GET    /api/knowledge-sources/{id}/stats            # document count, avg query time, error rate
POST   /api/knowledge-sources/search                # federated search (for UI / testing)
```

#### Database

`knowledge_sources` SQLite table stores source configurations and runtime state (status, error count, last health check). Sensitive values within the `connection` dict (passwords, API keys) are stored in the auth store (§6.3), referenced by `source_id`.

#### Dependencies

| Dependency | Purpose | Required? |
|---|---|---|
| `chromadb` | Chroma adapter | Optional (install when chroma source configured) |
| `asyncpg` + `pgvector` | pgvector adapter | Optional (install when pgvector source configured) |
| `faiss-cpu` | FAISS adapter | Optional (install when FAISS source configured) |
| `httpx` | HTTP adapter | Yes (already a dependency) |

---

## 6) Authentication and Provider Setup

### 6.1 LLM Provider Authentication

**OpenAI OAuth (PKCE)**:
- PKCE verifier/challenge generation
- Auth URL generation and redirect handling
- Local callback server flow + manual paste fallback
- Access/refresh token exchange and persistence
- Token refresh on expiry
- Logout / clear auth

**Anthropic OAuth (PKCE + paste)**:
- PKCE auth URL generation
- Redirect/pasted code parsing
- Token exchange and refresh
- Token persistence and logout

**API Key fallback**:
- Direct API key entry for either provider
- Key validation endpoint
- Key stored in local auth store

### 6.2 Plugin Authentication

Plugin auth is handled through the unified plugin API (see §8). Each plugin declares its auth requirements (`PluginAuth`), and the gateway's auth store manages credentials per plugin_id.

- OAuth2 plugins (Gmail, Google Calendar, Slack): use `/api/plugins/{id}/auth/start` + `/auth/callback`
- Token plugins (Telegram, Discord): token entered via plugin config
- API key plugins (MCP servers, custom): key entered via plugin config
- Shared credentials: plugins can reference another plugin's auth (e.g., `google_calendar` reuses `gmail` OAuth tokens)

### 6.3 Auth Store

All tokens persisted locally. No cloud token storage. Auth state queryable via API for frontend setup flows.

---

## 7) Scheduler and Background Automation

### 7.1 Scheduler Runtime

- Scheduler manager starts as part of gateway lifecycle
- Cron-based scheduling with standard cron expressions
- Each scheduled task creates a `cron:<job_id>` session when it fires

### 7.2 Scheduler API

- Task CRUD: create / list / get / update / delete
- Run-now: immediate trigger
- Enable/disable toggle
- Runtime inspection: next-run, last-run, status

### 7.3 Background Agent Runs

- Scheduled tasks trigger agent runs in their own sessions
- Results can be announced to user (notification) or silently logged
- Background sessions follow the same policy model as any other session

---

## 8) Plugin System

**Plugin** is the top-level extensibility concept. Every external integration AND every internal extension point is a plugin. **Connectors** are plugins that connect to external services (plugin_type="connector"). Internal plugins extend Tequila's pipeline without touching external APIs.

### 8.0 Plugin Types

| Plugin Type | What It Does | Examples |
|---|---|---|
| **Connector** | Connects to an external service. Provides tools, channel adapter, or both. | telegram, gmail, google_calendar, MCP servers |
| **Pipeline Hook** | Extends the agent turn pipeline at defined hook points. | Custom RAG injection, prompt preprocessing, response post-processing |
| **Audit Sink** | Receives gateway audit events and forwards them somewhere. | Datadog logger, file export, webhook forwarder |
| **UI Extension** (future) | Adds custom panels/widgets to the React frontend. | Dashboard widget, custom visualization |

All plugin types share the same lifecycle, auth, config, and management API. The `plugin_type` field determines which capabilities a plugin registers.

```python
class Plugin(BaseModel):
    plugin_id: str                       # "telegram", "gmail", "custom_rag", etc.
    name: str
    description: str
    version: str
    plugin_type: Literal["connector", "pipeline_hook", "audit_sink"]
    connector_type: Literal["builtin", "mcp", "custom"] | None = None  # only for connectors

    # What this plugin provides
    tools: list[ToolDefinition] = []     # tools agents can call
    channel: ChannelAdapterSpec | None = None  # optional channel adapter (connectors only)
    hooks: list[PipelineHookSpec] = []   # pipeline hook points (pipeline_hook type)

    # What this plugin needs
    auth: PluginAuth | None = None       # OAuth config, API key spec, etc.
    config_schema: dict = {}             # JSON Schema for plugin-specific settings

    # Runtime state
    status: Literal["installed", "configured", "active", "error", "disabled"]
    error_message: str | None = None

class PipelineHookSpec(BaseModel):
    hook_point: Literal[
        "pre_prompt_assembly",            # inject context before prompt is built
        "post_prompt_assembly",           # modify assembled prompt before provider call
        "pre_tool_execution",             # intercept/modify tool calls
        "post_tool_execution",            # process tool results
        "post_turn_complete",             # after turn finishes (logging, side effects)
    ]
    priority: int = 100                   # lower = runs first
```

Connectors are the most common plugin type. Every external integration is a **connector** plugin — the single abstraction for adding capabilities to Tequila, whether it's a messaging channel, an email service, a calendar, an MCP server, or a custom API integration. There is no separate `Connector` model — connectors are `Plugin` instances with `plugin_type="connector"`.

### 8.1 Auth & Channel Models

```python
class PluginAuth(BaseModel):
    kind: Literal["oauth2", "api_key", "token", "none"]
    oauth2_config: OAuth2Config | None = None  # provider, scopes, endpoints
    # Credentials stored in auth store, referenced by plugin_id

class ChannelAdapterSpec(BaseModel):
    channel_name: str                    # "telegram", "email", "webchat", etc.
    supports_inbound: bool = True        # can receive messages
    supports_outbound: bool = True       # can send messages
    supports_voice: bool = False         # can handle voice/audio
    polling_mode: bool = False           # uses polling (vs webhook/push)
```

### 8.2 Plugin Subtypes (for Connectors)

| Subtype | Description | Discovery | Examples |
|---|---|---|---|
| **Built-in** | Ships with Tequila. Python modules in `app/plugins/builtin/` | Auto-discovered on startup | webchat, telegram, gmail, smtp_imap, google_calendar, webhooks, documents, browser |
| **MCP** | External process exposing tools via Model Context Protocol | User adds server URL | Any MCP-compatible server (same as Claude Desktop) |
| **Custom** | User-written Python module placed in `app/plugins/custom/` | Auto-discovered on startup | Custom CRM, internal API wrapper, proprietary service |

### 8.3 Plugin Lifecycle

All plugin types share the same lifecycle:

```
Installed → Configured → Active ⇄ Error
    ↑           ↑          ↓
    └───────────┴── Disabled
```

1. **Installed**: plugin code is present but not configured (no auth, no settings)
2. **Configured**: auth completed and settings provided, but not yet started
3. **Active**: running — channel adapter listening (if connector), tools registered, hooks attached
4. **Error**: runtime failure (auth expired, external API down, config invalid)
5. **Disabled**: manually turned off by user

### 8.4 Plugin Registry

The gateway maintains a **plugin registry** that manages all plugin instances:

- **Startup**: scan `app/plugins/builtin/` for built-in plugins + load saved MCP/custom configs from DB → initialize all `active` plugins
- **Register**: add a plugin, validate config, store in DB
- **Activate**: start the plugin (begin polling, register tools, attach hooks, open connections)
- **Deactivate**: stop the plugin gracefully (stop polling, unregister tools, detach hooks)
- **Reload**: stop + reconfigure + start (for config changes)
- **Uninstall**: deactivate + remove config from DB

When a plugin activates:
- Its **tools** are registered as a tool group named `plugin:<plugin_id>` (e.g., `plugin:gmail`)
- Its **channel adapter** (if connector) starts listening for inbound events
- Its **pipeline hooks** (if pipeline_hook) are attached at the declared hook points
- Agents with that tool group enabled can now call those tools

### 8.5 How Connector Plugins Interact With the Gateway

**Inbound** (plugin → gateway):
- Plugin receives external event (Telegram update, IMAP email, webhook hit)
- Converts to `GatewayEvent` with `source.kind = "channel"`, `source.id = plugin_id`
- Emits `inbound.message` → gateway routes to correct session → agent runs

**Outbound** (gateway → plugin):
- Agent emits `delivery.send` with `channel = "telegram"` (or `"email"`, etc.)
- Gateway looks up the active plugin for that channel name
- Calls the plugin's `send()` method
- Plugin returns `delivery.result` (success/failure)

**Tools only** (no channel adapter):
- Plugin registers tools but has no inbound/outbound channel
- Agent calls tools directly (e.g., `calendar_list_events`, `notion_search`)
- No gateway routing needed — just tool execution

### 8.6 Built-in Plugin Catalog

#### `webchat` (always active)
- **Type**: built-in
- **Provides**: channel adapter (WebSocket ↔ React UI)
- **Tools**: none (the UI is the interface, not a tool)
- **Auth**: none
- **Cannot be disabled**

#### `telegram`
- **Type**: built-in
- **Provides**: channel adapter + tools
- **Channel**: inbound polling/webhook, outbound sends
- **Tools**: `telegram_send_message`, `telegram_list_chats`
- **Auth**: bot token
- **Config**: bot token, allowed chat-ID allowlist, polling interval
- **Session mapping**: `channel:telegram:<chat_id>`
- **Features**: text + voice message handling, rate-limited sends, long-message chunking

#### `whatsapp` (future)
- **Type**: built-in
- **Provides**: channel adapter + tools
- **Channel**: inbound via WhatsApp Business API or bridge, outbound sends
- **Tools**: `whatsapp_send_message`, `whatsapp_list_chats`
- **Auth**: API token or bridge credentials
- **Config**: phone number, allowed contacts, bridge URL
- **Session mapping**: `channel:whatsapp:<phone_or_chat_id>`

#### `discord` (future)
- **Type**: built-in
- **Provides**: channel adapter + tools
- **Channel**: inbound via bot gateway, outbound sends
- **Tools**: `discord_send_message`, `discord_list_channels`
- **Auth**: bot token
- **Config**: bot token, allowed server/channel IDs
- **Session mapping**: `channel:discord:<channel_id>`

#### `slack` (future)
- **Type**: built-in
- **Provides**: channel adapter + tools
- **Channel**: inbound via Events API, outbound via Web API
- **Tools**: `slack_send_message`, `slack_list_channels`
- **Auth**: OAuth2 (Slack app)
- **Config**: workspace, allowed channels
- **Session mapping**: `channel:slack:<channel_id>`

#### `signal` (future)
- **Type**: built-in
- **Provides**: channel adapter + tools
- **Channel**: inbound via Signal CLI/bridge, outbound sends
- **Tools**: `signal_send_message`
- **Auth**: Signal registration / bridge config
- **Session mapping**: `channel:signal:<phone_or_group_id>`

#### `gmail`
- **Type**: built-in
- **Provides**: channel adapter + tools
- **Channel**: inbound via IMAP idle or Gmail push, outbound via Gmail API
- **Tools**: `gmail_list_messages`, `gmail_get_message`, `gmail_send`, `gmail_mark_read`
- **Auth**: OAuth2 (Google)
- **Config**: account, label filters, polling interval
- **Session mapping**: `channel:email:<account>:<thread_id>`

#### `smtp_imap`
- **Type**: built-in
- **Provides**: channel adapter + tools
- **Channel**: inbound via IMAP poll, outbound via SMTP
- **Tools**: `email_list_messages`, `email_get_message`, `email_send`, `email_mark_read`
- **Auth**: IMAP/SMTP credentials
- **Config**: server, port, SSL, account, polling interval
- **Session mapping**: `channel:email:<account>:<thread_id>`

#### `google_calendar`
- **Type**: built-in
- **Provides**: tools (+ optional trigger adapter)
- **Channel**: optional — calendar event reminders can create `cron`-like sessions
- **Tools**: `calendar_list_events`, `calendar_create_event`, `calendar_update_event`, `calendar_delete_event`, `calendar_preview`
- **Auth**: OAuth2 (Google) — can share credentials with `gmail` plugin
- **Config**: calendar selection, sync window, reminder trigger settings

#### `webhooks`
- **Type**: built-in
- **Provides**: channel adapter (inbound only)
- **Channel**: inbound via `POST /api/trigger` with payload
- **Tools**: none
- **Auth**: optional webhook secret
- **Config**: allowed sources, payload schema validation
- **Session mapping**: `webhook:<uuid>`

#### `documents`
- **Type**: built-in
- **Provides**: tools only (no channel)
- **Channel**: none
- **Auth**: none
- **Dependencies**: `python-pptx`, `python-docx`, `openpyxl`, `fpdf2`, `PyMuPDF` (fitz), `pymupdf4llm`, `pypdf`, `matplotlib`, `Pillow`, `duckdb` (reveal.js assets bundled as static files — no pip dependency)
- **Safety**: read tools classified as `read_only` (open, extract); write/create/edit tools classified as `side_effect` (create/modify files on disk); destructive operations (merge overwriting, encrypt) classified as `destructive`
- **Output**: files saved to `data/uploads/`, returned as `file_id` references integrated with the file system (§21)

**PowerPoint tools:**

| Tool | Description |
|---|---|
| `pptx_create` | Create a new presentation from structured slide specs |
| `pptx_open` | Read an existing `.pptx` — returns structured data (slide count, text, shapes, images, notes, layout metadata) |
| `pptx_edit` | Modify an existing presentation: add/remove/reorder slides, edit text, replace images, update charts, change theme |
| `pptx_list_templates` | List available `.pptx` templates from the template library |
| `pptx_from_markdown` | Convert a markdown outline into a presentation (headings → slides, bullets → bullet points, `![img]()` → images, `---` → slide breaks) |

**Slide layouts** (carried forward from v1, extended):

`title`, `section`, `bullets`, `two_column`, `image_text`, `hero_image`, `chart`, `table`, `quote`, `blank`, `comparison` (new — side-by-side with headers), `timeline` (new — horizontal step visualization)

**Slide features:**
- **Speaker notes**: each slide spec accepts an optional `notes` field — plain text or markdown, rendered as PowerPoint speaker notes
- **Theme / color scheme**: `pptx_create` accepts an optional `theme` parameter:
  ```python
  class SlideTheme(BaseModel):
      primary_color: str = "#212529"      # headings, bars
      accent_color: str = "#0d6efd"       # highlights, chart colors
      background_color: str = "#ffffff"
      text_color: str = "#212529"
      font_family: str = "Calibri"        # applied to all text runs
  ```
  When omitted, defaults are used. Templates override theme settings.
- **Image sources**: AI-generated (via vision provider), web URL, vault file, uploaded file (`file_id` reference), base64 inline
- **Image overlays**: color tint + opacity (e.g., dark overlay on hero images for text readability)
- **Charts**: bar, stacked bar, horizontal bar, line, area, pie, scatter, donut — rendered via matplotlib, embedded as images
- **Tables**: supports header row styling, alternating row shading, configurable border style
- **Template support**: user drops `.pptx` files into `data/pptx_templates/` (resolved via `paths.data_dir()`) and references by name

**HTML presentation tools:**

HTML presentations use [reveal.js](https://revealjs.com/) to produce self-contained, single-file HTML slide decks that open in any browser with no runtime dependencies. Slides share the same structured input format as PowerPoint (layouts, themes, charts) but render as interactive HTML with built-in navigation, speaker notes view, and responsive scaling.

| Tool | Description |
|---|---|
| `html_presentation_create` | Create a self-contained reveal.js HTML presentation from structured slide specs. Accepts the same `SlideTheme` and layout types as `pptx_create`. Output is a single `.html` file with all CSS/JS inlined. |
| `html_presentation_from_markdown` | Convert a markdown outline into a reveal.js HTML presentation. Same slide-break conventions as `pptx_from_markdown` (`---` = slide break, `##` = section). |
| `html_presentation_preview` | Return a localhost preview URL for an HTML presentation file. Leverages Tequila's local server to serve the file with live-reload on re-generation. |

- **Dependencies**: no additional pip packages — reveal.js assets (CSS + JS, ~300 KB) are bundled as static files in `app/plugins/builtin/documents/reveal_assets/` and inlined into the output HTML at generation time.
- **Layout mapping**: all PPTX layouts (`title`, `section`, `bullets`, `two_column`, `image_text`, `hero_image`, `chart`, `table`, `quote`, `blank`, `comparison`, `timeline`) have HTML/CSS equivalents. Charts are embedded as inline SVG (matplotlib `svg` backend) instead of raster images.
- **Speaker notes**: rendered via reveal.js speaker view (`S` key to open).
- **Theme reuse**: `SlideTheme` applies identically — colors and fonts map to CSS custom properties in the generated HTML.
- **Safety**: `html_presentation_create` and `html_presentation_from_markdown` are `side_effect` (create files on disk); `html_presentation_preview` is `read_only`.

**Word document tools:**

| Tool | Description |
|---|---|
| `docx_create` | Create a Word document from structured content (headings, paragraphs, bullet lists, tables, images, page breaks) |
| `docx_open` | Read an existing `.docx` — returns structured content data |
| `docx_edit` | Modify an existing document: append/insert/replace sections, update text, swap images |
| `docx_from_markdown` | Convert markdown to a formatted Word document (headings, bold/italic, code blocks, lists, images, tables) |

**Spreadsheet tools:**

| Tool | Description |
|---|---|
| `xlsx_create` | Create an Excel workbook from structured data (multiple sheets, headers, rows, formulas, conditional formatting, embedded charts) |
| `xlsx_open` | Read an existing `.xlsx` — returns sheet names, headers, row data, formulas |
| `xlsx_edit` | Modify an existing workbook: add/remove sheets, update cells, add formulas, insert charts |

**PDF tools:**

PDF handling uses three libraries, each for its strength:
- **PyMuPDF (fitz) + pymupdf4llm** — reading: text extraction, LLM-optimized markdown output, page rendering to image, table detection, image extraction, structure inspection. 10–100× faster than pdfminer-based alternatives.
- **pypdf** — manipulation: merge, split, rotate, watermark, form fill, encrypt/decrypt. Pure Python, BSD license, clean API for structural operations.
- **fpdf2** — creation: generate new PDFs from structured content (already in spec).

*AGPL note*: PyMuPDF is AGPL-licensed. For Tequila (local-first, single-user, not distributed as a service) this is not a concern — AGPL only triggers on distribution or network service provision.

| Tool | Safety | Description |
|---|---|---|
| `pdf_open` | `read_only` | Read a PDF — returns page count, metadata (author, title, subject, creation date, producer), table of contents / bookmarks, form field list, page dimensions, whether pages are scanned (image-only) vs text-based. Via PyMuPDF. |
| `pdf_read_pages` | `read_only` | Extract content from specified pages as LLM-optimized markdown (headings, tables, lists, code blocks preserved). Accepts `pages` parameter (e.g., `[1, 5, "10-15"]`) and `format` (`"markdown"` or `"text"`). Via pymupdf4llm. |
| `pdf_extract_tables` | `read_only` | Extract tables from a specific page as structured data (list of rows). Uses PyMuPDF's built-in `page.find_tables()`. Returns column headers + row data per table found. |
| `pdf_extract_images` | `read_only` | Extract embedded images from specified pages — saved to `data/uploads/`, returned as `file_id` references. Useful for pulling diagrams/charts for vision analysis. |
| `pdf_page_to_image` | `read_only` | Render a page as a PNG image at configurable DPI (default 150). Returns `file_id`. Critical for scanned PDFs, complex layouts, forms, and infographics — the rendered image can be fed to the vision pipeline (§17.4) for understanding. |
| `pdf_search` | `read_only` | Search for text within a PDF — returns page numbers and surrounding context for each match. |
| `pdf_create` | `side_effect` | Generate a PDF from structured content (text, images, tables, headers/footers, page numbers) via fpdf2. |
| `pdf_from_markdown` | `side_effect` | Convert markdown to a formatted PDF via fpdf2. |
| `pdf_merge` | `destructive` | Merge multiple PDF files into one. Accepts ordered list of `file_id` references + optional page ranges per file. Via pypdf. |
| `pdf_split` | `side_effect` | Split a PDF into multiple files by page ranges (e.g., `[["1-5"], ["6-10"], ["11-"]]`). Returns list of `file_id` references. Via pypdf. |
| `pdf_edit` | `side_effect` | Modify a PDF: rotate pages, add text/image watermark, add/remove password protection, fill form fields (AcroForm). Via pypdf. |

**Scanned PDF strategy**: When `pdf_open` detects image-only pages (no extractable text), it flags them as `scanned: true`. The agent can then:
1. Use `pdf_page_to_image` to render the page as a PNG.
2. Feed the image to `vision_extract_text` (OCR via vision model) or `vision_analyze` for structured extraction.

This vision-fallback path handles any PDF the text extraction can't parse — scanned documents, complex layouts, handwritten notes, infographics.

**CSV / TSV tools:**

| Tool | Safety | Description |
|---|---|---|
| `csv_open` | `read_only` | Parse a CSV/TSV file — returns column names, row count, data types (inferred), sample rows (first 20), file size, delimiter detected. Handles encoding detection (UTF-8, Latin-1, etc.) and various delimiters (comma, tab, semicolon, pipe). |
| `csv_query` | `read_only` | Run a SQL query against a CSV/TSV file via DuckDB. Supports full SQL: `SELECT`, `WHERE`, `GROUP BY`, `ORDER BY`, `JOIN` (across multiple CSVs), aggregations (`SUM`, `AVG`, `COUNT`, `MIN`, `MAX`), window functions. Returns structured results (columns + rows) with configurable `max_rows` (default 100). |
| `csv_to_xlsx` | `side_effect` | Convert a CSV/TSV to an Excel workbook — auto-detects types, applies header formatting, auto-fits column widths. Returns `file_id`. |

```python
@tool(safety="read_only")
def csv_open(
    file: str,                           # file_id or filesystem path
    delimiter: str | None = None,        # auto-detect if None
    encoding: str | None = None,         # auto-detect if None
    has_header: bool = True,
    sample_rows: int = 20,
) -> CsvInfo:
    """Parse a CSV/TSV and return structure + sample data."""

class CsvInfo(BaseModel):
    columns: list[ColumnInfo]            # name, inferred_type, sample_values, null_count
    row_count: int
    delimiter: str
    encoding: str
    file_size_bytes: int
    sample: list[dict]                   # first N rows as dicts

@tool(safety="read_only")
def csv_query(
    file: str,                           # file_id or filesystem path (or list for JOINs)
    query: str,                          # SQL query — table is referenced as "data" (or filename for JOINs)
    max_rows: int = 100,
) -> QueryResult:
    """Run a SQL query against CSV data via DuckDB in-process."""

class QueryResult(BaseModel):
    columns: list[str]
    rows: list[list]                     # list of row arrays
    row_count: int                       # rows returned
    total_rows: int                      # total matching (before max_rows limit)
    truncated: bool
```

**Why DuckDB for CSV queries**: DuckDB runs in-process (no server), reads CSV/Parquet/JSON natively, handles files larger than memory via streaming, and executes analytical SQL 10–100× faster than pandas for aggregation queries. Single dependency, ~30 MB, BSD license.

**Data analysis tool:**

| Tool | Safety | Description |
|---|---|---|
| `data_analyze` | `read_only` | Compute summary statistics and analysis on tabular data (CSV or XLSX). Returns per-column stats (min, max, mean, median, std, null count, unique count, top values for categoricals), correlations between numeric columns, and optional groupby aggregations. |
| `data_to_chart` | `side_effect` | Generate a chart from tabular data — auto-selects chart type based on data shape or accepts explicit type. Reads directly from CSV/XLSX, runs a SQL query for filtering/aggregation, renders via matplotlib. Returns `file_id`. |

```python
@tool(safety="read_only")
def data_analyze(
    file: str,                           # file_id or path (CSV, TSV, XLSX)
    sheet: str | None = None,            # for XLSX — sheet name or index
    columns: list[str] | None = None,    # analyze specific columns (None = all)
    groupby: str | None = None,          # optional groupby column for aggregations
) -> DataSummary:
    """Compute summary statistics on tabular data."""

class DataSummary(BaseModel):
    row_count: int
    column_count: int
    columns: list[ColumnStats]           # per-column: type, min, max, mean, median, std, nulls, uniques, top_values
    correlations: dict[str, dict[str, float]] | None  # numeric column correlation matrix
    groupby_summary: list[dict] | None   # if groupby requested
```

**Chart tools:**

`chart_render` is the low-level chart tool — it takes explicit data and chart config. `data_to_chart` (§8.6 data analysis) is the high-level tool — it reads from a CSV/XLSX file, optionally runs a SQL query for filtering/aggregation, and calls `chart_render` internally.

| Tool | Safety | Description |
|---|---|---|
| `chart_render` | `read_only` | Render a chart from explicit data to a PNG image — bar, stacked bar, horizontal bar, line, area, pie, scatter, donut. Accepts data series, labels, title, colors, dimensions. Returns `file_id`. |

#### `browser`
- **Type**: built-in
- **Provides**: tools only (no channel)
- **Channel**: none
- **Auth**: none
- **Dependencies**: `playwright` (+ browser binaries installed via `playwright install chromium`)
- **Activation**: opt-in — disabled by default. User activates via plugin management UI. First activation triggers browser binary download.
- **Safety**: tools classified from `read_only` (screenshot, extract) through `side_effect` (click, type, navigate) to `destructive` (execute JS, delete profile)
- **Config**: engine (chromium/firefox/webkit), headless mode, viewport size, device emulation, max concurrent sessions, session timeout, proxy
- **Policy**: governed by `WebPolicy` in §17.5 — private network blocking, URL scheme blocking, rate limiting, JS execution gating
- **Tools**: 25 browser automation tools — see §17.3 for full table (navigation, interaction, vision-based interaction, observation, tabs, output, profiles, advanced)

**Browser profile persistence**: profiles stored in `data/browser_profiles/{id}/` — cookies, localStorage, and session data survive across browser sessions. Useful for authenticated browsing (log in once, reuse).

#### `image_generation` (future)
- **Type**: built-in
- **Provides**: tools only (no channel)
- **Channel**: none
- **Auth**: uses LLM provider auth (OpenAI for DALL-E) or API key for third-party services
- **Dependencies**: provider SDK (already installed for LLM access)
- **Safety**: `side_effect` for generation (creates files + incurs cost), `read_only` for listing styles/models

**Image generation tools:**

| Tool | Safety | Description |
|---|---|---|
| `image_generate` | `side_effect` | Generate an image from a text prompt. Accepts: prompt, size (256/512/1024), style (natural/vivid), quality (standard/hd), model (dall-e-3, etc.). Returns `file_id`. |
| `image_edit` | `side_effect` | Edit an existing image with a text prompt (inpainting). Accepts: `file_id` of source image, edit prompt, optional mask `file_id`. Returns `file_id` of edited image. |
| `image_variations` | `side_effect` | Generate variations of an existing image. Accepts: `file_id`, count (1–4). Returns list of `file_id`. |

```python
@tool(safety="side_effect")
def image_generate(
    prompt: str,                         # description of the image to generate
    size: Literal["256x256", "512x512", "1024x1024", "1024x1792", "1792x1024"] = "1024x1024",
    style: Literal["natural", "vivid"] = "natural",
    quality: Literal["standard", "hd"] = "standard",
    model: str = "dall-e-3",
) -> ImageGenResult:
    """Generate an image from a text prompt."""

class ImageGenResult(BaseModel):
    file_id: str                         # saved to data/uploads/
    revised_prompt: str                  # model's revised prompt (what was actually generated)
    size: str
    model: str
    cost_usd: float                      # tracked in budget system
```

*This plugin is marked "future" — it ships after the core platform is stable. The tool definitions are locked in now so the build sequence and safety classifications account for it.*

#### MCP connectors
- **Type**: mcp
- **Provides**: tools only
- **Channel**: none
- **Tools**: whatever the MCP server exposes
- **Auth**: per-server (URL + optional token)
- **Config**: server URL, transport (stdio/SSE), environment variables
- **Management**: CRUD + connection test + tool listing + global refresh

### 8.7 Custom Plugin Contract

A custom plugin is a Python module that implements the `PluginBase` interface:

```python
class PluginBase(ABC):
    plugin_id: str
    name: str
    description: str
    version: str = "1.0.0"
    plugin_type: str                     # "connector", "pipeline_hook", "audit_sink"

    # --- Lifecycle methods (called by plugin registry in order) ---

    async def initialize(self, gateway: Gateway) -> None:
        """Called once when the plugin is first loaded. Store a reference to the
        gateway for emitting events and accessing shared services (auth store,
        config, event router). Default implementation stores `self.gateway = gateway`."""
        self.gateway = gateway

    @abstractmethod
    async def configure(self, config: dict, auth_store: AuthStore) -> None:
        """Apply configuration and auth credentials. Called on install and on
        config update. Must validate config and raise ConfigError if invalid."""

    @abstractmethod
    async def activate(self) -> None:
        """Start the plugin (begin polling, open connections, register hooks, etc.).
        Called after configure() succeeds. Plugin should be fully operational after
        this returns."""

    @abstractmethod
    async def deactivate(self) -> None:
        """Stop the plugin gracefully. Release connections, stop polling,
        unregister hooks. Must be idempotent (safe to call multiple times)."""

    # --- Capability declarations ---

    @abstractmethod
    async def get_tools(self) -> list[ToolDefinition]:
        """Return tool definitions this plugin provides. Called during activation
        to register tools with the tool registry."""

    async def get_channel_adapter(self) -> ChannelAdapter | None:
        """Return a channel adapter if this plugin handles inbound/outbound
        message routing (connector plugins). Default: None."""
        return None

    async def get_hooks(self) -> list[PipelineHook] | None:
        """Return pipeline hooks if this is a pipeline_hook plugin.
        Default: None."""
        return None

    # --- Health & diagnostics ---

    async def health_check(self) -> PluginHealthResult:
        """Check plugin health: auth validity, external service reachability,
        internal state consistency. Called periodically by the plugin registry
        (default: every 5 minutes for active plugins) and on-demand via
        POST /api/plugins/{id}/test. Default implementation returns healthy."""
        return PluginHealthResult(healthy=True)

    async def test(self) -> PluginTestResult:
        """One-time connectivity test. More thorough than health_check —
        validates full auth flow, sends a test request, checks response.
        Called via POST /api/plugins/{id}/test."""
        return PluginTestResult(success=True)

    # --- Configuration introspection ---

    def get_config_schema(self) -> dict:
        """Return JSON Schema for this plugin's configuration. Used by the
        UI to render a config form."""
        return {}

    def get_auth_spec(self) -> PluginAuth | None:
        """Return auth requirements (OAuth2, API key, token, or none)."""
        return None

class PluginHealthResult(BaseModel):
    healthy: bool
    message: str = ""
    details: dict = {}                   # provider-specific diagnostics
    checked_at: datetime

class PluginTestResult(BaseModel):
    success: bool
    message: str = ""
    latency_ms: int | None = None
    details: dict = {}
```

Drop a module into `app/plugins/custom/` that subclasses `PluginBase` → it's auto-discovered on startup and appears in the plugin management UI.

### 8.8 Plugin API

Single unified API surface for all plugin types:

```
GET    /api/plugins                      # list all (installed + available built-ins)
POST   /api/plugins                      # install/register (MCP, custom, or hook)
GET    /api/plugins/{id}                 # details + status + config
PATCH  /api/plugins/{id}                 # update config
DELETE /api/plugins/{id}                 # uninstall
POST   /api/plugins/{id}/auth/start      # begin OAuth flow (if OAuth plugin)
GET    /api/plugins/{id}/auth/callback    # OAuth callback
POST   /api/plugins/{id}/activate        # start plugin
POST   /api/plugins/{id}/deactivate      # stop plugin
POST   /api/plugins/{id}/test            # test connectivity
GET    /api/plugins/{id}/tools           # list tools provided
POST   /api/plugins/refresh              # reload all plugin states
```

This **replaces** the previous separate endpoints for `/api/channels/*`, `/api/email/accounts/*`, `/api/mcp/*`, and `/api/integrations/*`.

### 8.9 Plugin Dependency Management

Plugins may require Python packages or external binaries that aren't bundled with Tequila. The plugin registry manages these dependencies transparently.

#### Dependency declaration

Each plugin declares its dependencies in its plugin metadata:

```python
class PluginDependencies(BaseModel):
    python_packages: list[str] = []      # pip install specs: ["playwright>=1.40", "duckdb>=0.9"]
    system_commands: list[str] = []      # post-install commands: ["playwright install chromium"]
    optional: bool = False               # True = plugin works without these (degraded mode)
```

#### Installation flow

```
User clicks "Activate" on a plugin (or plugin auto-activates on startup)
    │
    ▼
1. CHECK: Are all declared python_packages importable?
    │
    ├─ YES → proceed to activation
    │
    └─ NO → 2. PROMPT: Show install dialog in UI:
                  "Activating [plugin_name] requires installing: playwright (120MB).
                   This will run: pip install playwright && playwright install chromium.
                   [Install & Activate] [Cancel]"
                  │
                  ▼
              3. INSTALL: Run pip install in a subprocess:
                  → Stream install output to UI (progress log panel)
                  → Run system_commands sequentially after pip succeeds
                  │
                  ├─ SUCCESS → 4. VERIFY: re-import packages → proceed to activation
                  │
                  └─ FAILURE → 5. REPORT: Show error in UI:
                                "Failed to install playwright: [error details]
                                 Plugin [name] could not be activated."
                              → Plugin status remains "configured" (not "active")
                              → Error logged + stored in plugin record
```

#### Built-in plugin dependency map

| Plugin | `python_packages` | `system_commands` | Size |
|---|---|---|---|
| `documents` | `python-pptx`, `python-docx`, `openpyxl`, `fpdf2`, `PyMuPDF`, `pymupdf4llm`, `pypdf`, `matplotlib`, `Pillow`, `duckdb` | — | ~180 MB |
| `browser` | `playwright` | `playwright install chromium` | ~280 MB |
| `image_generation` | — (uses existing provider SDK) | — | 0 |
| `telegram` | — (uses httpx, already installed) | — | 0 |
| `gmail` | `google-auth`, `google-auth-oauthlib`, `google-api-python-client` | — | ~20 MB |
| `google_calendar` | (shares with gmail) | — | 0 |
| `smtp_imap` | — (stdlib imaplib + smtplib) | — | 0 |

#### API

```
GET  /api/plugins/{id}/dependencies      # list declared deps + installed status
POST /api/plugins/{id}/dependencies/install  # trigger dependency installation
```

#### Design decisions

- **No auto-install**: Dependencies are never installed without user consent. The UI always prompts first.
- **Isolated venv**: Dependencies install into Tequila's own `.venv` (the application's virtual environment). No global pip pollution.
- **Startup check**: On startup, plugins with `status=active` that have unmet dependencies are set to `status=error` with a message explaining the missing package.
- **Upgrade path**: `POST /api/plugins/{id}/dependencies/install` can also be used to upgrade deps (runs `pip install --upgrade`).

---

## 9) Frontend (React + Vite SPA)

### 9.1 Architecture

- React SPA built with Vite
- Single WebSocket connection to gateway (the only real-time transport)
- REST calls for CRUD operations, config, and non-streaming data
- All real-time data (chat streaming, status updates, notifications) comes through WS events

**Library choices** (locked):

| Concern | Library | Rationale |
|---|---|---|
| State management | **Zustand** | Minimal boilerplate, works natively with React, no context/provider nesting; stores are plain functions |
| Routing | **React Router v7** | De facto standard, supports lazy loading, nested layouts |
| Component primitives | **shadcn/ui** (Radix-based) | Copy-paste-own components, accessible by default, no runtime CSS-in-JS overhead |
| Styling | **Tailwind CSS v4** | Utility-first, consistent spacing/colors, tree-shakes unused styles, pairs naturally with shadcn/ui |
| Server data fetching | **TanStack Query (React Query)** | Declarative cache, automatic stale-while-revalidate, background refetch, pagination helpers |
| Icons | **Lucide React** | Default icons bundled with shadcn/ui; tree-shakeable |
| Graph visualization | **react-force-graph-2d** (+ optional 3D) | Already specified for knowledge graph (§9.2) |

**Data flow patterns**:

```
┌─────────────────────────────────────────────────┐
│                     React SPA                    │
│                                                  │
│  ┌───────────┐  ┌──────────────┐  ┌───────────┐ │
│  │  Zustand   │  │ TanStack     │  │ WS Events │ │
│  │  Stores    │  │ Query Cache  │  │ (gateway)  │ │
│  │ (UI state) │  │ (REST data)  │  │ (realtime) │ │
│  └─────┬─────┘  └──────┬───────┘  └─────┬─────┘ │
│        │               │                │        │
│        └───────────────┼────────────────┘        │
│                        ▼                         │
│                    Components                    │
└──────────────────────────────────────────────────┘
```

- **REST (TanStack Query)**: All CRUD — sessions, agents, config, files, plugins, workflows. Queries auto-refetch on window focus. Mutations use optimistic updates where possible (e.g., sending a message, toggling a setting).
- **WebSocket (Zustand store)**: Streaming tokens, tool approvals, notifications, escalation events, agent status. WS events update Zustand stores directly. The WS store handles reconnection (§2.5a) and event sequencing.
- **UI state (Zustand)**: Sidebar open/closed, active session, active agent, theme, modal state, pending approval queue. No server persistence — these are ephemeral.
- **Separation rule**: Components never call `fetch()` or `ws.send()` directly. All data access goes through hooks backed by TanStack Query or Zustand selectors.

### 9.2 Core UI Surfaces

**Chat interface**:
- Session list / create / resume / delete
- Streaming message display with inline media rendering (§9.2a)
- File cards with local-app quick actions: open file, reveal in Explorer, download, view (§21.6)
- Tool approval action loop (approve / deny / allow-all)
- Agent selector (talk to main agent or any sub-agent directly)
- Voice/audio input with transcription
- Session files panel (§9.2b)

**Agent management**:
- Agent CRUD with soul/personality editor
- Skill management and attachment
- Tool group configuration
- Agent capability dashboard (what tools, what policy)

**Workflow management**:
- Workflow builder (pipeline / parallel modes)
- Execution list / history / detail
- Live execution progress visualization
- Execution response (approval / input continuation)
- Execution cancellation

**Settings**:
- Provider auth setup (OAuth flows, API key entry)
- Plugin management (install, configure, auth, activate/deactivate, test)
- Scheduler task management
- App lock (PIN set / verify / disable)
- Config read / update
- **Web access settings** (§17):
  - Default search provider selector (DuckDuckGo, Brave, Tavily, Google, Bing, SearXNG)
  - Search provider API key entry (per-provider)
  - Fetch policy controls (rate limits, timeout, respect robots.txt toggle)
  - Domain allow-list / block-list editor
  - Cache settings (TTL, clear cache button, cache stats display)
- **Browser settings** (§17.3 — visible only when browser plugin is active):
  - Default engine selector (Chromium / Firefox / WebKit)
  - Headless mode toggle, viewport size, device emulation preset
  - Active browser sessions list (view / force-close)
  - Browser profile manager (list, create, rename, delete)
  - JS execution policy toggle (requires confirmation per call)
- **Vision settings** (§17.4):
  - Preferred vision model selector
  - Fallback model selector
  - Auto-describe uploads toggle
  - OCR enabled toggle
  - Max image size / dimension limits

**Knowledge & memory**:
- Vault note browser (list, read, edit, create, delete)
- **Memory explorer**:
  - Structured list with type filters (identity, preference, fact, experience, task, relationship, skill)
  - Status filters (active, archived, expired)
  - Scope filters (global, agent, session)
  - Decay score visualization (color-coded freshness indicator)
  - Inline edit, archive, pin/unpin actions
  - Promotion queue (memories flagged for review / conflict resolution)
  - Orphan report (unlinked, low-access memories — candidates for cleanup)
  - Memory history timeline (audit trail per memory)
- **Entity explorer**:
  - Entity list with type filters (person, org, project, location, concept, etc.)
  - Entity detail panel: properties, aliases, linked memories, relationship graph
  - Merge UI: select two entities → preview merge → confirm
  - Entity creation form
- **Agent memory panel** (in agent detail view):
  - Agent-scoped memories (private namespace)
  - Pinned memories for current session
  - Always-recall memories (identity, preferences)
- Search interface (full-text + semantic, cross-domain)
- Reindex triggers

**Knowledge graph** (Obsidian-style interactive visualization):
- Force-directed graph rendered via `react-force-graph-2d` (with optional 3D toggle via `react-force-graph-3d`)
- **Node rendering**: nodes colored and sized by type (notes = blue, memories = green, entities = red, agents = orange, sessions = gray, tags = purple, files = teal); size proportional to connection count
- **Edge rendering**: edges styled by type (wiki_links = solid, semantic = dashed, extracted_from = dotted, entity_relationship = thick solid with label, linked_to = thin solid), thickness proportional to weight
- **Interactions**:
  - Click node → open detail panel (note content, memory text, entity properties + linked memories, agent info)
  - Hover node → highlight direct connections, dim unrelated nodes
  - Drag to reposition nodes; zoom and pan
  - Double-click node → center graph on that node and expand its neighborhood
  - Right-click → context menu (open note, edit, create link, delete link, find similar)
- **Filters panel** (sidebar):
  - Toggle node types on/off (notes, memories, entities, agents, sessions, files, tags)
  - Toggle edge types on/off (wiki_link, semantic_similar, extracted_from, entity_relationship, linked_to, etc.)
  - Minimum similarity weight slider (for semantic edges)
  - Date range filter
  - Agent scope filter
  - Search-within-graph (highlight matching nodes)
- **Views**:
  - **Full graph**: all nodes, useful for exploring the overall knowledge structure
  - **Ego graph**: centered on a selected node, configurable depth (1–3 hops)
  - **Orphan view**: nodes with no connections (candidates for linking or cleanup)
  - **Cluster view**: auto-detected communities (via connected components or modularity)
- **Graph stats bar**: total nodes, total edges, orphan count, most-connected nodes
- **Live updates**: new nodes/edges pushed via WebSocket events, graph animates additions in real-time

### 9.2a Inline Media Rendering

Chat messages containing files (via `content_blocks` or `file_ids`) render rich inline previews directly in the conversation. This section defines the rendering rules for each media type and the shared viewer components.

#### Image rendering & lightbox

- **Inline**: images render as thumbnails (max 300px width, aspect-ratio preserved) directly in the message bubble.
- **Multi-image**: messages with multiple images render a grid (2 columns, up to 4 visible, "+N more" badge if >4).
- **Lightbox** (click any image thumbnail):
  - Full-resolution image centered in a dimmed overlay.
  - Zoom: scroll-wheel zoom (1x → 5x), pinch-to-zoom on touch. Double-click to toggle fit/actual-size.
  - Pan: click-and-drag when zoomed.
  - Navigation: left/right arrow keys (or swipe) to cycle through images in the same message.
  - Actions: download button, copy-to-clipboard, close (Esc or click outside).
  - Keyboard: `Esc` to close, `←`/`→` to navigate, `+`/`-` to zoom.
  - Implementation: shadcn/ui `Dialog` + CSS transforms for zoom/pan. No additional library required.

#### PDF viewer

- **Inline**: first-page thumbnail (from `GET /api/files/{id}/preview`) + filename + page count badge.
- **Viewer** (click thumbnail or "View" action):
  - Opens in a **side panel** (right rail, resizable, 40% default width) — not a modal, so the user can reference the conversation while reading the document.
  - Renders via browser-native `<iframe>` embedding (`<iframe src="/api/files/{id}/download" type="application/pdf">`). This provides page navigation, zoom, search, and print — all handled by the browser's built-in PDF viewer — with zero additional dependencies.
  - Fallback: if the browser blocks iframe PDF embedding (rare), falls back to a full-page download prompt.
  - Panel header: filename, page count, download button, open-with-OS-app button, close button.
  - Panel persists across messages — user can click a different PDF to replace the panel content without closing.
  - **Future upgrade path**: replace `<iframe>` with `react-pdf` (pdf.js wrapper) for annotation, highlighting, and custom page navigation. Not needed for v1.

#### Code & text file rendering

- **Inline**: syntax-highlighted preview of the first 30 lines in a collapsible code block within the message.
- Language detection: inferred from file extension (`.py` → Python, `.js` → JavaScript, etc.) or MIME type.
- Syntax highlighting: uses the same highlighting library as markdown code blocks in assistant messages (Shiki or Prism, chosen during Sprint 02 frontend setup).
- "Show all" expands to full file content (scrollable, max-height 500px before requiring "Open in viewer").
- "View" action opens the same side panel (shared with PDF viewer) with full syntax-highlighted content + line numbers.

#### Audio rendering

- Inline `<audio>` player widget: play/pause button, seek bar, current time / duration, playback speed selector (0.5x–2x).
- If transcription is available (§22), a "Show transcript" toggle reveals the text below the player.

#### Rendering rules summary

| Content type | Inline rendering | "View" target |
|---|---|---|
| `image/*` | Thumbnail (300px max width) | Image lightbox (full-res overlay) |
| `application/pdf` | First-page thumbnail + name + pages | Side panel (iframe PDF viewer) |
| `text/*`, code files | Syntax-highlighted 30-line preview | Side panel (full content + line numbers) |
| `audio/*` | Audio player widget | — (plays inline) |
| Office docs (DOCX, XLSX, PPTX) | File card (icon + name + size) | OS default app (via "Open file" action) |
| Other | File card (icon + name + size) | OS default app or download |

### 9.2b Session Files Panel

A collapsible panel listing all files associated with the current session — both user-uploaded and agent-generated. Gives the user a single place to find and act on every file in the conversation without scrolling through messages.

**Location**: right sidebar tab (alongside any other session detail panels). Toggled via a 📎 (paperclip) icon in the chat header or `Ctrl+Shift+F` keyboard shortcut.

**Data source**: `GET /api/sessions/{id}/files` — returns all files where `session_id` matches OR `file_id` appears in any message's `file_ids` in the session.

```python
class SessionFileEntry(BaseModel):
    file_id: str
    filename: str
    mime_type: str
    size_bytes: int
    origin: Literal["upload", "agent_generated"]   # how the file got here
    message_id: str | None = None                   # which message references this file (first reference)
    pinned: bool = False
    created_at: datetime
```

**Panel layout**:

```
┌─────────────────────────────────────┐
│ 📎 Session Files (12)       [✕]     │
│─────────────────────────────────────│
│ Search files...              🔍     │
│─────────────────────────────────────│
│ ▾ Uploads (4)                       │
│   📄 report_draft.pdf    1.2 MB  ⋮ │
│   🖼 screenshot.png      340 KB  ⋮ │
│   📊 data.csv            89 KB   ⋮ │
│   📄 notes.md            12 KB   ⋮ │
│                                     │
│ ▾ Agent Generated (8)               │
│   📄 report_final.pdf   2.1 MB  📌⋮│
│   📊 chart_revenue.png  156 KB   ⋮ │
│   📄 summary.md          8 KB    ⋮ │
│   [... more files ...]              │
└─────────────────────────────────────┘
```

**Features**:
- **Grouped by origin**: "Uploads" (user-attached files) and "Agent Generated" (files created by tool calls) as collapsible sections.
- **Search/filter**: text search by filename. Filter by MIME type category (images, documents, audio, other).
- **Per-file actions** (via `⋮` overflow menu): same quick actions as file cards in chat (§21.6) — Open file, Reveal in Explorer, Download, View, Copy path, Pin/Unpin.
- **Click filename**: scrolls the chat to the message that first references this file and highlights it briefly.
- **Pin indicator**: 📌 badge on pinned files (exempt from cleanup — §21.7).
- **Sort**: by date (newest first, default), by name, by size.
- **Empty state**: "No files in this session. Upload a file or ask the agent to create one."

**API**:

```
GET /api/sessions/{id}/files            — list all files for a session
  Query params: ?origin=upload|agent_generated&mime_category=image|document|audio|other&sort=date|name|size
  Response: { "files": [SessionFileEntry, ...], "total": int }
```

### 9.3 Theming & Dark Mode

The UI supports dark, light, and system-follow color schemes via CSS custom properties. Theme preference is persisted locally and respected immediately on load (no flash of wrong theme).

**Available modes**:

| Mode | Behavior |
|---|---|
| `light` | Light background, dark text. Default for first-time users. |
| `dark` | Dark background, light text. Reduced eye strain in low-light environments. |
| `system` | Follows `prefers-color-scheme` media query. Updates in real-time if the OS theme changes. |

**Implementation**:
- A `data-theme` attribute on `<html>` controls the active theme (`light` | `dark`).
- All colors are defined as CSS custom properties (Tailwind's `@theme` layer in v4): `--color-bg`, `--color-text`, `--color-primary`, `--color-border`, etc.
- shadcn/ui components inherit theme variables automatically — no per-component overrides needed.
- Theme toggle: a three-state button (☀️ / 🌙 / 🖥️) in the sidebar header or settings top bar.

**Persistence**:
- Stored in `localStorage` under `tequila.theme` (`"light"` | `"dark"` | `"system"`).
- Applied synchronously in a `<script>` block in `<head>` (before React hydrates) to prevent theme flash.
- Not synced to server config — theme is per-browser, not per-user.

**Accent customization** (stretch goal):
- Users can select a primary accent color from a preset palette (blue, green, purple, amber, rose, teal).
- Accent selection updates `--color-primary` and related variables.
- Stored alongside theme in `localStorage` as `tequila.accent`.

### 9.4 Keyboard Shortcuts

Power users benefit from keyboard-driven navigation. All shortcuts use standard modifier keys and are discoverable via a help overlay.

**Global shortcuts** (active anywhere in the app):

| Shortcut | Action |
|---|---|
| `Ctrl+K` | Open command palette / quick search |
| `Ctrl+N` | New session |
| `Ctrl+Shift+N` | New session with agent picker |
| `Ctrl+/` | Toggle sidebar |
| `Ctrl+,` | Open settings |
| `Ctrl+Shift+?` | Show keyboard shortcuts help overlay |
| `Escape` | Close any open modal / dropdown / palette |

**Chat shortcuts** (active when chat is focused):

| Shortcut | Action |
|---|---|
| `Enter` | Send message (unless Shift held) |
| `Shift+Enter` | New line in message input |
| `Ctrl+↑` | Edit last sent message (opens edit mode) |
| `↑` (when input empty) | Recall last sent message into input |
| `Ctrl+Shift+C` | Copy last assistant response to clipboard |
| `Ctrl+Shift+R` | Regenerate last assistant response |
| `Ctrl+Shift+F` | Toggle session files panel (§9.2b) |

**Session navigation shortcuts**:

| Shortcut | Action |
|---|---|
| `Alt+↑` / `Alt+↓` | Navigate to previous / next session in sidebar list |
| `Ctrl+W` | Archive current session |
| `Ctrl+Shift+E` | Export current session transcript |

**Tool approval shortcuts** (active when approval banner is visible):

| Shortcut | Action |
|---|---|
| `Enter` or `Y` | Approve pending tool call |
| `N` | Deny pending tool call |
| `A` | Allow all remaining tool calls for this turn |

**Discoverability**:
- The help overlay (`Ctrl+Shift+?`) shows all available shortcuts organized by category.
- Shortcuts are also listed in Settings → Keyboard Shortcuts (read-only in v1; customizable in future).
- Tooltips on buttons include the shortcut hint (e.g., "New Session (Ctrl+N)").

### 9.5 Session Search & Filtering

The session sidebar includes search and filter controls to help users find conversations quickly, especially as the session list grows.

**Search bar** (top of session sidebar):
- Text input with debounced search (300ms delay).
- Searches across: session `title`, session `summary`, and agent `name`.
- Results are highlighted in the session list, with matching text snippets shown below the title.
- When the search field is active, the session list is replaced with search results sorted by relevance.

**Filter controls** (collapsible filter bar below search):

| Filter | Options | Default |
|---|---|---|
| **Status** | Active, Idle, Archived, All | Active |
| **Kind** | user, channel, cron, webhook, workflow, All | All |
| **Agent** | Dropdown of all agents | All |
| **Date range** | Start / end date pickers | None (show all) |

**Sort options** (dropdown next to search bar):

| Sort | Behavior |
|---|---|
| **Last activity** (default) | `last_message_at DESC` — most recently active first |
| **Created** | `created_at DESC` — newest first |
| **Message count** | `message_count DESC` — most active sessions first |
| **Title A–Z** | Alphabetical sort on title |

**API support** (extends existing `GET /api/sessions`):
```
GET /api/sessions?q=budget+meeting&status=active&kind=user&agent_id=main&sort=last_activity&order=desc&limit=20&offset=0
```

All filter and sort state is stored in the Zustand UI store — not persisted to server. Clearing the search restores the default view.

---

## 10) Multi-Agent Workflows

### 10.1 Pipeline Mode

Sequential step execution:
1. Step 1 → Agent A processes → output
2. Step 2 → Agent B receives step 1 output → processes → output
3. ... continues through all steps
4. Final step output = workflow result

Context passing configurable per step (full output, summary, or specific fields).

### 10.2 Parallel Mode

1. Entry agent produces dispatch context
2. Fan-out: multiple worker agents execute in parallel (each in spawned sessions)
3. Worker results collected
4. Synthesis agent merges results into final response

### 10.3 Workflow API

- Workflow CRUD (definition management)
- Run-now trigger
- Execution list / history / detail
- Execution response (approval / input continuation at any step)
- Execution cancellation
- Step lifecycle events: step-start, step-done, step-error (streamed to UI)

---

## 11) Safety, Trust, and Approval Controls

### 11.1 Tool Safety Classification

Every tool has a safety level. The four canonical level names are `read_only`, `side_effect`, `destructive`, and `critical`.

- **`read_only`** — no side effects:
  - Filesystem: `fs_read_file`, `fs_list_dir`, `fs_search`, `fs_tree`, `fs_info`, `fs_get_working_dir`
  - Web: `web_search`, `web_fetch`
  - Browser: `browser_screenshot`, `browser_extract`, `browser_get_elements`, `browser_get_a11y_tree`, `browser_capture_network`, `browser_scroll`, `browser_list_tabs`, `browser_save_pdf`, `browser_profile_list`
  - Vision: `vision_describe`, `vision_extract_text`, `vision_compare`, `vision_analyze`
  - Memory: `memory_search`, `memory_list`, `entity_search`
  - Documents: `pdf_open`, `pdf_read_pages`, `pdf_extract_tables`, `pdf_extract_images`, `pdf_page_to_image`, `pdf_search`, `csv_open`, `csv_query`, `data_analyze`, `xlsx_open`, `docx_open`, `pptx_open`, `chart_render`
  - Sessions: `sessions_list`, `sessions_history`
  - Search: `search`
  - Audio: `transcribe`

- **`side_effect`** — reversible side effects:
  - Filesystem: `fs_write_file`, `fs_append_file`, `fs_mkdir`, `fs_copy`, `fs_set_working_dir`
  - Browser: `browser_open`, `browser_navigate`, `browser_back`, `browser_forward`, `browser_close`, `browser_click`, `browser_type`, `browser_select`, `browser_act`, `browser_new_tab`, `browser_switch_tab`, `browser_close_tab`, `browser_download`, `browser_profile_create`
  - Memory: `memory_save`, `memory_update`, `memory_pin`, `memory_unpin`, `memory_link`, `memory_extract_now`, `entity_create`, `entity_update`, `entity_merge`
  - Documents: `pdf_create`, `pdf_from_markdown`, `pdf_split`, `pdf_edit`, `csv_to_xlsx`, `xlsx_create`, `xlsx_edit`, `docx_create`, `docx_edit`, `docx_from_markdown`, `pptx_create`, `pptx_edit`, `pptx_from_markdown`, `data_to_chart`
  - Sessions: `sessions_send`, `sessions_spawn`

- **`destructive`** — irreversible side effects:
  - Filesystem: `fs_delete`, `fs_move`
  - Browser: `browser_execute_js`, `browser_profile_delete`
  - Memory: `memory_forget`
  - Documents: `pdf_merge`
  - Code: `code_exec`

- **`critical`** — high-impact external actions:
  - Channel sends: `telegram_send_message`, `gmail_send`, `email_send`, `whatsapp_send_message`, `discord_send_message`, `slack_send_message`, `signal_send_message`
  - Agent management: modify agent config, `calendar_create_event`, `calendar_update_event`, `calendar_delete_event`

*Future (Phase 7)*: `image_generate`, `image_edit`, `image_variations` will be classified as `side_effect` (file creation + API cost).

### 11.2 Approval Gates

- `SessionPolicy.require_confirmation` lists tools that need user approval before execution
- Default: all `destructive` and `critical` tools require confirmation
- User can "allow all" for a session to bypass confirmation for the remainder of that session
- Approval requests emitted as gateway events; UI renders approve/deny dialog

### 11.3 Filesystem Scope Enforcement

- Configurable file scope: all / documents / custom paths + extra scoped paths
- Every file tool validates path against configured scope before execution
- Out-of-scope access denied with clear error

### 11.4 Agent Self-Modification Rules

- Main agent (`is_admin=True`): can modify any agent's config, skills, tools, soul
- Sub-agents (`is_admin=False`): can modify only their own session state and private memory
- No agent can delete itself or the main agent
- Config changes logged to audit trail

---

## 12) Observability and Audit

### 12.1 Audit Log

Every gateway event is audit-logged:
- Event type, source, session key, timestamp
- Outcome (success/failure/error)
- Tool calls: tool name, input summary, result summary, execution time
- Delivery: channel, recipient, status

### 12.2 Metrics

- Per-agent: turn count, token usage, tool call frequency, error rate
- Per-session: message count, duration, compression triggers
- Per-integration: send/receive success/failure, latency
- Per-tool: usage frequency, failure rate, timeout count
- System: gateway event throughput, active sessions, memory usage

### 12.3 Retention

- Audit log rotation: configurable retention period, cleanup on startup
- Vault history snapshots: periodic cleanup
- Archived sessions: configurable auto-delete after N days
- Memory extracts: lifecycle-managed (decay → archive → consolidation). Archived memories retained but excluded from recall. User can permanently delete via UI.

### 12.4 Structured Application Logging

All application components emit structured JSON logs for debugging, performance analysis, and troubleshooting.

```python
class LogConfig(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    format: Literal["json", "text"] = "json"       # json for machine parsing, text for console
    output: Literal["stdout", "file", "both"] = "both"
    log_file: str = "data/logs/tequila.log"
    max_file_size_mb: int = 50                       # rotate after this size
    max_files: int = 5                               # keep last N rotated files
    per_module_levels: dict[str, str] = {}           # override level per module
        # e.g., {"agent.turn_loop": "DEBUG", "plugins.telegram": "WARNING"}
```

**Log entry structure** (JSON mode):

```json
{
    "ts": "2026-03-13T10:30:15.123Z",
    "level": "INFO",
    "module": "agent.turn_loop",
    "message": "Turn completed",
    "session_id": "sess_abc123",
    "agent_id": "main",
    "duration_ms": 2340,
    "input_tokens": 1520,
    "output_tokens": 430,
    "tool_calls": 2,
    "provider": "anthropic",
    "model": "claude-sonnet-4-20250514"
}
```

**Key log points** (each module logs its critical operations):

| Module | Key events logged |
|---|---|
| `gateway` | Event dispatch, routing decisions, policy enforcement |
| `agent.turn_loop` | Turn start/end, token counts, tool calls, errors, retries |
| `agent.prompt_assembly` | Budget allocation, trimming decisions, compression triggers |
| `memory.extraction` | Pipeline steps, duplicates found, conflicts detected, entities created |
| `memory.recall` | Recall stages, result counts, cache hits |
| `memory.lifecycle` | Decay calculations, consolidation merges, archives |
| `providers` | API calls, latency, errors, circuit breaker state changes |
| `plugins` | Lifecycle events, health checks, tool registrations |
| `scheduler` | Job execution, skip reasons, next-run times |
| `web` | Search queries, fetch URLs, cache hits/misses, browser sessions |
| `auth` | Token refresh, OAuth flows, auth failures (no secrets logged) |

**Security**: Sensitive data (API keys, tokens, user passwords) is NEVER logged. Tool call arguments are logged at DEBUG level only, and PII-containing fields are redacted.

**API access**: `GET /api/logs?level=ERROR&module=agent&limit=100&since=2026-03-13` returns recent log entries matching the filter. Useful for the UI's diagnostics panel.

---

## 13) API Surface Map

**API versioning**: All endpoints are served at `/api/...` (unversioned). If breaking changes are ever needed, the server will support a `X-API-Version` request header with a default of `1`. This avoids URL churn while preserving a migration path.

### 13.1 REST Endpoints

```
# System
GET    /api/status                       # full system status (see §13.3)
GET    /api/health                       # lightweight liveness probe (see §13.3)
POST   /api/setup                        # first-run setup wizard (see §15.1)
GET    /api/config
PATCH  /api/config
GET    /api/config/providers
GET    /api/config/models
POST   /api/config/test-key
POST   /api/lock/set
POST   /api/lock/verify
POST   /api/lock/disable
GET    /api/lock/status

# Auth
POST   /api/auth/codex/start
POST   /api/auth/codex/callback
POST   /api/auth/codex/refresh
POST   /api/auth/codex/logout
GET    /api/auth/codex/status
POST   /api/auth/anthropic/start
POST   /api/auth/anthropic/callback
POST   /api/auth/anthropic/refresh
POST   /api/auth/anthropic/logout
GET    /api/auth/anthropic/status
GET    /api/oauth2/gmail/start
GET    /api/oauth2/gmail/callback

# Sessions
GET    /api/sessions
POST   /api/sessions
GET    /api/sessions/{id}
PATCH  /api/sessions/{id}
DELETE /api/sessions/{id}
GET    /api/sessions/{id}/messages
GET    /api/sessions/{id}/export         # transcript export (markdown, JSON, PDF)
POST   /api/sessions/{id}/regenerate     # regenerate an assistant message (§3.5)
POST   /api/sessions/{id}/edit           # edit-and-resubmit a user message (§3.5)
POST   /api/sessions/{id}/escalate       # manually trigger escalation (§4.2a)
POST   /api/sessions/{id}/archive        # archive a session (§3.7)
POST   /api/sessions/{id}/unarchive      # restore archived session to active (§3.7)
GET    /api/sessions/{id}/files           # list files in session — uploads + agent-generated (§9.2b)
GET    /api/sessions/search
GET    /api/sessions/analytics

# Messages
POST   /api/messages/{id}/feedback       # submit thumbs up/down (§3.6)
DELETE /api/messages/{id}/feedback       # remove feedback (§3.6)

# Agents
GET    /api/agents
POST   /api/agents
GET    /api/agents/{id}
PATCH  /api/agents/{id}
DELETE /api/agents/{id}
POST   /api/agents/{id}/clone
POST   /api/agents/{id}/export
POST   /api/agents/import
POST   /api/agents/{id}/reset
POST   /api/agents/{id}/run
GET    /api/agents/{id}/runs
GET    /api/agents/{id}/soul
PUT    /api/agents/{id}/soul
POST   /api/agents/{id}/soul/generate
GET    /api/agents/{id}/tools
PUT    /api/agents/{id}/tools
GET    /api/agents/{id}/skills            # list skills assigned to agent (§4.5.5)
POST   /api/agents/{id}/skills            # assign skill(s) to agent (§4.5.5)
DELETE /api/agents/{id}/skills/{skill_id} # remove skill from agent (§4.5.5)
POST   /api/agent/quick-turn             # one-shot agent call without a persistent session (see below)

# Skills
GET    /api/skills
POST   /api/skills
GET    /api/skills/{id}
PATCH  /api/skills/{id}
DELETE /api/skills/{id}
POST   /api/skills/import
GET    /api/skills/{id}/export            # export skill as JSON/YAML (§4.5.5)
POST   /api/skills/{id}/clone            # clone skill (§4.5.5)
GET    /api/skills/{id}/resources          # list Level 3 resources for a skill (§4.5.7)
POST   /api/skills/{id}/resources          # create a resource for a skill (§4.5.7)
GET    /api/skills/{id}/resources/{rid}    # get a specific resource (§4.5.7)
PATCH  /api/skills/{id}/resources/{rid}    # update a resource (§4.5.7)
DELETE /api/skills/{id}/resources/{rid}    # delete a resource (§4.5.7)

# Tool Groups
GET    /api/tools/groups
PATCH  /api/tools/groups/{name}

# Workflows
GET    /api/workflows
POST   /api/workflows
GET    /api/workflows/{id}
PATCH  /api/workflows/{id}
DELETE /api/workflows/{id}
POST   /api/workflows/{id}/run
GET    /api/workflow-executions
GET    /api/workflow-executions/{id}
POST   /api/workflow-executions/{id}/respond
POST   /api/workflow-executions/{id}/cancel

# Scheduler
GET    /api/scheduler/tasks
POST   /api/scheduler/tasks
GET    /api/scheduler/tasks/{id}
PATCH  /api/scheduler/tasks/{id}
DELETE /api/scheduler/tasks/{id}
POST   /api/scheduler/tasks/{id}/run
POST   /api/scheduler/tasks/{id}/toggle

# Memory & Entities
POST   /api/memory/extract                # trigger extraction pipeline on session
GET    /api/memory/extracts                # list memories (filter by type, entity, scope, status)
GET    /api/memory/extracts/{id}           # single memory detail + history
PATCH  /api/memory/extracts/{id}           # update memory content/type/tags
DELETE /api/memory/extracts/{id}           # archive (soft-delete) a memory
POST   /api/memory/extracts/{id}/pin       # pin memory to a session
POST   /api/memory/extracts/{id}/unpin     # unpin memory from a session
GET    /api/memory/extracts/{id}/history    # audit trail for a memory
GET    /api/memory/promotion-queue          # memories flagged for review
GET    /api/memory/index-status
POST   /api/memory/reindex
GET    /api/memory/orphans                  # memories with no entity links, low access
POST   /api/memory/consolidate             # trigger consolidation run
GET    /api/entities                        # list entities (filter by type, name)
POST   /api/entities                        # create entity
GET    /api/entities/{id}                   # entity detail + linked memories
PATCH  /api/entities/{id}                   # update entity properties/aliases
DELETE /api/entities/{id}                   # soft-delete entity
POST   /api/entities/merge                  # merge two entities

# Knowledge Graph
GET    /api/graph
GET    /api/graph/node/{id}
GET    /api/graph/node/{id}/neighborhood
GET    /api/graph/stats
GET    /api/graph/orphans
POST   /api/graph/edges
DELETE /api/graph/edges/{id}
POST   /api/graph/rebuild

# Search
GET    /api/search
POST   /api/search/reindex

# Files & Uploads
POST   /api/files/upload
GET    /api/files/{id}
GET    /api/files/{id}/download           # download file with Content-Disposition (§21.6)
GET    /api/files/{id}/preview            # thumbnail or first-page render (§21.6)
DELETE /api/files/{id}
POST   /api/files/{id}/pin               # pin file for permanent retention (§21.7)
DELETE /api/files/{id}/pin               # unpin file (§21.7)
POST   /api/files/{id}/open              # open file with OS default app — local-only (§21.6)
POST   /api/files/{id}/reveal            # reveal file in Explorer — local-only (§21.6)
POST   /api/files/cleanup                # trigger manual cleanup run (§21.7)
GET    /api/files/stats                   # storage statistics (§21.7)

# Budget & Cost Tracking
GET    /api/budget/summary
GET    /api/budget/by-agent
GET    /api/budget/by-provider
GET    /api/budget/caps
PUT    /api/budget/caps
GET    /api/budget/pricing
PUT    /api/budget/pricing

# Notifications
GET    /api/notifications/preferences
PUT    /api/notifications/preferences
GET    /api/notifications/history
PATCH  /api/notifications/{id}/read
POST   /api/notifications/read-all

# Backup & Restore
POST   /api/backup
GET    /api/backup/list
GET    /api/backup/{id}/download
POST   /api/backup/restore
GET    /api/backup/config
PUT    /api/backup/config

# Integrations — Plugins (unified, replaces channels/email/mcp/telegram)
GET    /api/plugins
POST   /api/plugins
GET    /api/plugins/{id}
PATCH  /api/plugins/{id}
DELETE /api/plugins/{id}
POST   /api/plugins/{id}/auth/start
GET    /api/plugins/{id}/auth/callback
POST   /api/plugins/{id}/activate
POST   /api/plugins/{id}/deactivate
POST   /api/plugins/{id}/test
GET    /api/plugins/{id}/tools
GET    /api/plugins/{id}/dependencies     # list declared deps + installed status (§8.9)
POST   /api/plugins/{id}/dependencies/install  # trigger dependency installation (§8.9)
POST   /api/plugins/refresh

# Knowledge Sources (§5.14)
GET    /api/knowledge-sources                     # list all registered sources
POST   /api/knowledge-sources                     # register a new source
GET    /api/knowledge-sources/{id}                # source details + status + health
PATCH  /api/knowledge-sources/{id}                # update source config
DELETE /api/knowledge-sources/{id}                # unregister source
POST   /api/knowledge-sources/{id}/activate       # activate source
POST   /api/knowledge-sources/{id}/deactivate     # deactivate source
POST   /api/knowledge-sources/{id}/test           # test connectivity + sample results
GET    /api/knowledge-sources/{id}/stats           # document count, avg query time, error rate
POST   /api/knowledge-sources/search              # federated search (UI / testing)

# Triggers
POST   /api/trigger

# Web Access & Search (§17)
GET    /api/web/config                   # get web policy + search config
PATCH  /api/web/config                   # update web policy + search config
GET    /api/web/search-providers         # list available search providers + status (configured, API key present)
POST   /api/web/cache/clear              # clear web cache (search + fetch)
GET    /api/web/cache/stats              # cache hit/miss stats, size, entry count

# Browser (§17.3 — only available when browser plugin is active)
GET    /api/browser/sessions             # list active browser sessions
DELETE /api/browser/sessions/{id}        # force-close a browser session
GET    /api/browser/profiles             # list saved browser profiles
POST   /api/browser/profiles             # create a named profile
DELETE /api/browser/profiles/{id}        # delete profile + stored cookies/data

# Vision (§17.4)
GET    /api/vision/config                # get vision config (preferred model, fallback, OCR, etc.)
PATCH  /api/vision/config                # update vision config

# Session Transcript Export (§13.4)
GET    /api/sessions/{id}/export?format=markdown   # export session as markdown
GET    /api/sessions/{id}/export?format=json       # export session as structured JSON
GET    /api/sessions/{id}/export?format=pdf        # export session as formatted PDF

# Observability
GET    /api/logs                          # query structured application logs (§12.4)
GET    /api/audit                         # query audit log entries
```

**`POST /api/agent/quick-turn`** — Execute a one-shot agent call without creating a persistent session. Accepts `{ "agent_id": "main", "message": "...", "model": "provider:model" }`. Creates a temporary session, runs one turn, returns the full response (text + any tool results), and archives the session immediately. Useful for programmatic integrations and quick single-question queries that don't need conversation history.

### 13.2 WebSocket Endpoint

```
WS /api/ws
```

Single connection. Typed JSON frames per §2.4. Handles:
- Connect handshake
- Session create / resume
- Message send
- Agent streaming (server push)
- Tool approval actions
- UI events (typing indicators, status updates, notifications)

### 13.3 Health & Status Endpoints

Two endpoints for system observability, with different purposes:

**`GET /api/health`** — Lightweight liveness probe. Returns `200 OK` if the server is running and the database is accessible. No auth required. Used by monitoring tools and the frontend's connection status indicator.

```json
{
  "status": "ok",
  "uptime_s": 3600,
  "version": "2.0.0"
}
```

**`GET /api/status`** — Full system status dashboard. Returns detailed information about every subsystem. Used by the frontend's system status panel and for diagnostics.

```python
class SystemStatus(BaseModel):
    status: Literal["ok", "degraded", "error"]
    version: str
    uptime_s: int
    started_at: datetime

    # --- Providers ---
    providers: list[ProviderStatus]      # per-provider: available, circuit state, model count, last error

    # --- Plugins ---
    plugins: list[PluginStatus]          # per-plugin: status, health check result, last error

    # --- Database ---
    db_size_mb: float
    db_wal_size_mb: float

    # --- Memory system ---
    memory_extract_count: int
    entity_count: int
    embedding_index_status: Literal["ready", "building", "error"]
    last_consolidation: datetime | None

    # --- Scheduler ---
    scheduler_status: Literal["running", "stopped"]
    pending_jobs: int
    next_job_at: datetime | None

    # --- Active sessions ---
    active_session_count: int
    active_turn_count: int               # turns currently in-flight

    # --- Budget ---
    today_spend_usd: float
    month_spend_usd: float
    budget_cap_status: Literal["ok", "warning", "exceeded"] | None

class ProviderStatus(BaseModel):
    provider_id: str
    available: bool
    circuit_state: Literal["closed", "open", "half_open"]
    model_count: int
    last_error: str | None = None

class PluginStatus(BaseModel):
    plugin_id: str
    status: str                          # "active", "error", "disabled", etc.
    healthy: bool | None = None          # last health check result
    last_error: str | None = None
```

### 13.4 Session Transcript Export

Sessions can be exported as formatted transcripts for sharing, archival, or external use:

```
GET /api/sessions/{id}/export?format=markdown
GET /api/sessions/{id}/export?format=json
GET /api/sessions/{id}/export?format=pdf
```

| Format | Content-Type | Details |
|---|---|---|
| `markdown` | `text/markdown` | Human-readable transcript: session metadata header, then chronological messages with role labels, timestamps, tool call summaries, and file references. |
| `json` | `application/json` | Structured export: full session record + all messages with complete metadata (tool calls, provenance, file_ids, costs). Machine-readable for import/migration. |
| `pdf` | `application/pdf` | Formatted PDF via fpdf2: header with session info (agent, dates, message count), styled message blocks with role colors, inline tool results, page numbers. |

**Export options** (query parameters):
- `include_tool_calls=true|false` — include/exclude tool call details (default: true)
- `include_system_messages=true|false` — include/exclude system messages (default: false)
- `include_costs=true|false` — include per-turn cost annotations (default: false)

---

## 14) Data Persistence

### 14.1 SQLite Tables (Core)

| Table | Purpose |
|---|---|
| `sessions` | Session records (key, kind, agent_id, policy, status, metadata) |
| `messages` | Session messages (role, content, provenance, tool_calls, timestamps) |
| `agents` | Agent configurations |
| `skills` | Skill definitions |
| `skill_resources` | Level 3 reference material linked to skills (§4.5.7) |
| `workflows` | Workflow definitions |
| `workflow_executions` | Execution records and step state |
| `scheduler_tasks` | Scheduled task definitions |
| `memory_extracts` | Structured memories with type, entities, decay, provenance, lifecycle status |
| `entities` | Entity records (person, org, project, etc.) with aliases, properties, embeddings |
| `memory_entity_links` | Join table linking memories to entities |
| `memory_events` | Memory audit trail (create, update, merge, access, conflict, archive events) |
| `auth_tokens` | OAuth tokens (provider, access, refresh, expiry) |
| `plugins` | Plugin configurations (type, auth ref, config, status) |
| `knowledge_sources` | External vector store registrations (backend, connection, status, scoping) |
| `embeddings` | Embedding vectors for memory, entities, and notes (§5.13) |
| `audit_log` | Gateway event audit trail |
| `config` | Application configuration key-value store |
| `files` | Uploaded file metadata (filename, mime_type, size, storage_path) |
| `transcriptions` | Audio transcription results (file ref, text, language, duration) |
| `turn_costs` | Per-turn LLM cost records (tokens, cost_usd, provider, model) |
| `provider_pricing` | Model pricing table (input/output cost per 1K tokens) |
| `budget_caps` | Budget limit configuration (period, limit, action) |
| `notification_preferences` | Per-type notification routing preferences |
| `notifications` | Notification history (type, payload, read status) |
| `messages_fts` | FTS5 virtual table for message search |
| `notes_fts` | FTS5 contentless virtual table for vault note search (content managed via manual INSERT/DELETE — no backing `notes` SQL table; notes are filesystem-based per §5.10) |
| `files_fts` | FTS5 virtual table for file metadata search |
| `agents_fts` | FTS5 virtual table for agent name/description/soul search |
| `plugins_fts` | FTS5 virtual table for plugin name/description search |
| `graph_edges` | Knowledge graph edges (source, target, edge_type, weight) |
| `web_cache` | Cached web search results and fetched page content (§17.6) |
| `browser_profiles` | Saved browser profiles with engine, domain list, timestamps (§17.3) |

### 14.2 Local Filesystem

| Path | Purpose |
|---|---|
| `data/vault/` | Knowledge base markdown notes |
| `data/embeddings/` | Embedding index storage |
| `data/auth/` | Token persistence |
| `data/backups/` | Backup archives |
| `data/uploads/` | Uploaded files (images, PDFs, audio, etc.) |
| `data/browser_profiles/` | Persistent browser profile storage (cookies, localStorage per profile) |
| `app/plugins/custom/` | User-written custom plugin modules |

### 14.3 Migrations

- Alembic for schema migrations
- Migrations run automatically on startup
- Migration scripts version-tracked in repository

### 14.4 Configuration Model

All runtime configuration is stored in the `config` SQLite table as key-value pairs. Each subsystem's config model (defined throughout this spec) maps to a namespace in the table.

```sql
CREATE TABLE config (
    key         TEXT PRIMARY KEY,        -- namespaced: "memory.extraction.trigger_interval_messages"
    value       TEXT NOT NULL,           -- JSON-encoded value
    value_type  TEXT NOT NULL,           -- "int", "float", "bool", "str", "json"
    category    TEXT NOT NULL,           -- top-level group: "memory", "web", "filesystem", etc.
    description TEXT,                    -- human-readable description for UI
    default_val TEXT,                    -- JSON-encoded default (for reset)
    requires_restart BOOLEAN DEFAULT 0,  -- does changing this require an app restart?
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    version     INTEGER NOT NULL DEFAULT 1  -- optimistic concurrency control (§20.3b)
);
```

**Configuration namespaces** (mapping spec config models to config table keys):

| Namespace | Config Model | Section | Hot-reload? |
|---|---|---|---|
| `session.*` | `SessionLifecycleConfig` | §3.7 | Yes |
| `memory.extraction.*` | `ExtractionConfig` | §5.5 | Yes |
| `memory.recall.*` | `RecallConfig` | §5.6 | Yes |
| `memory.decay.*` | `MemoryDecayConfig` | §5.8 | Yes |
| `memory.consolidation.*` | `ConsolidationConfig` | §5.8 | Yes |
| `knowledge_sources.*` | `KnowledgeSourceConfig` | §5.14 | Yes |
| `embedding.*` | `EmbeddingConfig` | §5.13 | Yes |
| `escalation.*` | `EscalationConfig` | §4.2a | Yes |
| `web.*` | `WebPolicy` | §17.5 | Yes |
| `vision.*` | `VisionConfig` | §17.4 | Yes |
| `browser.*` | `BrowserConfig` | §17.3 | Yes |
| `filesystem.*` | `FilesystemPolicy` | §16.4 | Yes |
| `ollama.*` | `OllamaConfig` | §4.6c | Yes |
| `transcription.*` | `TranscriptionConfig` | §22.2 | Yes |
| `files.*` | `FileStorageConfig` | §21.7 | Yes |
| `budget.*` | `BudgetCap` | §23.3 | Yes |
| `backup.*` | `BackupConfig` | §26.4 | Yes |
| `logging.*` | `LogConfig` | §12.4 | Yes |
| `server.host` | — | — | **No** (restart) |
| `server.port` | — | — | **No** (restart) |
| `server.gateway_token` | — | — | **No** (restart) |

**API behavior**:
- `GET /api/config` → returns all config grouped by category (values + defaults + descriptions)
- `PATCH /api/config` → accepts partial updates `{"key": "value", ...}`; validates types against `value_type`; hot-reloads affected subsystems for hot-reloadable keys; returns `requires_restart: true` for keys that need a restart
- On backup, config is exported as flat JSON (`config.json`) for portability
- On restore, config is re-imported into the table
- On first run, all defaults are seeded from the config models' default values

---

## 15) Startup Lifecycle

### 15.1 First-Run Experience

When Tequila detects an empty database (no agents, no config), it enters first-run mode:

1. **`POST /api/setup`** endpoint becomes available (blocked after setup completes).
2. Frontend shows a setup wizard instead of the chat interface.
3. Setup wizard steps:

| Step | What happens |
|---|---|
| **Welcome** | Brief intro to Tequila. User sets display name. |
| **Provider setup** | Choose provider (Anthropic / OpenAI / Ollama). Enter API key or start OAuth flow. Validate connectivity. |
| **Model selection** | Pick default model from available models (populated after provider auth). |
| **Main agent creation** | Auto-create the main agent with sensible defaults. Optional: describe desired personality → LLM-assisted soul generation (§4.1a). |
| **Done** | Redirect to chat. Setup flag written to config table. `/api/setup` returns 404 thereafter. |

**Setup data model:**

```python
class SetupRequest(BaseModel):
    user_name: str
    provider: Literal["anthropic", "openai", "ollama"]
    api_key: str | None = None           # for API key auth
    oauth_code: str | None = None        # for OAuth auth
    default_model: str                   # provider:model format
    agent_name: str = "Tequila"
    agent_persona: str | None = None     # optional free-text for soul generation
```

**CLI entry point:**

```bash
# Start Tequila (recommended)
python main.py

# Or with explicit settings
python main.py --host 127.0.0.1 --port 8000 --data-dir ./data

# Headless restore from backup
python -m app.backup.restore path/to/backup.tar.gz
```

`main.py` starts the FastAPI server with uvicorn, opens the default browser to `http://localhost:8000`, and logs startup status to console.

### 15.2 Initialization Sequence

Ordered initialization sequence on application start:

1. Load configuration
2. Open database, run pending Alembic migrations
3. Initialize auth store (load persisted tokens)
4. Initialize provider registry (validate connections)
5. Initialize gateway event router
6. Initialize session store
7. Initialize policy engine
8. Initialize vault + file watcher
9. Initialize embedding runtime + search index
10. Initialize memory manager (load extraction config, decay config, consolidation config)
11. Initialize entity store
12. Initialize memory lifecycle manager (schedule decay + consolidation jobs)
13. Initialize web access: load WebPolicy, configure search providers, initialize web cache, register core tools (web_search, web_fetch)
14. Initialize vision system: detect available vision models, load VisionConfig, register core tools (vision_describe, vision_extract_text, vision_compare, vision_analyze)
15. Initialize plugin registry (scan built-in + load saved configs from DB)
16. Activate all plugins with status=active (start adapters, register tools, attach hooks — including browser plugin if enabled)
17. Initialize scheduler manager, start pending jobs
18. Initialize notification manager
19. Run retention cleanup (audit logs, vault history, archived sessions, decayed memories, expired web cache)
20. Mount React static assets
21. Start accepting HTTP + WebSocket connections

Shutdown reverses the order: stop accepting connections → stop scheduler → deactivate all plugins → close DB.

---

## 16) Filesystem Access

The agent has full access to the user's filesystem — separate from the vault (which is the agent's internal knowledge brain). Filesystem tools are **core agent tools**, always available to every agent without a plugin.

### 16.1 Concepts

| Concept | Description |
|---|---|
| **Vault** | Agent's internal knowledge base. Notes, references, ingested documents. Managed by Tequila. |
| **Working directory** | A user-selected folder the agent treats as "home base" for the current task. Relative paths resolve here. |
| **Filesystem** | The entire machine's file system. Agent can navigate, read, write, and manage files anywhere within policy bounds. |

The vault and filesystem are **completely separate**. The vault is Tequila's managed knowledge store. The filesystem is the user's real world of files — projects, downloads, documents, code repos.

### 16.2 Working Directory

Each session can have its own working directory, set at session creation or changed mid-session:

```python
class SessionWorkingDir(BaseModel):
    path: str                              # absolute path
    set_by: Literal["user", "agent"]
    set_at: str                            # ISO timestamp
```

- **Default**: user's home directory (`~` / `%USERPROFILE%`) if no working directory is set.
- **Per-session**: each chat session tracks its own working directory — good for task-switching ("work on Q3 report" vs "work on client proposal").
- **Relative path resolution**: when an agent uses a filesystem tool with a relative path, it resolves against the session's working directory.
- **Persisted**: saved in the session record so resuming a session restores the context.

### 16.3 Filesystem Tools

All filesystem tools are **core** (not a plugin) and available to every agent:

| Tool | Safety | Description |
|---|---|---|
| `fs_list_dir` | `read_only` | List directory contents (name, type, size, modified date). Supports glob patterns. |
| `fs_read_file` | `read_only` | Read a file's contents. Text files return content; binary files return metadata + base64 (up to size limit). |
| `fs_write_file` | `side_effect` | Create or overwrite a file. Inside working dir → auto-approved. Outside → requires confirmation. |
| `fs_append_file` | `side_effect` | Append content to an existing file. Same approval rules as write. |
| `fs_copy` | `side_effect` | Copy a file or directory. |
| `fs_move` | `destructive` | Move/rename a file or directory. Always requires confirmation. |
| `fs_delete` | `destructive` | Delete a file or directory. Always requires confirmation. |
| `fs_mkdir` | `side_effect` | Create a directory (including parents). |
| `fs_search` | `read_only` | Find files by name pattern, glob, or content (grep-like). Configurable depth limit. |
| `fs_tree` | `read_only` | Return a directory tree structure (like `tree` command). Configurable depth. |
| `fs_info` | `read_only` | Get file/directory metadata: size, created, modified, permissions, MIME type. |
| `fs_get_working_dir` | `read_only` | Return the current session's working directory. |
| `fs_set_working_dir` | `side_effect` | Change the session's working directory. Validates path exists and is accessible. |

### 16.4 Path Policy

Open by default — the agent can access anything in the user's home directory tree. A **deny-list** blocks known-sensitive paths.

```python
class FilesystemPolicy(BaseModel):
    # Top-level roots the agent can access (default: user home directory)
    allowed_roots: list[str] = ["~"]

    # Hard-blocked patterns — these paths are NEVER accessible regardless of confirmation
    deny_patterns: list[str] = [
        "~/.ssh/*",
        "~/.gnupg/*",
        "~/.aws/*",
        "~/.azure/*",
        "~/.config/gcloud/*",
        "**/*.pem",
        "**/*.key",
        "**/.env",
        "**/.env.*",
        "**/secrets.*",
    ]

    # System directories — always blocked (OS-specific, resolved at startup)
    # Windows: C:\Windows\, C:\Program Files\, C:\ProgramData\
    # Linux/Mac: /usr/, /etc/, /var/, /sys/, /proc/, /boot/
    system_dirs_blocked: bool = True

    # Tequila's own data directory — blocked to prevent self-corruption
    tequila_data_blocked: bool = True

    # Max file read size (prevents agent from loading a 10 GB file into context)
    max_read_size_mb: int = 10

    # Max search depth for fs_search and fs_tree
    max_search_depth: int = 10

    # Files the agent can write without confirmation (within working dir)
    auto_approve_writes_in_working_dir: bool = True
```

#### Deny-list vs allow-list behavior:

1. Check `system_dirs_blocked` → hard block if system path.
2. Check `tequila_data_blocked` → hard block if Tequila's own `data/` or `app/` directory.
3. Check `deny_patterns` → hard block if matched (no confirmation escape hatch).
4. Check `allowed_roots` → block if path is outside all allowed roots.
5. Apply safety classification (`read_only` / `side_effect` / `destructive`) for confirmation gating.

The user can expand `allowed_roots` to include additional drives or mount points (e.g., `D:\Projects\`) and add custom `deny_patterns` in Settings → Filesystem.

### 16.5 Safety Classification Summary

| Operation | Inside working dir | Outside working dir (but in allowed_roots) | Deny-listed / system path |
|---|---|---|---|
| **Read** | Auto-approved | Auto-approved | **Blocked** |
| **List / search / tree** | Auto-approved | Auto-approved | **Blocked** |
| **Write / append / mkdir** | Auto-approved (if `auto_approve_writes_in_working_dir`) | Confirmation required | **Blocked** |
| **Copy** | Auto-approved | Confirmation required | **Blocked** |
| **Move / rename** | Confirmation required | Confirmation required | **Blocked** |
| **Delete** | Confirmation required | Confirmation required | **Blocked** |

### 16.6 Agent UX

When setting a working directory, the agent announces the change:
> *Working directory set to `C:\Users\me\Projects\Q3Report`. I can now read and write files here without confirmation.*

When an operation is blocked by policy:
> *I can't access `~/.ssh/id_rsa` — it's in a restricted path. This is a security policy to protect sensitive files.*

When confirmation is required:
> *I'd like to write `summary.docx` to `D:\SharedDrive\Reports\`. This is outside the working directory — approve?*

### 16.7 Code Execution Tool

The agent can execute code snippets in a sandboxed subprocess. This is a **core tool** (always available, not a plugin).

```python
@tool(safety="destructive")
def code_exec(
    code: str,                           # source code to execute
    language: Literal["python", "bash", "powershell"] = "python",
    timeout_s: int = 30,                 # kill after timeout
    working_dir: str | None = None,      # defaults to session working dir
) -> CodeExecResult:
    """Execute code in a sandboxed subprocess. Returns stdout, stderr, exit code."""

class CodeExecResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    execution_time_ms: int
```

**Safety**: `destructive` — always requires user confirmation. Code runs as the current OS user with full filesystem access (within `FilesystemPolicy` bounds). The `CODE_RUNNER` policy preset (§2.7) restricts sub-agents to only code execution + file tools.

---

## 17) Web Access & Vision

The agent can search the internet, read web pages, control a browser, and analyze images. Web access is organized into three layers of increasing capability, plus a unified vision system that works across all image sources.

### 17.1 Layer 1: Web Search (Core Tool)

Web search is a **core tool** — always available to every agent, no plugin required. Multiple search provider backends are supported. DuckDuckGo is the default (no API key needed, works out of the box).

**Search providers:**

| Provider | API key | Cost | Quality | Notes |
|---|---|---|---|---|
| `duckduckgo` | No | Free | Good | Default. Uses `duckduckgo-search` package. No rate limit issues. |
| `brave` | Yes | Free tier (2k/mo) | Very good | Fast, privacy-focused, good snippet quality |
| `tavily` | Yes | Free tier (1k/mo) | Excellent for AI | AI-optimized: returns clean extracted content, not just snippets |
| `google` | Yes | $5/1k queries | Excellent | Google Custom Search JSON API |
| `bing` | Yes | Free tier (1k/mo) | Very good | Microsoft Cognitive Services |
| `searxng` | No (self-hosted) | Free | Aggregated | Self-hosted meta-search engine; privacy-conscious users |

**Search tool:**

```python
@tool(safety="read_only")
def web_search(
    query: str,
    provider: str | None = None,       # override default; None = use configured default
    search_type: Literal["web", "news", "images", "academic"] = "web",
    max_results: int = 10,
    time_range: Literal["day", "week", "month", "year", "all"] = "all",
    region: str | None = None,          # e.g., "us-en", "bg-bg"
) -> list[SearchResult]:
    """Search the web. Returns structured results with title, URL, snippet."""
```

**Search type notes**: `"web"` is the default general search. `"news"` limits to recent news articles (supported by Brave, Google, Bing). `"images"` returns image results (supported by DuckDuckGo, Google, Bing). `"academic"` searches scholarly sources — supported by Tavily (which has an academic mode) and SearXNG (which can aggregate Google Scholar, Semantic Scholar, etc.). For providers that don't support a given search type, the tool falls back to `"web"` and logs a warning.

```python
class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str                        # text excerpt / rich snippet
    published_date: str | None = None
    source: str | None = None           # domain name
```

**Configuration:**

`SearchConfig` is a **convenience alias** for the search-related subset of `WebPolicy` (§17.5). All search settings are persisted under the `web.*` config namespace (§14.4). The fields below map directly:

```python
# Convenience view — actual storage is in WebPolicy (web.search_*)
class SearchConfig(BaseModel):
    default_provider: str = "duckduckgo"     # → web.search_provider
    api_keys: dict[str, str] = {}           # → web.search_api_keys
    searxng_url: str | None = None          # → web.search_searxng_url
    max_results_default: int = 10           # → web.search_max_results
    rate_limit_per_minute: int = 20         # → web.search_rate_limit_per_minute
    cache_ttl_minutes: int = 15             # → web.search_cache_ttl_minutes
```

### 17.2 Layer 2: Web Fetch (Core Tool)

The agent can read any web page. Raw HTML is useless for LLM context — the fetch tool extracts clean, structured content.

**Two fetch modes (auto-selected):**

| Mode | Engine | Use case | JS rendering? | Latency |
|---|---|---|---|---|
| **Light** | `httpx` + `trafilatura` | Articles, docs, blogs, static pages | No | ~1s |
| **Full** | Playwright headless | JS-heavy SPAs, dynamic content | Yes | ~3–5s |

```python
@tool(safety="read_only")
def web_fetch(
    url: str,
    mode: Literal["auto", "light", "full"] = "auto",
    extract_format: Literal["text", "markdown", "html"] = "markdown",
    max_length: int = 50000,            # chars — truncate beyond this
    include_links: bool = False,         # include hyperlinks in extracted text
    include_images: bool = False,        # include image alt text / descriptions
    timeout_s: int = 30,
) -> FetchResult:
    """Fetch a web page and extract its content as clean text/markdown."""

class FetchResult(BaseModel):
    url: str                             # final URL (after redirects)
    title: str
    content: str                         # extracted text/markdown
    content_length: int                  # original content length before truncation
    truncated: bool
    links: list[Link] | None = None
    fetch_mode: str                      # "light" or "full"
    status_code: int
    content_type: str
```

**Auto-mode logic:**
1. Try light fetch first (fast, low overhead).
2. If result is suspiciously short (< 500 chars extracted) or has meta-redirects / SPA indicators → retry with full (Playwright).
3. Cache mode decision per domain for future fetches.

**Content extraction pipeline:**
```
Raw HTML → trafilatura (or readability-lxml)
    → Strip nav, ads, boilerplate, keep main content
    → Optional: markdownify → clean markdown (headings, lists, code blocks, tables)
    → Truncation: smart-truncate at max_length with "[…truncated, {total} chars total]"
    → Optional: vision pass on embedded images (if include_images + vision model available)
```

### 17.3 Layer 3: Browser Automation (Plugin)

For complex web interactions — logging into sites, filling forms, navigating multi-step flows, scraping dynamic content. This is a **built-in plugin** (not core), because it requires `playwright` + browser binaries, is stateful, and carries higher safety risk.

See §8 "Plugin & Connector System" → `browser` plugin entry for the full plugin spec.

**Browser engines** (all via Playwright):

| Engine | Browser | Best for | Notes |
|---|---|---|---|
| **Chromium** | Chrome/Edge | Default — widest site compatibility | ~280 MB binary |
| **Firefox** | Gecko | Privacy-focused, different rendering behavior | ~250 MB |
| **WebKit** | Safari | Lightweight, fast for basic JS rendering | ~150 MB |

**Browser session model:**

```python
class BrowserSession(BaseModel):
    id: str
    agent_session_id: str               # tied to agent session lifecycle
    profile_id: str | None = None       # persistent profile (cookies, localStorage)
    engine: Literal["chromium", "firefox", "webkit"] = "chromium"
    current_url: str
    page_title: str
    tab_count: int = 1
    created_at: datetime
    last_action_at: datetime
    status: Literal["active", "idle", "closed"]

class BrowserConfig(BaseModel):
    engine: Literal["chromium", "firefox", "webkit"] = "chromium"
    headless: bool = True
    viewport_width: int = 1280
    viewport_height: int = 720
    user_agent: str = "Tequila/2.0"
    device_emulation: str | None = None  # "iPhone 14", "Pixel 7", "iPad Pro", etc.
    max_sessions_per_agent: int = 3
    session_timeout_minutes: int = 30    # auto-close idle sessions
    block_media: bool = True             # block images/video for speed unless screenshot
    proxy: str | None = None
```

**Browser tools** (25 tools, provided by the `browser` plugin):

| Tool | Safety | Description |
|---|---|---|
| **Navigation** | | |
| `browser_open` | `side_effect` | Open browser session, navigate to URL. Accepts optional `profile_id` and `engine`. |
| `browser_navigate` | `side_effect` | Go to a URL in the current session |
| `browser_back` | `side_effect` | Navigate back |
| `browser_forward` | `side_effect` | Navigate forward |
| `browser_close` | `side_effect` | Close the browser session |
| **Interaction (selector-based)** | | |
| `browser_click` | `side_effect` | Click element by CSS selector, text content, or coordinates |
| `browser_type` | `side_effect` | Type text into a form field (selector + text) |
| `browser_select` | `side_effect` | Select an option from a dropdown |
| `browser_scroll` | `read_only` | Scroll the page (up/down/to element) |
| **Interaction (vision-based)** | | |
| `browser_act` | `side_effect` | Vision-driven action: take screenshot → send to vision model with action description → get coordinates → execute. Works on any page without knowing the DOM. |
| **Observation** | | |
| `browser_screenshot` | `read_only` | Capture screenshot (viewport or full page; specific element; PNG or JPEG). Returns image for vision analysis + `file_id`. |
| `browser_extract` | `read_only` | Extract page content as text/markdown (same pipeline as `web_fetch`) |
| `browser_get_elements` | `read_only` | List interactive elements + auto-generated selectors (buttons, links, inputs, etc.) |
| `browser_get_a11y_tree` | `read_only` | Extract accessibility tree — compact, structured, LLM-friendly page representation (~2K tokens vs ~50K for raw HTML) |
| `browser_capture_network` | `read_only` | Intercept XHR/fetch requests for a duration; extract clean API data from JS-heavy sites |
| **Tabs** | | |
| `browser_new_tab` | `side_effect` | Open new tab (optionally with URL) |
| `browser_switch_tab` | `side_effect` | Switch to tab by index or title pattern |
| `browser_list_tabs` | `read_only` | List all open tabs (index, title, URL) |
| `browser_close_tab` | `side_effect` | Close a specific tab |
| **Output** | | |
| `browser_save_pdf` | `read_only` | Save current page as PDF document → returns `file_id` |
| `browser_download` | `side_effect` | Download a file via the browser → stored in `data/uploads/`, returns `file_id` |
| **Profiles** | | |
| `browser_profile_list` | `read_only` | List saved browser profiles |
| `browser_profile_create` | `side_effect` | Create a named profile (persists cookies, localStorage per domain) |
| `browser_profile_delete` | `destructive` | Delete profile and all stored cookies/data |
| **Advanced** | | |
| `browser_execute_js` | `destructive` | Execute JavaScript in page context. Requires `browser_js_execution: true` in policy AND user confirmation. |

**Accessibility tree extraction:**

```python
class A11yNode(BaseModel):
    role: str               # "button", "link", "textbox", "heading", etc.
    name: str               # accessible name ("Submit", "Search...", "Home")
    value: str | None       # current value (for inputs)
    description: str | None
    focused: bool
    enabled: bool
    selector: str           # auto-generated CSS selector for interaction
    children: list[A11yNode] = []
```

An entire complex page's accessibility tree fits in ~2K tokens (vs ~50K for raw HTML), making it the most context-efficient way for the agent to understand page structure.

**Persistent browser profiles:**

```python
class BrowserProfile(BaseModel):
    id: str
    name: str                            # "GitHub", "Company Intranet"
    engine: str = "chromium"
    storage_path: str                    # data/browser_profiles/{id}/
    persist_cookies: bool = True
    persist_local_storage: bool = True
    domains: list[str] = []              # auto-detected domains this profile covers
    created_at: datetime
    last_used: datetime
```

The agent logs in once → cookies saved to profile → next time it opens a page on that domain, it's already authenticated.

### 17.4 Vision System

Vision is a **cross-cutting capability** — it works on images from any source, not just file uploads. The vision system unifies image understanding across the entire application.

#### Image Sources

| Source | How images arrive | Example |
|---|---|---|
| **File upload** | User uploads image via chat or `POST /api/files/upload` | "What's in this photo?" |
| **Browser screenshot** | `browser_screenshot` or `browser_act` tool | Interpreting web page content |
| **Generated chart** | `chart_render` tool output from documents plugin | "Describe this chart" |
| **Document images** | Images extracted from PPTX, DOCX, PDF during `_open` tools | "What's in slide 3's diagram?" |
| **Web image** | Image URL fetched via `web_fetch` with `include_images=True` | Inline image descriptions |
| **Clipboard / paste** | User pastes image into chat (frontend captures) | Quick screenshare analysis |
| **Screen capture** | Future: system screenshot tool | Desktop automation |

#### Vision Pipeline

```
Image arrives (from any source)
    │
    ▼
1. Metadata extraction
    → dimensions, format, MIME type, file size
    → EXIF data (if JPEG: camera, GPS, date taken)
    │
    ▼
2. Provider capability check
    → model_capabilities.vision == True?
    │
    ├── YES → 3a. Native vision injection
    │         Image sent as content block (base64 data-URI or URL)
    │         Provider adapter formats per-provider:
    │           Anthropic: { type: "image", source: { type: "base64", ... } }
    │           OpenAI: { type: "image_url", image_url: { url: "data:image/..." } }
    │
    └── NO → 3b. Fallback description
              If vision model available (separate from chat model):
                → Route image to vision model for description
                → Inject description as text: "[Image: {description}]"
              If no vision model:
                → Inject: "[Image uploaded: {filename}, {width}×{height}]"
```

#### Vision Tools

Vision-specific tools available to every agent (core tools):

| Tool | Safety | Description |
|---|---|---|
| `vision_describe` | `read_only` | Describe an image in detail (pass `file_id` or URL). Returns natural language description. |
| `vision_extract_text` | `read_only` | OCR: extract text from an image (screenshots, photos of documents, whiteboards). |
| `vision_compare` | `read_only` | Compare two images and describe differences. |
| `vision_analyze` | `read_only` | Structured analysis: extract specific information from an image based on a prompt (e.g., "What products are shown and what are their prices?"). |

```python
@tool(safety="read_only")
def vision_describe(
    image: str,                          # file_id or URL
    detail_level: Literal["brief", "detailed"] = "detailed",
    focus: str | None = None,            # optional focus area: "the chart", "the text", "the people"
) -> str:
    """Describe an image using the vision model."""

@tool(safety="read_only")
def vision_extract_text(
    image: str,                          # file_id or URL
    language_hint: str | None = None,
) -> str:
    """Extract text from an image (OCR via vision model)."""

@tool(safety="read_only")
def vision_compare(
    image_a: str,                        # file_id or URL
    image_b: str,                        # file_id or URL
    comparison_focus: str | None = None, # what to compare: "layout", "content", "colors"
) -> str:
    """Compare two images and describe the differences."""

@tool(safety="read_only")
def vision_analyze(
    image: str,                          # file_id or URL
    prompt: str,                         # what to extract/analyze
) -> str:
    """Analyze an image with a specific prompt. Returns structured findings."""
```

#### Vision Configuration

```python
class VisionConfig(BaseModel):
    enabled: bool = True
    preferred_model: str | None = None   # override: use this model for vision tasks
                                         # None = use the agent's default model (if vision-capable)
    fallback_model: str | None = None    # if default model lacks vision, use this one
    max_image_size_mb: int = 10
    max_image_dimension: int = 4096      # resize larger images before sending
    auto_describe_uploads: bool = False  # auto-generate descriptions for uploaded images
    ocr_enabled: bool = True
```

### 17.5 Web Policy

All web access is governed by a unified policy:

```python
class WebPolicy(BaseModel):
    # --- Search ---
    search_enabled: bool = True
    search_provider: str = "duckduckgo"
    search_api_keys: dict[str, str] = {}     # provider → API key (e.g., {"brave": "...", "tavily": "..."})
    search_searxng_url: str | None = None    # for self-hosted SearXNG
    search_max_results: int = 10
    search_rate_limit_per_minute: int = 20

    # --- Fetch ---
    fetch_enabled: bool = True
    fetch_max_size_mb: int = 5               # max response body before abort
    fetch_max_content_chars: int = 50000     # max extracted text length
    fetch_timeout_s: int = 30
    fetch_rate_limit_per_minute: int = 30
    respect_robots_txt: bool = True

    # --- Browser ---
    browser_enabled: bool = False             # off by default (opt-in via browser plugin)
    browser_max_sessions: int = 3
    browser_session_timeout_min: int = 30
    browser_js_execution: bool = False        # browser_execute_js requires this + confirmation

    # --- URL policy ---
    allowed_domains: list[str] = []           # empty = all allowed
    blocked_domains: list[str] = [            # always blocked
        "localhost", "127.0.0.1", "0.0.0.0",
        "*.local", "*.internal",
        "169.254.*",                           # link-local
        "10.*", "172.16.*", "192.168.*",       # private network ranges (SSRF prevention)
    ]
    blocked_url_schemes: list[str] = [
        "file", "ftp", "data", "javascript",
    ]

    # --- Content ---
    strip_tracking_params: bool = True        # remove utm_*, fbclid, etc. from URLs

    # --- Caching ---
    cache_enabled: bool = True
    cache_ttl_minutes: int = 60              # fetched page cache duration
    search_cache_ttl_minutes: int = 15       # search result cache duration
```

**Key safety points:**
- **Private network blocking**: agent cannot access localhost, internal IPs, or private ranges (prevents SSRF attacks)
- **URL scheme blocking**: no `file://`, `ftp://`, `data:`, `javascript:` URLs
- **Rate limiting**: per-minute caps on search and fetch to prevent abuse and API cost overruns
- **robots.txt**: respected by default (configurable for personal use cases)
- **Browser opt-in**: disabled by default — most agents only need search + fetch
- **JS execution gated**: `browser_execute_js` requires policy flag AND per-call user confirmation

### 17.6 Web Caching

Web operations are slow and often repetitive. Caching saves time and API costs:

```sql
CREATE TABLE web_cache (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_type   TEXT NOT NULL,           -- "search" or "fetch"
    cache_key    TEXT NOT NULL UNIQUE,    -- hash of (query+params) or normalized URL
    url          TEXT,                    -- for fetch cache
    query        TEXT,                    -- for search cache
    content      TEXT NOT NULL,           -- cached response (JSON)
    content_size INTEGER NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at   TEXT NOT NULL
);
CREATE INDEX idx_web_cache_key ON web_cache(cache_key);
CREATE INDEX idx_web_cache_expires ON web_cache(expires_at);
```

- Search results cached for 15 minutes (configurable).
- Fetched pages cached for 60 minutes (configurable).
- Agent can force fresh fetch with `fresh: true` parameter.
- Expired entries cleaned up during retention cleanup (§15 startup lifecycle).

### 17.7 Dependencies

| Dependency | Purpose | Required? |
|---|---|---|
| `httpx` | HTTP client for light fetches and search API calls | Yes (already used) |
| `trafilatura` | Content extraction from HTML (main article, strip boilerplate) | Yes |
| `duckduckgo-search` | Default search provider (no API key needed) | Yes |
| `html2text` or `markdownify` | HTML → markdown conversion | Yes |
| `playwright` | Headless browser for full fetch + browser automation plugin | Optional (install when browser plugin activated) |

---

## 18) Build Sequencing (Recommended Implementation Order)

### Phase 1: Foundation
1. FastAPI app skeleton + lifespan + config + SQLite + Alembic
2. Gateway event router (in-process async, Pydantic event models)
3. Configuration table + config model (§14.4) + structured logging (§12.4)
4. Session store + session CRUD API + session lifecycle (§3.7: idle detection, auto-summarize, archive states)
5. WebSocket endpoint + wire protocol + WebChat adapter + WS reconnection & state recovery (§2.5a: seq replay, event buffer, heartbeat)
5a. React shell (Vite setup, WS connection, basic chat UI) + theming (§9.3: dark/light/system) + keyboard shortcuts (§9.4)
5b. First-run setup wizard (§15.1): provider auth, model selection, main agent creation
5c. Health & status endpoints (§13.3)
5d. Session title auto-generation (§3.2: title, summary, message_count) + session search & filtering (§9.5)

### Phase 2: Agent Core
6. SoulConfig model (§4.1a) + soul generation + soul editor UI
7. Agent config model + CRUD API + escalation protocol (§4.2a: triggers, context transfer, EscalationConfig)
8. Provider abstraction layer: LLMProvider ABC, ProviderStreamEvent, ToolDef, ModelCapabilities registry (§4.6–4.6b) + OllamaProvider adapter (§4.6c: model discovery, tiktoken fallback, OllamaConfig)
9. Prompt assembly pipeline (§4.3a): 9-step assembly (steps 1–3, 3a, 4–8), budget allocation, priority trimming
10. Turn loop: prompt assembly → provider streaming → tool-call parsing → tool execution → response persistence (§4.3 + §4.6a)
10a. Message model (§3.4): full Message/ContentBlock/ToolCallRecord schema + branching & regeneration (§3.5: parent_id, active flag, edit-and-resubmit)
10b. Message feedback (§3.6): thumbs up/down, confidence effects on extraction
11. Tool framework: tool registry, safety classification, execution handlers, parallel tool-call support
12. Filesystem tools: fs_list_dir, fs_read_file, fs_write_file, fs_search, working directory, path policy + code execution tool (code_exec §16.7: sandboxed subprocess, destructive safety)
13. Web search tool: web_search with DuckDuckGo default, SearchConfig, search provider registry
14. Web fetch tool: web_fetch with httpx + trafilatura (light mode), content extraction pipeline, web_cache table
15. Vision core: vision pipeline (§17.4), vision tools (vision_describe, vision_extract_text, vision_compare, vision_analyze), VisionConfig
16. Context window management (§4.7): ContextBudget, compression, token counting cache
17. Session policy enforcement in gateway
18. Approval flow: gateway events → WS → UI → gateway → agent

### Phase 3: Multi-Agent
19. Session tools: `sessions_list`, `sessions_history`, `sessions_send`, `sessions_spawn`
20. Sub-agent spawning with policy scoping
21. Workflow runtime: pipeline + parallel modes
22. Workflow API + UI

### Phase 4: Memory & Knowledge
23. Vault storage + watcher + note CRUD + wiki-link parser
24. Embedding engine (§5.13): EmbeddingProvider ABC, SQLiteEmbeddingStore, sentence-transformers local default, reindex triggers
25. Memory data model: structured types (identity, preference, fact, experience, task, relationship, skill), provenance, decay fields
26. Entity model: entity store, NER extraction, alias resolution, entity-memory linking
27. Extraction pipeline: 6-step (classify → extract → dedup → conflict → entity-link → graph-edge)
28. Recall pipeline: 3-stage (session init pre-load → per-turn foreground → background pre-fetch + entity graph traversal)
28a. Knowledge Source Registry (§5.14): KnowledgeSourceAdapter ABC, adapters (Chroma, pgvector, FAISS, HTTP), KnowledgeSourceRegistry, recall pipeline federation (step 4a–4b), kb_search + kb_list_sources agent tools, knowledge source API endpoints, health monitoring
29. Agent memory tools: memory_save, memory_update, memory_forget, memory_search, memory_list, memory_pin, entity_create, entity_merge, entity_update
30. Memory lifecycle manager: decay calculation, consolidation (merge, summarize, archive, orphan report)
31. Memory audit trail: memory_events table, history API, UI timeline
32. Knowledge graph: edge store, graph API, entity-centric edges, semantic similarity edge builder
33. Knowledge graph UI: force-directed visualization, filters, ego graph, entity nodes, live updates

### Phase 5: Plugins & Integrations
34. Plugin base class (PluginBase ABC §8.7) + registry + CRUD API + health check loop + plugin dependency management (§8.9: PluginDependencies, install flow, venv isolation)
35. Auth flows: OpenAI OAuth, Anthropic OAuth, API key (LLM providers)
36. Built-in connector plugin: `telegram` (channel + tools)
37. Built-in connector plugin: `gmail` (channel + tools)
38. Built-in connector plugin: `smtp_imap` (channel + tools)
39. Built-in connector plugin: `google_calendar` (tools + optional trigger)
40. Built-in connector plugin: `webhooks` (inbound channel)
41. Built-in tool plugin: `documents` (PowerPoint, Word, Excel, PDF full suite, CSV/TSV, charts, data analysis)
    - PDF reading: PyMuPDF + pymupdf4llm (pdf_open, pdf_read_pages, pdf_extract_tables, pdf_extract_images, pdf_page_to_image, pdf_search)
    - PDF manipulation: pypdf (pdf_merge, pdf_split, pdf_edit)
    - PDF creation: fpdf2 (pdf_create, pdf_from_markdown) — already available
    - CSV/TSV: csv_open, csv_query (DuckDB), csv_to_xlsx
    - Data analysis: data_analyze, data_to_chart
    - Smart context injection routing (§21.4): MIME-type → document tool auto-preview on upload
42. Built-in tool plugin: `browser` (Playwright-based browser automation — 25 tools, profiles, vision-based interaction). Includes full-mode web_fetch via Playwright.
43. Web access polish: additional search providers (Brave, Tavily, Google, Bing, SearXNG), WebPolicy UI, web cache admin
44. MCP plugin type (external tool servers)
45. Pipeline hook plugin type
46. Custom plugin auto-discovery
47. Scheduler + cron sessions

### Phase 6: Polish
48. Skills system + auto-attach
49. Agent soul editor + LLM-assisted setup
50. Notifications + notification preference model + proactive session injection (§24.5)
51. Audit log + audit sink plugins + retention
52. Budget & cost tracking
53. App lock
54. Backup & restore
55. Session transcript export (§13.4): markdown, JSON, PDF formats
56. File download & export flow (§21.6): file cards, inline media rendering (§9.2a), local-app actions (open file, reveal in Explorer), session files panel (§9.2b), preview endpoint, quick actions
57. Full React UI build-out (all settings, plugin management, workflow visualization, memory explorer, entity explorer, web/browser/vision settings)
58. File cleanup & retention (§21.7): orphan detection, storage quota, soft-delete, cleanup task
59. Windows packaging (§29): PyInstaller freeze, frozen-mode path resolution, plugin venv isolation, Inno Setup installer

### Phase 7: Future Additions
60. Built-in tool plugin: `image_generation` (DALL-E / Stable Diffusion — image_generate, image_edit, image_variations)
61. Additional connector plugins: Slack, Discord, WhatsApp, Signal
62. Auto-update mechanism (§29.5): version check on startup, update notification, in-place patching

Gate each phase: the previous phase must be demonstrably working before proceeding.

---

## 19) Error Handling & Resilience

### 19.1 Retry Policy

```python
class RetryPolicy(BaseModel):
    max_retries: int = 3
    base_delay_s: float = 1.0          # exponential back-off base
    max_delay_s: float = 30.0
    retryable_errors: list[str] = [    # error code prefixes (matched against §19.5 classification codes)
        "provider_rate_limit",         # e.g., provider_rate_limit_anthropic
        "provider_overloaded",         # e.g., provider_overloaded_openai
        "provider_timeout",            # e.g., provider_timeout_ollama
        "network_error",               # e.g., network_error_connection_refused
    ]
```

Retryable error strings are **prefix-matched** against the structured error codes from §19.5 (`{domain}_{category}_{detail}`). For example, `"provider_rate_limit"` matches `"provider_rate_limit_anthropic"`, `"provider_rate_limit_openai"`, etc. Each LLM provider call and external HTTP request is wrapped in a retry loop governed by `RetryPolicy`. Non-retryable errors (auth failures, validation errors, 4xx) fail immediately.

### 19.2 Circuit Breaker

Per-provider circuit breaker prevents cascading failures:

| State | Behaviour |
|---|---|
| **closed** | Normal operation; failures increment counter |
| **open** | All calls fail-fast for `cooldown_s` (default 60) |
| **half-open** | One probe call allowed; success → closed, failure → open |

Transition thresholds: 5 consecutive failures → open. Tracked per `(provider_id, model)` pair.

### 19.3 Graceful Degradation

When a provider circuit opens:
1. Gateway emits `provider.unavailable` event.
2. Agent runtime checks for a **fallback provider** in `AgentConfig.fallback_provider_id`.
3. If fallback exists and its circuit is closed → reroute silently, log the swap.
4. If no fallback → return a user-visible error with estimated retry time.

### 19.4 Partial-State Cleanup

If a turn fails mid-execution (tool call succeeded but LLM response failed):
- Completed tool results are persisted to the session as `role: "tool_result"`.
- An `agent.run.error` event is emitted with `partial: true` flag.
- The next turn auto-injects a system note: *"Previous turn failed after tool execution. Tool results are available above."*

### 19.5 Error Classification

All errors are tagged with a structured code:

```
{domain}_{category}_{detail}
```

Examples: `provider_rate_limit_anthropic`, `tool_execution_timeout`, `gateway_routing_no_session`, `plugin_auth_token_expired`.

The frontend maps error codes to user-friendly messages via a static lookup table.

---

## 20) Concurrency Model

Tequila is a single-process, single-event-loop application backed by SQLite. The concurrency strategy is designed to eliminate race conditions, guarantee idempotency for external inputs, and keep write lock hold-times minimal — all without introducing an external message broker or a separate database engine.

### 20.1 SQLite Configuration

```python
# Applied once at startup via open_db()
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
```

WAL mode allows concurrent reads while a single write proceeds. All write operations are serialized through a single global `asyncio.Lock` (one per database path) to prevent `SQLITE_BUSY` under async concurrency.

**Rules:**
- The lock is **never** held across `await` boundaries that involve network I/O (LLM calls, HTTP requests, etc.). Only the actual SQL write executes inside the lock.
- Reads (`SELECT`) do **not** acquire the lock — WAL allows unlimited concurrent readers.

### 20.2 Write Transaction Helper

All database mutations go through a `write_transaction` helper that enforces the lock → BEGIN IMMEDIATE → execute → COMMIT/ROLLBACK pattern:

```python
async def write_transaction(
    db: aiosqlite.Connection,
    fn: Callable[[aiosqlite.Connection], Awaitable[T]],
) -> T:
    """Execute *fn* inside a serialized write transaction.

    Acquires the global write lock, opens a BEGIN IMMEDIATE transaction,
    calls *fn(db)*, and commits.  On any exception the transaction is
    rolled back and the exception re-raised.
    """
    async with _write_lock:
        await db.execute("BEGIN IMMEDIATE")
        try:
            result = await fn(db)
            await db.commit()
            return result
        except BaseException:
            await db.rollback()
            raise
```

**Guidelines for callers:**
- Keep `fn` as short as possible — only SQL statements, no network I/O.
- For read-modify-write cycles, prefer the atomic patterns in §20.3 before reaching for `write_transaction`.
- `write_transaction` is reentrant-safe: the lock is per-path, not per-connection.

### 20.3 Atomic Updates & State Transitions

#### 20.3a Atomic Counters

For simple read-modify-write on numeric fields, use atomic SQL instead of read → compute → write:

```sql
-- ✅ Correct: single atomic statement
UPDATE sessions SET message_count = message_count + 1 WHERE session_id = ?;

-- ❌ Wrong: race-prone read-then-write
count = SELECT message_count FROM sessions WHERE session_id = ?;
UPDATE sessions SET message_count = ? WHERE session_id = ?;  -- stale
```

Applies to: `message_count`, `access_count`, budget counters, retry counts.

#### 20.3b Optimistic Concurrency Control (Version Columns)

For complex read-modify-write on objects (where the entire row is read, modified in Python, and written back), tables carry an integer `version` column. Writers must include `AND version = :expected_version` in their `UPDATE ... WHERE` clause and increment `version` on success:

```sql
UPDATE sessions
SET    status = :new_status,
       summary = :new_summary,
       version = version + 1,
       updated_at = datetime('now')
WHERE  session_id = :id AND version = :expected_version;
```

If `changes() == 0`, the row was modified by a concurrent writer. The caller must:
1. Re-read the row.
2. Re-apply the mutation (merge if possible).
3. Retry (max 3 attempts).
4. If still conflicting, log `concurrency.version_conflict` and raise `DatabaseError`.

**Tables with version columns:**

| Table | Rationale |
|---|---|
| `sessions` | Status transitions, summary updates, metadata edits |
| `config` | Hot-reload writes from API + background subsystems |
| `agents` | Soul/config edits from UI + agent self-modification |
| `memory_extracts` | Decay updates, access-count bumps, consolidation merges |

Tables that are **append-only** (e.g., `messages`, `audit_log`, `files`) or **idempotent-by-key** (e.g., `embeddings`) do **not** need version columns.

#### 20.3c State Transitions

Status changes (e.g., session `active → idle → archived`) must use conditional `WHERE` clauses that assert the expected current state:

```sql
UPDATE sessions
SET    status = 'idle', version = version + 1, updated_at = datetime('now')
WHERE  session_id = ? AND status = 'active' AND version = ?;
```

This prevents double-transitions (e.g., two concurrent idle-checks both archiving the same session).

### 20.4 Idempotency

#### 20.4a External Inputs

Every external message source supplies (or is assigned) a unique ID that serves as a deduplication key:

| Source | Dedup key | Storage |
|---|---|---|
| WebSocket frame | `frame_id` (client-supplied UUID) | Check before inserting into `messages` |
| Telegram message | `telegram_message_id` | Stored in `messages.metadata` |
| Email | `Message-ID` header | Stored in `messages.metadata` |
| Webhook | `X-Idempotency-Key` header or `webhook_event_id` | Stored in `messages.metadata` |
| Cron trigger | `cron_run_{job_id}_{scheduled_ts}` | Checked against `audit_log` before firing |

**On duplicate**: the gateway returns the original response (or acknowledges silently) without re-processing.

#### 20.4b Internal Turns

Within a single session, turn execution is already serialized by the turn queue (§20.6). No additional internal idempotency mechanism is required — the queue guarantees at-most-once execution per enqueued turn.

### 20.5 Background Task Safety

Background tasks (memory decay, consolidation, session idle-checks, embedding indexing) run on periodic timers and may read stale data by the time they write.

**Pattern — timestamp-gated writes:**

```sql
-- Memory decay: only update if nobody else touched the row since we read it
UPDATE memory_extracts
SET    decay_score = :new_score,
       version = version + 1,
       last_accessed = datetime('now')
WHERE  id = :id AND updated_at = :read_updated_at AND version = :expected_version;
```

If `changes() == 0`, the background task silently skips the row (another writer won the race). This is safe because all background mutations are **convergent** — they will be retried on the next timer tick.

**Bulk operations** (e.g., batch decay recalculation across hundreds of memories):
- Process in **chunks of 50 rows** per transaction to keep lock hold-times short.
- Each chunk acquires and releases `write_transaction` independently.
- Interleaving with interactive writes is acceptable — interactive writes always have higher effective priority because they are triggered by user input.

### 20.6 Turn Queuing

Each session maintains an async turn queue (depth = 1). While a turn is in-flight:
- Inbound user messages are queued (FIFO, max 10).
- If the queue is full, the gateway returns `status: "busy"` to the sender.
- Tool-generated follow-up turns are inserted at the head of the queue.

### 20.7 Concurrent Sub-Agents

When an agent spawns sub-agents in a parallel workflow:
- Each sub-agent session runs its turn loop independently.
- The parent session enters a `waiting_for_children` state — it does not consume its turn queue.
- Results are collected via `sessions_send` back to the parent.
- Maximum concurrent sub-agent turns: configurable, default 3.

### 20.8 Scheduler & Cron Isolation

Scheduled jobs (cron sessions) are not allowed while an interactive session is actively in a turn:
- The scheduler checks for active turns before firing.
- If a turn is in-flight, the cron job is deferred by up to 60 s, then retried.
- If still blocked, the job is skipped and logged with `scheduler.skipped` event.

### 20.9 Gateway Event Ordering

Events are dispatched within a session in strict order. Cross-session events (e.g., `sessions_send`) are delivered in send-order but processed in the recipient's turn queue, so ordering is eventual.

---

## 21) File Uploads & Vision

### 21.1 Upload Endpoint

```
POST /api/files/upload
Content-Type: multipart/form-data

Response: { "file_id": "...", "filename": "...", "mime_type": "...", "size_bytes": int }
```

### 21.2 Storage

Uploaded files are stored under `data/uploads/{YYYY-MM}/{file_id}_{sanitized_name}`. Metadata is persisted in a `files` table:

```sql
CREATE TABLE files (
    id          TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    mime_type   TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    storage_path TEXT NOT NULL,
    session_id  TEXT,              -- optional association
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 21.3 Size & Type Limits

| Constraint | Default | Configurable |
|---|---|---|
| Max file size | 20 MB | `files.max_size_mb` |
| Allowed MIME types | `image/*`, `application/pdf`, `text/*`, `text/csv`, `audio/*`, `application/vnd.openxmlformats-officedocument.*` (XLSX, DOCX, PPTX), `application/vnd.ms-excel`, `application/vnd.ms-powerpoint`, `application/msword` | `files.allowed_types` |
| Max files per message | 5 | `files.max_per_message` |

### 21.4 Context Injection

When a message includes `file_ids`, the turn loop resolves each file from the `files` table and routes it based on MIME type. The goal is to inject **structured, LLM-friendly content** into context — not raw bytes or dumped text.

**Routing table:**

| MIME Type | Route | What gets injected |
|---|---|---|
| `image/*` | Vision pipeline (§17.4) | Vision-capable model → native image content block. Non-vision model → generated description via fallback vision model. No vision model → metadata placeholder. |
| `application/pdf` | `pdf_open` + `pdf_read_pages` | Structure summary (page count, metadata, TOC) + markdown-extracted content of first N pages (configurable, default 10). Scanned pages flagged — agent can use `pdf_page_to_image` + vision for those. |
| `text/csv`, `text/tab-separated-values` | `csv_open` | Column names, row count, inferred types, sample rows (first 20). Agent can follow up with `csv_query` for specific analysis. |
| `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` (XLSX) | `xlsx_open` | Sheet names, headers, row count per sheet, sample data from first sheet. |
| `application/vnd.openxmlformats-officedocument.wordprocessingml.document` (DOCX) | `docx_open` | Structured content: headings, paragraphs, tables, image placeholders. |
| `application/vnd.openxmlformats-officedocument.presentationml.presentation` (PPTX) | `pptx_open` | Slide count, per-slide text/notes/layout, shape descriptions, image placeholders. |
| `application/vnd.ms-excel` (XLS), `application/msword` (DOC), `application/vnd.ms-powerpoint` (PPT) | Legacy Office fallback | Attempt conversion via the same tool (python-pptx / python-docx / openpyxl only support OOXML). If the library rejects the file, inject metadata placeholder and advise the user to save as XLSX/DOCX/PPTX. |
| `text/plain`, `text/markdown`, `text/html`, `application/json`, `application/xml` | Direct text injection | Raw content injected as a system-context block (truncated at `max_inject_chars`, default 50,000). |
| `audio/*` | Transcription pipeline (§22) | Async transcription via Whisper → transcript injected as text. |

**Injection flow:**

```
File uploaded with message
    │
    ▼
1. Resolve file metadata from `files` table
2. Check MIME type against routing table
3. Route to appropriate handler:
    │
    ├─ image/* → vision pipeline (native content block or description)
    ├─ application/pdf → pdf_open() → pdf_read_pages(pages="1-10", format="markdown")
    ├─ text/csv → csv_open() → inject column info + sample rows
    ├─ xlsx → xlsx_open() → inject sheet structure + sample data
    ├─ docx → docx_open() → inject structured content
    ├─ pptx → pptx_open() → inject slide summaries
    ├─ text/* → read content → inject raw text (truncated)
    └─ audio/* → transcription queue → inject transcript
4. Injected content wrapped with file context header:
    "[File: {filename} ({mime_type}, {size})]"
    {extracted content}
    "[End of file: {filename}]"
5. If extraction fails, inject metadata-only placeholder:
    "[File: {filename} ({mime_type}, {size}) — content extraction failed, use document tools to inspect manually]"
```

**Key behaviors:**
- **Auto-preview, not auto-dump**: structured documents get a smart preview (structure + sample), not their entire contents crammed into context.
- **Agent can dig deeper**: the initial injection gives enough context to understand what the file is. The agent can then call `pdf_read_pages(pages="15-20")`, `csv_query("SELECT ... WHERE ...")`, or `xlsx_open(sheet="Sheet2")` for targeted access.
- **Truncation**: text injection capped at 50,000 chars with `[...truncated, {total} chars total]` marker. PDF markdown extraction defaults to first 10 pages.
- **Failure graceful**: if a document tool fails (corrupt file, unsupported format), a metadata placeholder is injected and the agent is told to use manual tools.

### 21.5 Vision Support

The full vision system is defined in §17.4. In the context of file uploads:

- Vision-capable models receive images natively via provider-specific content blocks.
- The provider adapter checks `model_capabilities.vision` and formats accordingly:
  - Anthropic: `{ type: "image", source: { type: "base64", ... } }`
  - OpenAI: `{ type: "image_url", image_url: { url: "data:image/..." } }`
- Non-vision models receive a generated description (via vision fallback model) or metadata placeholder.
- OCR via `vision_extract_text` tool works on any uploaded image (photos of documents, screenshots, whiteboards).
- Uploaded images are stored as files (§21.2) and can be referenced by `file_id` in any vision tool.

### 21.6 File Download & Export Flow

When the agent creates a file (document, chart, PDF, image, spreadsheet), the user needs a clear path to access it.

**Download endpoint:**

```
GET /api/files/{file_id}/download
→ Content-Disposition: attachment; filename="report.pdf"
→ Content-Type: application/pdf
→ Binary file body
```

**Chat integration**: When a tool returns a `file_id`, the agent's response includes a **file card** in the message:

```python
class FileCard(BaseModel):
    file_id: str
    filename: str
    mime_type: str
    size_bytes: int
    download_url: str                    # /api/files/{id}/download
    preview_available: bool              # true for images, PDFs
    preview_url: str | None = None       # /api/files/{id}/preview (thumbnail or first page)
```

The frontend renders file cards as:
- **Images**: inline thumbnail (max 300px width). Click opens **image lightbox** (§9.2a).
- **Documents** (PDF, DOCX, PPTX, XLSX): file type icon + filename + human-readable size + action buttons.
- **PDFs**: first-page thumbnail (from preview endpoint) + filename + size. Click opens **PDF viewer** (§9.2a).
- **Charts**: inline preview (the chart image). Click opens image lightbox.
- **Code / text files**: syntax-highlighted preview (first 30 lines, collapsible to expand). Language detected from extension or MIME type.
- **Audio**: inline player widget (play/pause, seek bar, duration).
- **Other**: generic file icon + filename + size + action buttons.

**Preview endpoint** (for images and PDFs):

```
GET /api/files/{file_id}/preview
→ Returns: thumbnail image (max 400px) for images, first-page render for PDFs
```

**Quick actions** in the file card (displayed as icon buttons, with a `⋮` overflow menu for less common actions):

| Action | Icon | Behavior | Availability |
|---|---|---|---|
| **Download** | ↓ | Triggers browser download via `/api/files/{id}/download` | All files |
| **Open file** | ↗ | Opens the file with the OS default application. Backend calls `os.startfile(path)` (Windows) / `xdg-open` (Linux) / `open` (macOS). | All files |
| **Reveal in Explorer** | 📂 | Opens the containing folder with the file selected. Backend calls `subprocess.Popen(['explorer', '/select,', path])` (Windows) / equivalent on other OS. | All files |
| **View** | 👁 | Opens inline viewer: image lightbox (§9.2a) for images, PDF viewer for PDFs, syntax-highlighted view for code/text. | Images, PDFs, text/code |
| **Copy path** | 📋 | Copies the absolute file path to clipboard. | All files (overflow menu) |
| **Pin** | 📌 | Marks file as pinned (exempt from cleanup — §21.7). Toggle. | All files (overflow menu) |

**Local-app file action endpoints:**

```
POST /api/files/{file_id}/open
→ Opens file with OS default application
→ Response: { "status": "ok" } or { "error": "file not found" }

POST /api/files/{file_id}/reveal
→ Opens containing folder with file selected in file manager
→ Response: { "status": "ok" } or { "error": "file not found" }
```

These endpoints resolve `storage_path` from the `files` table and execute OS-level commands. They only work when the app is running locally (which is always true for Tequila — local-first architecture). The endpoints validate that the file exists on disk before executing.

**Context menu on right-click**: File cards also support a right-click context menu exposing all quick actions plus "Copy download URL" (for local network sharing if configured).

### 21.7 File Cleanup & Retention

Uploaded files consume local disk space and must be managed over time. This section defines the retention policy, orphan detection, and storage quota system.

**Retention policy**:

| File Category | Default Retention | Rationale |
|---|---|---|
| **Session-linked** (has `session_id`) | Retained while session exists; deleted when session is permanently deleted | Files are part of session context |
| **Orphaned** (no `session_id`, not referenced by any message `file_ids`) | 30 days after creation | Uploads that were never attached to a conversation |
| **Pinned** (`pinned = true`) | Indefinite | User explicitly marked for permanent retention |
| **Transcription source audio** | 7 days after transcription completes | Transcript is the value; audio is large and redundant |

**Orphan detection**:
- A file is **orphaned** if:
  1. `session_id IS NULL`, AND
  2. Its `file_id` does not appear in any message's `file_ids` array, AND
  3. It is not `pinned`
- Orphan scan runs daily (configurable interval).
- Orphaned files past their retention window are soft-deleted first (marked `deleted_at`), then permanently removed after an additional 7-day grace period.

**Storage quota**:

```python
class FileStorageConfig(BaseModel):
    max_storage_mb: int = 5000                # total upload storage cap (default 5 GB)
    orphan_retention_days: int = 30           # days before orphaned files are soft-deleted
    audio_retention_days: int = 7             # days to keep transcription source audio
    cleanup_interval_hours: int = 24          # how often the cleanup task runs
    soft_delete_grace_days: int = 7           # days between soft-delete and permanent removal
    warn_at_percent: int = 80                 # emit warning notification at this % of quota
```

- When usage exceeds `warn_at_percent`, a `notification.push` event is emitted with type `storage_warning`.
- When usage reaches 100%, new uploads are rejected with HTTP 507 (Insufficient Storage) until space is freed.

**Cleanup task flow**:
```
1. Scan files table for orphans past retention window → mark deleted_at = now()
2. Scan files table for rows with deleted_at older than grace period → delete from disk + remove row
3. Scan transcription source audio past audio_retention_days → mark deleted_at
4. Calculate total storage usage → update /api/status storage stats
5. If usage > warn_at_percent → emit storage_warning notification
```

**Storage stats** (exposed in `GET /api/status`):
```json
{
  "file_storage": {
    "total_files": 342,
    "total_size_mb": 1847,
    "quota_mb": 5000,
    "usage_percent": 36.9,
    "orphaned_files": 12,
    "orphaned_size_mb": 45,
    "pinned_files": 23
  }
}
```

**File table additions** (extending §21.2 schema):
```sql
ALTER TABLE files ADD COLUMN pinned      INTEGER NOT NULL DEFAULT 0;
ALTER TABLE files ADD COLUMN deleted_at   TEXT;      -- soft-delete timestamp
```

**API**:
```
POST /api/files/{id}/pin                — pin file for permanent retention
DELETE /api/files/{id}/pin              — unpin file
POST /api/files/cleanup                 — trigger manual cleanup run
GET /api/files/stats                    — storage statistics (same as /api/status.file_storage)
```

---

## 22) Audio & Transcription Pipeline

### 22.1 Transcription Flow

```
Audio file upload → /api/files/upload
                  → transcription queue (async)
                  → Whisper (local or API)
                  → transcript stored in `transcriptions` table
                  → gateway event: transcription.complete
```

### 22.2 Whisper Integration

```python
class TranscriptionConfig(BaseModel):
    engine: Literal["local", "openai_api"] = "local"
    model_size: str = "base"              # local Whisper model size
    language: str | None = None           # auto-detect if None
    openai_api_key: str | None = None     # for API mode
```

- **Local mode**: uses `faster-whisper` or `openai-whisper` package. Runs in a thread pool to avoid blocking the event loop.
- **API mode**: sends audio to OpenAI's `/v1/audio/transcriptions` endpoint.

**Audio limits**: The general file size limit (§21.3, default 20 MB) applies. For longer recordings, consider:
- Local Whisper: no duration limit beyond what fits in RAM (the `base` model handles files of any length via chunked processing). Processing time scales linearly (~1× real-time on CPU, much faster on GPU).
- OpenAI API: accepts files up to 25 MB. For larger files, the pipeline auto-splits into segments and concatenates transcripts.
- Recommended max: 60 minutes per file for responsive UX. Longer recordings should be split beforehand.

### 22.3 Data Model

```sql
CREATE TABLE transcriptions (
    id          TEXT PRIMARY KEY,
    file_id     TEXT NOT NULL REFERENCES files(id),
    text        TEXT NOT NULL,
    language    TEXT,
    duration_s  REAL,
    engine      TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 22.4 Agent Integration

When a transcription completes:
1. The transcript is injected into the session as a user message: *"[Transcription of {filename}]: {text}"*.
2. If the session has `auto_respond: true`, this triggers a new turn automatically.
3. The agent can also call the `transcribe` tool to request on-demand transcription of any uploaded audio file.

```python
@tool(safety="read_only")
def transcribe(
    file: str,                           # file_id of an uploaded audio file
    language: str | None = None,         # language hint (auto-detect if None)
    engine: Literal["auto", "local", "openai_api"] = "auto",
) -> TranscriptionResult:
    """Transcribe an audio file to text. Returns transcript + metadata."""

class TranscriptionResult(BaseModel):
    text: str
    language: str
    duration_s: float
    engine: str
```

---

## 23) Budget & Cost Tracking

### 23.1 Cost Model

```python
class ProviderPricing(BaseModel):
    provider_id: str
    model: str
    input_cost_per_1k: float      # USD per 1K input tokens
    output_cost_per_1k: float     # USD per 1K output tokens
    effective_date: str           # ISO date; latest wins

class TurnCost(BaseModel):
    turn_id: str
    session_id: str
    agent_id: str
    provider_id: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    timestamp: str
```

### 23.2 Cost Calculation

After every LLM call, the provider adapter returns token counts. The budget tracker:
1. Looks up `ProviderPricing` for the `(provider_id, model)` pair.
2. Computes `cost_usd = (input_tokens * input_cost_per_1k + output_tokens * output_cost_per_1k) / 1000`.
3. Persists a `TurnCost` record.
4. Emits `budget.turn_cost` gateway event.

### 23.3 Budget Caps

```python
class BudgetCap(BaseModel):
    period: Literal["daily", "monthly"]
    limit_usd: float
    action: Literal["warn", "block"] = "warn"
```

- **warn**: Gateway emits `budget.warning` at 80% and 100% of cap. Agent continues.
- **block**: At 100%, all LLM calls are rejected with `budget_exceeded` error. Agent receives a system message explaining the block.

Caps are configurable in Settings. Default: no cap (unlimited).

### 23.4 Attribution & Reporting

```
GET /api/budget/summary?period=daily&date=2026-03-13
GET /api/budget/summary?period=monthly&month=2026-03
GET /api/budget/by-agent?period=monthly&month=2026-03
GET /api/budget/by-provider?period=daily&date=2026-03-13
```

Each endpoint returns aggregated `total_cost_usd`, `total_input_tokens`, `total_output_tokens`, broken down by the requested dimension.

### 23.5 UI Visibility

The frontend displays:
- **Dashboard widget**: Today's spend, month-to-date spend, active cap status.
- **Session detail**: Per-turn cost breakdown (hover to see token counts).
- **Settings → Budget**: Cap configuration, pricing overrides, cost history chart.

---

## 24) Notification Preference Model

### 24.1 Notification Events

Every system event that can produce a user-facing notification is tagged with a `notification_type`:

| Type | Example trigger |
|---|---|
| `agent.run.error` | Turn failed after retries exhausted |
| `agent.run.complete` | Background/cron agent finished a task |
| `budget.warning` | Spend reached 80% of cap |
| `budget.exceeded` | Spend reached 100% of cap (block mode) |
| `plugin.error` | Plugin auth expired or health check failed |
| `plugin.deactivated` | Plugin stopped (manual or error) |
| `scheduler.skipped` | Cron job skipped due to contention |
| `backup.complete` | Backup finished successfully |
| `backup.failed` | Backup failed |
| `inbound.message` | New message arrived via external channel |

### 24.2 Delivery Channels

Notifications can be delivered through:
1. **In-app toast** (WebSocket push to frontend) — always available.
2. **System notification** (OS-level via Notification API) — requires browser permission.
3. **Email** (via configured SMTP/Gmail plugin) — optional.
4. **Telegram** (via configured Telegram plugin) — optional.

### 24.3 Preference Model

```python
class NotificationPreference(BaseModel):
    notification_type: str        # matches types above, or "*" for default
    channels: list[Literal["in_app", "system", "email", "telegram"]]
    enabled: bool = True
```

Stored in a `notification_preferences` table. The notification dispatcher:
1. Receives a notification event.
2. Looks up matching preference (exact type first, then `"*"` fallback).
3. Dispatches to each enabled channel.

### 24.4 API

```
GET    /api/notifications/preferences
PUT    /api/notifications/preferences     — bulk update
GET    /api/notifications/history?limit=50&offset=0
PATCH  /api/notifications/{id}/read
POST   /api/notifications/read-all
```

### 24.5 Proactive Notification Plumbing

Many system events need to surface to the user even when they didn't initiate the interaction. The **notification dispatcher** is the bridge between background processes and the user.

**Notification flow:**

```
Background event occurs (cron complete, channel message, extraction conflict, budget warning, etc.)
    │
    ▼
1. Source emits a typed gateway event (e.g., agent.run.complete, inbound.message, budget.warning)
    │
    ▼
2. Notification manager catches the event (subscribed to all notification_type events)
    │
    ▼
3. Look up NotificationPreference for this notification_type
    │
    ▼
4. For each enabled delivery channel:
    ├─ in_app → emit `notification.push` gateway event → WS pushes to frontend → toast displayed
    ├─ system → emit `notification.push` with system flag → frontend triggers Notification API
    ├─ email → format notification body → call email plugin's send tool → delivery tracked
    └─ telegram → format notification body → call telegram plugin's send tool → delivery tracked
    │
    ▼
5. Persist to `notifications` table (for history & read tracking)
```

**`notification.push` gateway event payload:**

```python
class NotificationPayload(BaseModel):
    notification_id: str
    notification_type: str               # e.g., "agent.task_complete"
    title: str                           # short summary for toast/banner
    body: str                            # full message
    severity: Literal["info", "warning", "error"] = "info"
    action_url: str | None = None        # deep link (e.g., "/sessions/cron:job_123")
    source_session_key: str | None = None  # originating session (for "go to session" action)
    created_at: datetime
```

**Proactive session injection**: For certain notification types, the result is also injected into the user's active webchat session as a system message, so the main agent is aware:
- `agent.task_complete` → *"[Background task completed] Job 'daily_digest' finished. Summary: ..."*
- `message.channel` → *"[New Telegram message from Alice] 'Hey, are we meeting tomorrow?'"*
- `budget.exceeded` → *"[Budget alert] Daily spending limit reached ($5.00/$5.00). LLM calls are blocked."*
- `backup.failed` → *"[Backup alert] Scheduled backup failed: {error}."*
- `plugin.disconnected` → *"[Plugin alert] Telegram plugin disconnected: token expired."*

This list is **extensible** — any `notification_type` can opt into session injection by adding a `session_inject_template` in the notification dispatcher config. The template receives the `NotificationPayload` fields and renders a system message string. Default injection types are: `agent.task_complete`, `message.channel`, `budget.exceeded`, `backup.failed`, `plugin.disconnected`.

This lets the main agent proactively mention results to the user in conversation, not just via a toast.

---

## 25) Search System

### 25.1 Searchable Domains

| Domain | What's searched | Index type |
|---|---|---|
| **messages** | Session message content | FTS5 |
| **notes** | Knowledge vault notes | FTS5 + vector |
| **files** | Uploaded file metadata + extracted text | FTS5 |
| **agents** | Agent names, descriptions, soul text | FTS5 |
| **plugins** | Plugin names, descriptions | FTS5 |

**Relationship to memory search**: The unified search system covers user-visible content (messages, notes, files). Structured memories and entities are searched via the dedicated `memory_search` and `entity_search` agent tools (§5.7), which use the memory embedding index (§5.13) and entity store — not the FTS5 tables above. This separation keeps the user-facing search fast and focused, while the agent's memory tools provide deeper, type-aware, entity-linked recall.

### 25.2 Unified Search API

```
GET /api/search?q=<query>&domains=messages,notes&limit=20&offset=0
```

Response:

```json
{
  "results": [
    {
      "domain": "messages",
      "id": "msg_abc",
      "session_id": "sess_123",
      "snippet": "...matched text with <mark>highlights</mark>...",
      "score": 0.95,
      "created_at": "2026-03-13T10:00:00Z"
    }
  ],
  "total": 42,
  "limit": 20,
  "offset": 0
}
```

### 25.3 Full-Text Search (FTS5)

SQLite FTS5 virtual tables are created for each searchable domain:

```sql
CREATE VIRTUAL TABLE messages_fts USING fts5(
    content, session_id UNINDEXED, created_at UNINDEXED,
    content=messages, content_rowid=rowid
);
```

Triggers keep FTS tables in sync with source tables on INSERT/UPDATE/DELETE.

### 25.4 Semantic Search (Vector)

For the `notes` domain, embedding-based search is also available:
- Uses the same embedding index from §5 (Memory System).
- Queries can opt into `mode: "semantic"` or `mode: "hybrid"` (FTS + vector, RRF merge).

### 25.5 Agent Search Tool

Agents can invoke a `search` tool:

```python
@tool(safety="read_only")
def search(query: str, domains: list[str] = ["notes", "messages"], limit: int = 10) -> list[dict]:
    """Search across knowledge, messages, and files."""
```

This allows agents to self-serve information retrieval without custom per-domain tools.

---

## 26) Backup & Restore

### 26.1 What's Backed Up

| Component | Location | Included |
|---|---|---|
| SQLite database | `data/tequila.db` | Yes — full copy |
| Uploaded files | `data/uploads/` | Yes |
| Vault documents | `data/vault/` | Yes |
| Embedding index | `data/embeddings/` | Yes |
| Configuration | `config` SQLite table (exported as JSON on backup) | Yes |
| Plugins (custom) | `app/plugins/custom/` | Yes |
| Application code | `app/`, `frontend/` | No — restored from repo |

### 26.2 Backup Format

```
tequila_backup_{YYYY-MM-DD_HHmmss}.tar.gz
├── tequila.db
├── uploads/
├── vault/
├── embeddings/
├── config.json          # exported from config SQLite table
└── plugins_custom/
```

**Intentionally excluded**: `data/logs/` (application logs are machine-specific, high-volume, and not needed for restore — the target machine generates its own logs) and `data/browser_profiles/` (browser cookie/session profiles are machine-specific and may contain sensitive auth tokens).

### 26.3 Triggers

| Trigger | Mechanism |
|---|---|
| **Manual** | `POST /api/backup` or UI button |
| **Scheduled** | Cron expression in settings (default: daily at 03:00) |
| **Pre-migration** | Automatic before any Alembic migration runs |

### 26.4 Retention

```python
class BackupConfig(BaseModel):
    enabled: bool = True
    schedule_cron: str = "0 3 * * *"
    retention_count: int = 7          # keep last N backups
    backup_dir: str = "data/backups"
```

Old backups beyond `retention_count` are deleted oldest-first after each successful backup.

### 26.5 Restore Procedure

```
POST /api/backup/restore
Content-Type: multipart/form-data
Body: backup file (.tar.gz)
```

Restore steps:
1. Validate archive integrity (check expected files exist).
2. Stop all active sessions and the scheduler.
3. Back up current state as `pre_restore_{timestamp}.tar.gz`.
4. Extract archive to `data/`.
5. Run any pending Alembic migrations (backup may be from an older version).
6. Rebuild FTS indexes.
7. Restart gateway, scheduler, and plugins.

### 26.6 Machine Migration

To move Tequila to a new machine:

**Development mode** (source checkout):
1. Create a backup on the source machine.
2. Install Tequila on the target machine (clone repo, install deps).
3. Copy the `.tar.gz` to the target.
4. Run restore via API or CLI: `python -m app.backup.restore path/to/backup.tar.gz`.

**Frozen mode** (Windows installer):
1. Create a backup on the source machine (UI button or `POST /api/backup`).
2. Install Tequila on the target machine using the same (or newer) version installer.
3. Launch Tequila on the target — the first-run setup wizard will appear.
4. Skip the wizard and restore from backup: copy the `.tar.gz` to any location, then use the UI's restore feature or call `POST /api/backup/restore` with the backup file.
5. Alembic migrations run automatically if the backup is from an older version.

---

## 27) Testing Strategy

### 27.1 Test Layers

| Layer | Scope | Runner | Target |
|---|---|---|---|
| **Unit** | Single function/class | `pytest` | All business logic, models, utilities |
| **Integration** | Multiple components, real DB | `pytest` + fixtures | API routes, gateway routing, turn loop |
| **Plugin** | Plugin lifecycle, auth, message handling | `pytest` + mock gateway | All built-in plugins, custom plugin contract |
| **E2E** | Full stack (backend + frontend) | Playwright | Critical user flows |

### 27.2 Test Infrastructure

```python
# conftest.py — shared fixtures
@pytest.fixture
def test_db():
    """In-memory SQLite with all migrations applied."""
    engine = create_engine("sqlite:///:memory:")
    run_migrations(engine)
    yield engine

@pytest.fixture
def test_gateway(test_db):
    """Gateway instance with test DB and no real providers."""
    return Gateway(db=test_db, providers={})

@pytest.fixture
def test_client(test_gateway):
    """FastAPI TestClient wired to test gateway."""
    app = create_app(gateway=test_gateway)
    return TestClient(app)

@pytest.fixture
def mock_provider():
    """LLMProvider that returns canned responses."""
    return MockProvider(responses=["Hello from mock."])
```

### 27.3 Plugin Test Harness

Every plugin type has a corresponding test harness:

```python
class PluginTestHarness:
    """Provides a sandboxed gateway, fake channels, and assertion helpers."""

    def __init__(self, plugin_class: type[PluginBase]):
        self.gateway = FakeGateway()
        self.plugin = plugin_class()
        self.plugin.initialize(self.gateway)

    async def send_message(self, text: str) -> list[GatewayEvent]:
        """Simulate an inbound message and capture emitted events."""

    async def trigger_hook(self, event: GatewayEvent) -> GatewayEvent | None:
        """Run a pipeline hook and return the transformed event."""

    def assert_event_emitted(self, event_type: str, **field_matches):
        """Assert the plugin emitted a specific event type."""
```

### 27.4 Mock Providers

`MockProvider` implements `LLMProvider` and supports:
- **Scripted responses**: Returns pre-defined strings in sequence.
- **Tool call simulation**: Returns tool-call responses to test the tool execution loop.
- **Streaming simulation**: Yields tokens with configurable delays.
- **Error injection**: Raises specific errors on configurable turn numbers.

### 27.5 Coverage & CI Targets

| Metric | Target |
|---|---|
| Unit test coverage | ≥ 80% line coverage |
| Integration test coverage | All API routes, all gateway event types |
| Plugin test coverage | All built-in plugins have ≥ 1 happy-path + 1 error test |
| E2E test coverage | Login → chat → tool use → settings change |
| CI gate | All tests pass, coverage ≥ threshold, no type errors (`pyright`) |

### 27.6 Test Naming Convention

```
tests/
├── unit/
│   ├── test_gateway.py
│   ├── test_session_policy.py
│   └── test_budget_tracker.py
├── integration/
│   ├── test_api_sessions.py
│   ├── test_turn_loop.py
│   └── test_plugin_lifecycle.py
├── plugins/
│   ├── test_telegram_plugin.py
│   ├── test_gmail_plugin.py
│   └── test_custom_plugin.py
└── e2e/
    ├── test_chat_flow.py
    └── test_settings.py
```

---

## 28) Project File Structure

### 28.1 Repository Layout

```
tequila/
├── main.py                              # Entry point — uvicorn + browser open
├── pyproject.toml                       # Project metadata, dependencies, scripts, build config
├── requirements.txt                     # Pinned deps (generated from pyproject.toml)
├── alembic.ini                          # Alembic config (points to alembic/ directory)
├── .env.example                         # Example environment variables
├── .gitignore
├── README.md
│
├── alembic/                             # Database migrations
│   ├── env.py
│   ├── script.py.mako
│   └── versions/                        # Migration scripts (0001_baseline.py, ...)
│
├── app/                                 # ── BACKEND ──────────────────────────
│   ├── __init__.py
│   ├── config.py                        # AppConfig loader, defaults, runtime path resolution
│   ├── constants.py                     # App-wide constants, version string
│   ├── exceptions.py                    # Base exception hierarchy (TequilaError, etc.)
│   ├── paths.py                         # Runtime path resolution (frozen exe vs dev mode)
│   │
│   ├── gateway/                         # §2 Gateway Architecture
│   │   ├── __init__.py
│   │   ├── router.py                    # Event router, dispatch, sequencing
│   │   ├── events.py                    # GatewayEvent model + all 23 event types
│   │   ├── policy.py                    # SessionPolicy, presets, enforcement points
│   │   └── buffer.py                    # EventBuffer for WS reconnection (§2.5a)
│   │
│   ├── sessions/                        # §3 Session Model
│   │   ├── __init__.py
│   │   ├── store.py                     # Session CRUD, lifecycle states, idle detection
│   │   ├── models.py                    # Session, Message, ContentBlock, ToolCallRecord
│   │   ├── branching.py                 # Edit-and-resubmit, regenerate (§3.5)
│   │   └── export.py                    # Transcript export: markdown, JSON, PDF (§13.4)
│   │
│   ├── agent/                           # §4 Agent Runtime
│   │   ├── __init__.py
│   │   ├── models.py                    # AgentConfig, SoulConfig, ContextBudget
│   │   ├── turn_loop.py                 # Turn execution: prompt → provider → tool calls → persist
│   │   ├── prompt_assembly.py           # 9-step prompt assembly pipeline (§4.3a)
│   │   ├── escalation.py               # Escalation protocol (§4.2a)
│   │   ├── soul.py                      # Soul generation, Jinja2 templates (§4.1a)
│   │   ├── skills.py                    # Skill model, auto-attach logic
│   │   └── compression.py              # In-session context compression (§5.12)
│   │
│   ├── providers/                       # §4.6 Provider Abstraction
│   │   ├── __init__.py
│   │   ├── base.py                      # LLMProvider ABC, ProviderStreamEvent, ToolDef, ToolResult
│   │   ├── registry.py                  # Provider registry, ModelCapabilities cache
│   │   ├── anthropic.py                 # Anthropic adapter
│   │   ├── openai.py                    # OpenAI adapter
│   │   ├── ollama.py                    # Ollama adapter (§4.6c)
│   │   └── circuit_breaker.py           # RetryPolicy, CircuitBreaker (§19)
│   │
│   ├── memory/                          # §5 Memory System (tiers 1–2)
│   │   ├── __init__.py
│   │   ├── models.py                    # MemoryExtract, Entity, MemoryEvent, MemoryScope
│   │   ├── extraction.py               # 6-step extraction pipeline (§5.5)
│   │   ├── recall.py                    # 3-stage recall pipeline (§5.6)
│   │   ├── lifecycle.py                 # Decay, consolidation, archival (§5.8)
│   │   ├── entity_store.py             # Entity CRUD, NER, alias resolution (§5.4)
│   │   ├── tools.py                     # 13 agent memory tools (§5.7)
│   │   └── audit.py                     # Memory event logging (§5.9)
│   │
│   ├── embeddings/                      # §5.13 Embedding Engine
│   │   ├── __init__.py
│   │   ├── base.py                      # EmbeddingProvider ABC, EmbeddingStore ABC
│   │   ├── local_provider.py            # sentence-transformers (all-MiniLM-L6-v2)
│   │   ├── openai_provider.py           # OpenAI text-embedding-3-small/large
│   │   ├── ollama_provider.py           # Ollama embedding models
│   │   └── sqlite_store.py             # SQLiteEmbeddingStore (numpy brute-force)
│   │
│   ├── knowledge/                       # §5.10–5.11, §5.14
│   │   ├── __init__.py
│   │   ├── vault.py                     # Vault note CRUD, wiki-links, file watcher (§5.10)
│   │   ├── graph.py                     # Knowledge graph construction, API (§5.11)
│   │   ├── registry.py                  # KnowledgeSourceRegistry (§5.14)
│   │   ├── tools.py                     # kb_search, kb_list_sources
│   │   └── adapters/                    # Knowledge source backend adapters
│   │       ├── __init__.py
│   │       ├── base.py                  # KnowledgeSourceAdapter ABC, KnowledgeChunk
│   │       ├── chroma.py               # ChromaAdapter (optional dep: chromadb)
│   │       ├── pgvector.py             # PgVectorAdapter (optional dep: asyncpg + pgvector)
│   │       ├── faiss.py                # FAISSAdapter (optional dep: faiss-cpu)
│   │       └── http.py                 # HTTPAdapter (uses httpx)
│   │
│   ├── auth/                            # §6 Authentication
│   │   ├── __init__.py
│   │   ├── store.py                     # AuthStore — token persistence, credential lookup
│   │   ├── openai_oauth.py             # OpenAI PKCE flow
│   │   ├── anthropic_oauth.py          # Anthropic PKCE flow
│   │   └── api_key.py                  # API key validation
│   │
│   ├── scheduler/                       # §7 Scheduler
│   │   ├── __init__.py
│   │   ├── manager.py                   # Scheduler runtime, cron evaluation
│   │   └── models.py                    # SchedulerTask model
│   │
│   ├── plugins/                         # §8 Plugin System
│   │   ├── __init__.py
│   │   ├── base.py                      # PluginBase ABC, PluginAuth, PluginHealthResult
│   │   ├── registry.py                  # Plugin registry, lifecycle management
│   │   ├── dependencies.py             # PluginDependencies, install flow (§8.9)
│   │   ├── builtin/                     # Built-in plugins
│   │   │   ├── __init__.py
│   │   │   ├── webchat.py              # WebChat adapter (always active)
│   │   │   ├── telegram.py             # Telegram bot (channel + tools)
│   │   │   ├── gmail.py               # Gmail (OAuth2, channel + tools)
│   │   │   ├── smtp_imap.py           # Generic email (IMAP/SMTP)
│   │   │   ├── google_calendar.py     # Google Calendar (tools + optional trigger)
│   │   │   ├── webhooks.py            # Inbound webhook adapter
│   │   │   ├── browser.py             # Playwright browser automation (25 tools)
│   │   │   └── documents/             # Document tools sub-package
│   │   │       ├── __init__.py         # Plugin class, tool registration
│   │   │       ├── pptx_tools.py       # PowerPoint create/open/edit/from_markdown
│   │   │       ├── docx_tools.py       # Word create/open/edit/from_markdown
│   │   │       ├── xlsx_tools.py       # Excel create/open/edit
│   │   │       ├── pdf_tools.py        # PDF full suite (PyMuPDF, pypdf, fpdf2)
│   │   │       ├── csv_tools.py        # CSV/TSV open/query (DuckDB)
│   │   │       ├── chart_tools.py      # Chart rendering (matplotlib)
│   │   │       └── data_analysis.py    # data_analyze, data_to_chart
│   │   └── custom/                      # User-written plugins (auto-discovered)
│   │       └── .gitkeep
│   │
│   ├── tools/                           # §11, §16–17 Tool Framework + Core Tools
│   │   ├── __init__.py
│   │   ├── registry.py                  # Tool registry, safety classification (§11.1)
│   │   ├── executor.py                  # Tool execution, approval gates (§11.2)
│   │   ├── filesystem.py               # fs_* tools + path policy (§16)
│   │   ├── code_exec.py                # code_exec sandboxed subprocess (§16.7)
│   │   ├── web_search.py               # web_search tool (§17.1)
│   │   ├── web_fetch.py                # web_fetch tool (§17.2)
│   │   ├── vision.py                    # vision_* tools (§17.4)
│   │   └── search.py                    # Unified search agent tool (§25.5)
│   │
│   ├── web/                             # §17 Web Access internals
│   │   ├── __init__.py
│   │   ├── policy.py                    # WebPolicy model (§17.5)
│   │   ├── cache.py                     # Web cache — search + fetch (§17.6)
│   │   └── providers/                   # Search provider backends
│   │       ├── __init__.py
│   │       ├── duckduckgo.py           # Default (no API key)
│   │       ├── brave.py
│   │       ├── tavily.py
│   │       ├── google.py
│   │       ├── bing.py
│   │       └── searxng.py
│   │
│   ├── workflows/                       # §10 Multi-Agent Workflows
│   │   ├── __init__.py
│   │   ├── models.py                    # Workflow, WorkflowExecution, step models
│   │   ├── runner.py                    # Pipeline + parallel execution modes
│   │   └── store.py                     # Workflow CRUD
│   │
│   ├── files/                           # §21 File Uploads
│   │   ├── __init__.py
│   │   ├── store.py                     # Upload storage, metadata, file_id resolution
│   │   ├── context_injection.py        # MIME-type routing, smart previews (§21.4)
│   │   └── cleanup.py                  # Retention policy, orphan detection, quota (§21.7)
│   │
│   ├── transcription/                   # §22 Audio & Transcription
│   │   ├── __init__.py
│   │   ├── pipeline.py                  # Transcription queue, Whisper integration
│   │   └── models.py                    # TranscriptionConfig, TranscriptionResult
│   │
│   ├── budget/                          # §23 Budget & Cost
│   │   ├── __init__.py
│   │   ├── tracker.py                   # Cost calculation, cap enforcement
│   │   └── models.py                    # ProviderPricing, TurnCost, BudgetCap
│   │
│   ├── notifications/                   # §24 Notifications
│   │   ├── __init__.py
│   │   ├── dispatcher.py               # Notification routing, proactive injection (§24.5)
│   │   └── models.py                    # NotificationPreference, NotificationPayload
│   │
│   ├── search/                          # §25 Search System
│   │   ├── __init__.py
│   │   ├── engine.py                    # Unified search: FTS5 + optional vector
│   │   └── indexer.py                   # FTS index sync triggers
│   │
│   ├── backup/                          # §26 Backup & Restore
│   │   ├── __init__.py
│   │   ├── manager.py                   # Backup creation, restore, retention
│   │   └── models.py                    # BackupConfig
│   │
│   ├── audit/                           # §12 Observability
│   │   ├── __init__.py
│   │   ├── logger.py                    # Structured JSON logging (§12.4)
│   │   └── log.py                       # Audit log (§12.1)
│   │
│   ├── db/                              # §14 Data Persistence
│   │   ├── __init__.py
│   │   ├── connection.py               # SQLite connection, WAL mode, busy_timeout
│   │   └── schema.py                   # Table creation helpers, shared DB utilities
│   │
│   └── api/                             # §13 API Surface
│       ├── __init__.py
│       ├── app.py                       # FastAPI app factory, lifespan, static file mount
│       ├── deps.py                      # Dependency injection (gateway, db, auth_store)
│       ├── ws.py                        # WebSocket endpoint (§13.2)
│       └── routers/                     # One router module per API domain
│           ├── __init__.py
│           ├── system.py               # /api/status, /api/health, /api/setup, /api/config, /api/lock
│           ├── auth.py                 # /api/auth/*
│           ├── sessions.py             # /api/sessions/*
│           ├── messages.py             # /api/messages/*
│           ├── agents.py               # /api/agents/*, /api/agent/quick-turn
│           ├── skills.py               # /api/skills/*
│           ├── tools.py                # /api/tools/*
│           ├── workflows.py            # /api/workflows/*, /api/workflow-executions/*
│           ├── scheduler.py            # /api/scheduler/*
│           ├── memory.py               # /api/memory/*, /api/entities/*
│           ├── graph.py                # /api/graph/*
│           ├── search.py               # /api/search/*
│           ├── files.py                # /api/files/*
│           ├── budget.py               # /api/budget/*
│           ├── notifications.py        # /api/notifications/*
│           ├── backup.py               # /api/backup/*
│           ├── plugins.py              # /api/plugins/*
│           ├── knowledge_sources.py    # /api/knowledge-sources/*
│           ├── web.py                  # /api/web/*, /api/browser/*, /api/vision/*
│           └── logs.py                 # /api/logs, /api/audit
│
├── frontend/                            # ── FRONTEND (React SPA) ─────────────
│   ├── index.html                       # HTML shell (theme script in <head>)
│   ├── package.json                     # npm deps: react, vite, tailwind, shadcn, etc.
│   ├── vite.config.mjs                 # Vite config (proxy /api → backend in dev)
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   ├── components.json                  # shadcn/ui config
│   ├── public/
│   │   ├── favicon.ico
│   │   └── icons/                       # PWA icons, app icon
│   └── src/
│       ├── main.tsx                     # React entry point
│       ├── App.tsx                      # Root component, React Router setup
│       ├── api/                         # Server communication layer
│       │   ├── client.ts               # HTTP client (fetch wrapper, auth headers)
│       │   ├── ws.ts                   # WebSocket connection, reconnection logic (§2.5a)
│       │   └── hooks/                  # TanStack Query hooks (one per API domain)
│       │       ├── useSessions.ts
│       │       ├── useAgents.ts
│       │       ├── useMemory.ts
│       │       ├── usePlugins.ts
│       │       ├── useBudget.ts
│       │       ├── useFiles.ts
│       │       ├── useWorkflows.ts
│       │       └── useConfig.ts
│       ├── stores/                      # Zustand stores (ephemeral UI state)
│       │   ├── uiStore.ts             # Sidebar, modals, active theme
│       │   ├── wsStore.ts             # WebSocket state, event stream, seq tracking
│       │   ├── chatStore.ts           # Active session, streaming message, pending approvals
│       │   └── notificationStore.ts   # Toast queue, unread count
│       ├── components/                  # Reusable UI components
│       │   ├── ui/                     # shadcn/ui primitives (Button, Dialog, etc.)
│       │   ├── chat/                   # ChatMessage, ChatInput, StreamingResponse, ApprovalBanner
│       │   ├── agents/                 # AgentCard, SoulEditor, CapabilityDashboard
│       │   ├── memory/                 # MemoryExplorer, EntityExplorer, MemoryTimeline
│       │   ├── graph/                  # KnowledgeGraph (react-force-graph), filters, ego view
│       │   ├── plugins/               # PluginCard, PluginConfigForm, DependencyInstaller
│       │   ├── workflows/             # WorkflowBuilder, ExecutionView, StepProgress
│       │   ├── settings/              # SettingsPanel, ProviderSetup, WebPolicyEditor
│       │   ├── files/                 # FileCard, FilePreview, UploadDropzone
│       │   └── common/               # CommandPalette, ShortcutOverlay, ThemeToggle
│       ├── pages/                       # Route-level page components
│       │   ├── ChatPage.tsx
│       │   ├── AgentsPage.tsx
│       │   ├── MemoryPage.tsx
│       │   ├── GraphPage.tsx
│       │   ├── WorkflowsPage.tsx
│       │   ├── SettingsPage.tsx
│       │   ├── SetupWizard.tsx
│       │   └── DiagnosticsPage.tsx
│       ├── lib/                         # Shared utilities
│       │   ├── shortcuts.ts            # Keyboard shortcut manager (§9.4)
│       │   ├── theme.ts               # Theme initialization, CSS variable switching
│       │   ├── format.ts              # Date, token count, cost, file size formatters
│       │   └── errors.ts              # Error code → user-friendly message mapping
│       └── types/                       # TypeScript type definitions
│           ├── api.ts                  # API response types (mirrors Pydantic models)
│           ├── events.ts              # WebSocket event payload types
│           └── models.ts              # Shared domain types (Session, Agent, Memory, etc.)
│
├── data/                                # ── RUNTIME DATA (gitignored) ────────
│   ├── tequila.db                       # SQLite database
│   ├── vault/                           # Knowledge vault markdown notes
│   ├── uploads/                         # Uploaded/generated files (YYYY-MM/ subdirs)
│   ├── embeddings/                      # Embedding index cache
│   ├── backups/                         # Backup archives (.tar.gz)
│   ├── auth/                            # Token persistence
│   ├── browser_profiles/               # Playwright persistent profiles
│   ├── logs/                            # Structured application logs
│   └── pptx_templates/                 # User-supplied PowerPoint templates
│
├── tests/                               # ── TESTS (§27) ─────────────────────
│   ├── conftest.py                      # Shared fixtures (test_db, test_gateway, mock_provider)
│   ├── unit/
│   │   ├── test_gateway_router.py
│   │   ├── test_session_policy.py
│   │   ├── test_prompt_assembly.py
│   │   ├── test_memory_extraction.py
│   │   ├── test_memory_recall.py
│   │   ├── test_memory_lifecycle.py
│   │   ├── test_budget_tracker.py
│   │   ├── test_circuit_breaker.py
│   │   └── test_context_budget.py
│   ├── integration/
│   │   ├── test_api_sessions.py
│   │   ├── test_api_agents.py
│   │   ├── test_turn_loop.py
│   │   ├── test_plugin_lifecycle.py
│   │   └── test_knowledge_sources.py
│   ├── plugins/
│   │   ├── test_telegram_plugin.py
│   │   ├── test_gmail_plugin.py
│   │   ├── test_documents_plugin.py
│   │   └── test_custom_plugin.py
│   └── e2e/
│       ├── test_chat_flow.py
│       └── test_settings.py
│
├── scripts/                             # ── BUILD & DEV SCRIPTS ──────────────
│   ├── build_exe.py                     # PyInstaller build script (see §29)
│   ├── build_installer.iss             # Inno Setup script for Windows installer
│   ├── dev.py                           # Start dev server (backend + frontend HMR)
│   └── seed_data.py                     # Seed test/demo data
│
├── installer/                           # ── INSTALLER ASSETS ─────────────────
│   ├── icon.ico                         # Application icon (multi-size .ico)
│   ├── banner.bmp                       # Installer sidebar banner (164×314)
│   ├── header.bmp                       # Installer header banner (150×57)
│   ├── license.txt                      # License text shown during install
│   └── README_installer.md             # Installer build instructions
│
└── docs/                                # ── DOCUMENTATION ────────────────────
    └── application_reference/
        └── tequila_v2_specification.md
```

### 28.2 Module Naming Rules

| Rule | Example |
|---|---|
| Directories match spec section concepts | `memory/`, `gateway/`, `plugins/` |
| Models in `models.py`, business logic in descriptive files | `memory/models.py`, `memory/extraction.py` |
| One router per API domain in `api/routers/` | `routers/sessions.py` → `GET/POST /api/sessions/*` |
| Plugin sub-packages for complex plugins | `plugins/builtin/documents/` (7 tool modules) |
| Adapters in `adapters/` sub-directories | `knowledge/adapters/chroma.py` |
| Frontend: pages in `pages/`, reusable components in `components/` | `pages/ChatPage.tsx`, `components/chat/ChatMessage.tsx` |
| Tests mirror source structure | `app/memory/extraction.py` → `tests/unit/test_memory_extraction.py` |

### 28.3 Import Conventions

```python
# Absolute imports from app root
from app.gateway.events import GatewayEvent
from app.agent.models import AgentConfig, SoulConfig
from app.memory.models import MemoryExtract, Entity
from app.providers.base import LLMProvider, ProviderStreamEvent
from app.plugins.base import PluginBase
from app.tools.registry import tool, ToolDefinition
from app.db.connection import get_db

# Relative imports within a package
# (only for internal module references within the same package)
from .models import MemoryExtract
from .extraction import run_extraction_pipeline
```

### 28.4 Runtime Path Resolution

Tequila must resolve file paths correctly in two modes: development (source checkout) and frozen (PyInstaller executable). The `app/paths.py` module centralizes this:

```python
import os
import sys
from pathlib import Path

def is_frozen() -> bool:
    """True when running as a PyInstaller-bundled executable."""
    return getattr(sys, 'frozen', False)

def app_dir() -> Path:
    """Root of the application code.
    - Dev: repository root (where main.py lives)
    - Frozen: the PyInstaller _MEIPASS temp directory (read-only, contains app code + frontend)"""
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent

def data_dir() -> Path:
    """Root of user data (database, uploads, vault, etc.).
    - Dev: ./data/ relative to repo root
    - Frozen: %LOCALAPPDATA%/Tequila/ (user-writable, persists across updates)"""
    if is_frozen():
        local = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(local) / "Tequila"
    return app_dir() / "data"

def frontend_dir() -> Path:
    """Built frontend static files.
    - Dev: ./frontend/dist/ (after npm run build)
    - Frozen: bundled inside _MEIPASS/frontend/dist/"""
    return app_dir() / "frontend" / "dist"

def custom_plugins_dir() -> Path:
    """User-written plugins directory.
    - Dev: ./app/plugins/custom/
    - Frozen: %LOCALAPPDATA%/Tequila/plugins/ (user-writable)"""
    if is_frozen():
        return data_dir() / "plugins"
    return app_dir() / "app" / "plugins" / "custom"

def alembic_dir() -> Path:
    """Alembic migration scripts.
    - Dev: ./alembic/
    - Frozen: bundled inside _MEIPASS/alembic/"""
    return app_dir() / "alembic"
```

All modules use `paths.data_dir()` instead of hardcoded `data/` — this is the single point of truth for path resolution.

---

## 29) Windows Packaging & Distribution

Tequila ships as a single Windows installer that non-technical users can run without Python knowledge. The packaging pipeline produces a standalone `.exe` installer containing the Python runtime, all dependencies, the built frontend, and a setup wizard.

### 29.1 Packaging Strategy

**Toolchain**: PyInstaller (freeze) + Inno Setup (installer)

| Stage | Tool | Input | Output |
|---|---|---|---|
| 1. Frontend build | `npm run build` | `frontend/src/` | `frontend/dist/` (static files) |
| 2. Python freeze | PyInstaller | `main.py` + `app/` + `frontend/dist/` + `alembic/` | `dist/tequila/` (self-contained directory) |
| 3. Installer | Inno Setup | `dist/tequila/` + installer assets | `TequilaSetup-{version}.exe` |

**Why PyInstaller**: Most mature Python freezer for Windows. Handles complex dependency trees (FastAPI, uvicorn, numpy, sentence-transformers). `--onedir` mode keeps startup fast and allows in-place updates. Well-documented hook system for problematic packages.

**Why Inno Setup**: Free, mature, widely trusted Windows installer framework. Produces a single `.exe` setup wizard. Handles shortcuts, PATH, uninstaller, and Start Menu entries.

### 29.2 PyInstaller Configuration

```python
# scripts/build_exe.py
# Run: python scripts/build_exe.py

import PyInstaller.__main__
import subprocess
import shutil
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Step 1: Build frontend
subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend", check=True)

# Step 2: Clean previous build
shutil.rmtree(ROOT / "dist", ignore_errors=True)
shutil.rmtree(ROOT / "build", ignore_errors=True)

# Step 3: Run PyInstaller
PyInstaller.__main__.run([
    str(ROOT / "main.py"),
    "--name=tequila",
    "--onedir",                          # directory mode (faster startup than --onefile)
    "--noconsole",                       # hide console window (server logs go to file)
    "--icon=installer/icon.ico",
    # Bundle frontend dist
    f"--add-data={ROOT / 'frontend' / 'dist'};frontend/dist",
    # Bundle alembic migrations
    f"--add-data={ROOT / 'alembic'};alembic",
    f"--add-data={ROOT / 'alembic.ini'};.",
    # Bundle built-in plugin modules (already in app/)
    # Hidden imports for dynamic imports that PyInstaller can't detect
    "--hidden-import=uvicorn.logging",
    "--hidden-import=uvicorn.protocols.http.auto",
    "--hidden-import=uvicorn.protocols.websockets.auto",
    "--hidden-import=uvicorn.lifespan.on",
    "--hidden-import=tiktoken_ext.openai_public",
    "--hidden-import=tiktoken_ext",
    "--hidden-import=sentence_transformers",
    # Exclude heavy optional deps (installed on demand by plugin system)
    "--exclude-module=playwright",
    "--exclude-module=chromadb",
    "--exclude-module=faiss",
    "--exclude-module=asyncpg",
    "--exclude-module=torch",            # sentence-transformers loads this lazily
    # Collect all data files for packages that need them
    "--collect-data=tiktoken",
    "--collect-data=sentence_transformers",
    # Output
    f"--distpath={ROOT / 'dist'}",
    f"--workpath={ROOT / 'build'}",
])
```

**Key decisions**:
- **`--onedir`** (not `--onefile`): `--onefile` extracts to a temp directory on every launch (slow, ~10s). `--onedir` keeps files on disk permanently — fast startup (~2s) and allows patching individual files for updates.
- **`--noconsole`**: The GUI is a browser window. Server logs go to `data/logs/tequila.log`. A system tray icon (future) provides "Show Logs" access.
- **Optional deps excluded**: Playwright (~280 MB), torch (~2 GB), chromadb, faiss are NOT bundled. They're installed on-demand when the user activates the corresponding plugin (§8.9). This keeps the base installer under ~200 MB.

### 29.3 Frozen-Mode Adaptations

When running as a frozen executable, several subsystems adapt:

| Subsystem | Dev behavior | Frozen behavior |
|---|---|---|
| **Data directory** | `./data/` | `%LOCALAPPDATA%/Tequila/` |
| **Custom plugins** | `app/plugins/custom/` | `%LOCALAPPDATA%/Tequila/plugins/` |
| **Frontend files** | Vite dev server (proxy) | Static files from `_MEIPASS/frontend/dist/` |
| **Alembic** | `./alembic/` | `_MEIPASS/alembic/` |
| **Plugin pip installs** | Into project `.venv/` | Into `%LOCALAPPDATA%/Tequila/.venv/` (dedicated venv) |
| **Browser open** | `http://localhost:8000` | Same, but auto-opened by `main.py` |
| **Log output** | stdout + file | File only (`data/logs/tequila.log`) |

**Plugin virtual environment** (frozen mode): When a plugin needs to install pip packages (§8.9), it cannot use the frozen Python's environment (read-only). Instead, a dedicated virtual environment is created at `%LOCALAPPDATA%/Tequila/.venv/`. The frozen executable's Python is used as the base interpreter. Plugin packages are installed here and added to `sys.path` at runtime.

```python
# In app/plugins/dependencies.py — frozen-mode adaptation
import sys, subprocess
from app.paths import data_dir, is_frozen

def get_plugin_venv() -> Path:
    """Returns the plugin venv path. Creates it if it doesn't exist."""
    venv_path = data_dir() / ".venv"
    if not venv_path.exists():
        python = sys.executable  # frozen exe's Python
        subprocess.run([python, "-m", "venv", venv_path], check=True)
    return venv_path

def install_plugin_package(package_spec: str) -> None:
    """Install a package into the plugin venv."""
    pip = get_plugin_venv() / "Scripts" / "pip.exe"
    subprocess.run([str(pip), "install", package_spec], check=True)
    # Add venv site-packages to sys.path so imports work immediately
    site_pkgs = get_plugin_venv() / "Lib" / "site-packages"
    if str(site_pkgs) not in sys.path:
        sys.path.insert(0, str(site_pkgs))
```

### 29.4 Inno Setup Installer

```iss
; scripts/build_installer.iss
[Setup]
AppName=Tequila
AppVersion={#AppVersion}
AppPublisher=Tequila Project
DefaultDirName={autopf}\Tequila
DefaultGroupName=Tequila
OutputBaseFilename=TequilaSetup-{#AppVersion}
SetupIconFile=..\installer\icon.ico
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
; Install per-user (no admin required)
UsedUserAreasWarning=no

[Files]
; Copy the entire PyInstaller output directory
Source: "..\dist\tequila\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
; Start Menu shortcut
Name: "{group}\Tequila"; Filename: "{app}\tequila.exe"; IconFilename: "{app}\tequila.exe"
; Desktop shortcut (optional, user chooses during install)
Name: "{commondesktop}\Tequila"; Filename: "{app}\tequila.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional options:"

[Run]
; Launch Tequila after installation
Filename: "{app}\tequila.exe"; Description: "Launch Tequila"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up data directory on full uninstall (if user confirms)
Type: filesandordirs; Name: "{localappdata}\Tequila"
```

**Installer behavior**:
- Installs per-user (no admin rights required) to `C:\Users\{user}\AppData\Local\Programs\Tequila\`
- Creates Start Menu entry + optional desktop shortcut
- Launches Tequila after install
- Uninstaller removes app files; optionally removes user data from `%LOCALAPPDATA%\Tequila\`
- No PATH modification (Tequila is launched via shortcut or `.exe`, not CLI)

### 29.5 Auto-Update (Future)

Not in v1 — users download new installer versions manually. Future implementation path:

| Approach | Mechanism | Notes |
|---|---|---|
| **Installer update** | Check `GET /releases/latest` on startup → show "Update available" notification → user downloads new installer | Simplest. Inno Setup supports incremental installs (overwrite in-place). |
| **In-place patching** | `--onedir` allows replacing individual `.pyd`/`.dll` files | Only for hotfixes. Full updates still use installer. |
| **Squirrel.Windows** | Auto-update framework for Windows apps | More complex but fully automatic. Consider for v3+. |

### 29.6 Build Pipeline Summary

```
Developer machine:
    1. npm run build          → frontend/dist/           (~5 MB)
    2. python build_exe.py    → dist/tequila/            (~150–200 MB)
    3. iscc build_installer.iss → TequilaSetup-2.0.0.exe (~80–100 MB compressed)

User machine:
    1. Run TequilaSetup-2.0.0.exe
    2. Install to C:\Users\{user}\AppData\Local\Programs\Tequila\
    3. Launch tequila.exe → browser opens http://localhost:8000
    4. First-run wizard: choose provider, enter API key, create agent
    5. Start chatting
```

### 29.7 Size Budget

| Component | Estimated size | Notes |
|---|---|---|
| Python runtime | ~30 MB | Embedded Python 3.12 |
| FastAPI + uvicorn + deps | ~15 MB | Core web framework |
| numpy + scipy | ~40 MB | Embedding computation |
| sentence-transformers (base) | ~20 MB | Model downloaded on first use (~90 MB, stored in data/) |
| tiktoken | ~5 MB | Tokenizer data |
| httpx + trafilatura + misc | ~10 MB | Web access, content extraction |
| Frontend (built) | ~5 MB | React SPA static files |
| Alembic + migrations | ~1 MB | |
| **Base total (uncompressed)** | **~130 MB** | |
| **Installer (LZMA compressed)** | **~70–100 MB** | |

Optional plugin dependencies (installed on demand, not in base):

| Plugin | Additional size |
|---|---|
| `documents` (python-pptx, docx, PyMuPDF, duckdb, etc.) | ~180 MB |
| `browser` (playwright + chromium) | ~280 MB |
| `sentence-transformers` model download | ~90 MB |
| `torch` (if GPU inference needed) | ~2 GB |

### 29.8 Dependencies

| Dependency | Purpose | Required? |
|---|---|---|
| `pyinstaller` | Python → frozen executable | Dev only (build time) |
| Inno Setup 6 | `.exe` installer creation | Dev only (build time) |
| Node.js + npm | Frontend build (`npm run build`) | Dev only (build time) |

---

## 30) Decision Log

Decisions locked in during design (March 12 – 13, 2026):

| # | Decision | Choice | Rationale |
|---|---|---|---|
| DL-01 | Frontend framework | React + Vite | Modern SPA, fast dev cycle, rich ecosystem |
| DL-02 | Backend framework | FastAPI (Python) | Existing expertise, async-native, Pydantic integration |
| DL-03 | Database | SQLite | Local-first, zero-config, sufficient for single-user |
| DL-04 | User model | Single-user (multi-user-ready architecture) | Ship fast, don't over-engineer auth |
| DL-05 | Agent hierarchy | Main agent (admin) + scoped sub-agents | Clear authority model, prevents agent chaos |
| DL-06 | Memory scope | Hierarchical: shared pool + per-agent private | Agents share knowledge but keep private scratch space |
| DL-07 | Memory types | 7 structured types (identity, preference, fact, experience, task, relationship, skill) with type-specific recall behaviors | Flat text chunks can't distinguish permanent facts from ephemeral tasks; typed memories enable always-recall, decay, and expiration |
| DL-08 | Entity model | First-class entity graph with NER extraction, alias resolution, and entity-memory linking | Memories about the same thing need structural connection, not just embedding similarity |
| DL-09 | Memory recall | 3-stage pipeline: session pre-load → per-turn query → background pre-fetch + entity graph traversal | Query-time-only recall misses always-relevant context and adds latency every turn |
| DL-10 | Extraction pipeline | 6-step structured pipeline: classify → extract → dedup → conflict → entity-link → graph-edge | "LLM summarizes" is underspecified; explicit pipeline ensures consistency, dedup, and conflict handling |
| DL-11 | Memory lifecycle | Decay (configurable half-life) + weekly consolidation (merge, summarize, archive) | Without decay, recall degrades as thousands of stale extracts compete for context budget |
| DL-12 | Agent memory tools | 13 tools for active memory/entity management (save, update, forget, pin, link, entity CRUD) | Agents need to be active curators, not just passive consumers of recalled memories |
| DL-13 | Memory provenance | Full audit trail on every create/update/merge/access/archive event | Memory mutations must be traceable for trust and debugging |
| DL-14 | Agent communication | Gateway with session-based routing (OpenClaw-inspired) | Unified event plane, not just agent plumbing |
| DL-15 | Schema validation | Pydantic models (runtime validation + JSON Schema export) | Native Python, no separate validation library |
| DL-16 | Auth security | GATEWAY_TOKEN in connect frame (reserved, not enforced locally) | Future-proof without upfront complexity |
| DL-17 | Multi-client readiness | Request IDs on all frames (dedup cache added when needed) | Schema-ready without implementation overhead |
| DL-18 | Network security | Configurable bind host, reverse proxy for TLS | Deployment concern, not application concern |
| DL-19 | Agent capability control | Per-session SessionPolicy | Controls tools, channels, spawning per agent session |
| DL-20 | Self-modification | Admin agents modify anything; sub-agents self-only | Prevents unauthorized capability escalation |
| DL-21 | Integration model | Unified plugin system (connectors, pipeline hooks, audit sinks) | All extensions share one base class, one API, one management UI, one lifecycle |
| DL-22 | Error handling | Retry + circuit breaker + fallback provider | Resilience without complexity; fail-fast when all options exhausted |
| DL-23 | Concurrency | SQLite WAL + write_transaction + optimistic versioning + idempotency | Serialized writes with short lock holds; version columns for conflict detection; dedup keys for external inputs |
| DL-24 | File handling | Upload endpoint + storage + context injection | Images, PDFs, text, audio all handled uniformly via provider adapters |
| DL-25 | Audio/transcription | Whisper (local or API), async pipeline | Local-first with cloud fallback; transcripts injected as messages |
| DL-26 | Budget tracking | Per-turn cost tracking, daily/monthly caps | User stays in control of spend; per-agent attribution for cost visibility |
| DL-27 | Notifications | Event-type → channel preference mapping | User controls what they see and where; extensible via plugins |
| DL-28 | Search | Unified API over FTS5 + optional vector | One search bar, multiple domains; agents also get a search tool |
| DL-29 | Backup & restore | tar.gz archive, scheduled + manual + pre-migration | Data safety without external backup infrastructure |
| DL-30 | Testing | 4-layer strategy (unit, integration, plugin harness, E2E) | Confidence at every level; plugin test harness lowers barrier for custom plugins |
| DL-31 | Document tools | Built-in plugin with PPTX, DOCX, XLSX, CSV, PDF (full read/edit/create) + charts + data analysis | Proven in v1 (PowerPoint + Excel); expanded with Word, CSV, comprehensive PDF (PyMuPDF for reading, pypdf for manipulation, fpdf2 for creation), DuckDB-powered CSV queries, data analysis tools, markdown→slides |
| DL-32 | PDF library choice | PyMuPDF + pymupdf4llm (reading), pypdf (manipulation), fpdf2 (creation) | PyMuPDF is 10–100× faster than pdfminer, only library that can render pages to images (critical for scanned PDF → vision fallback), pymupdf4llm outputs LLM-optimized markdown. pypdf is pure-Python BSD for merge/split/form-fill. AGPL not a concern for local-first desktop app |
| DL-33 | CSV handling | DuckDB in-process SQL engine for CSV queries | DuckDB reads CSV/Parquet/JSON natively, handles larger-than-memory files, 10–100× faster than pandas for analytical queries, single ~30 MB dependency, BSD license. SQL is universally understood by LLMs |
| DL-34 | Upload context injection | Smart MIME-type routing: each file type gets structured preview via its document tool, not raw text dump | Raw text injection breaks for PDFs (binary), spreadsheets (tabular data needs structure), and large CSVs (context window explosion). Structured preview + on-demand deep access via tools is the right pattern |
| DL-35 | Filesystem access | Open by default (user home tree), deny-list for sensitive paths, per-session working directory | Agent needs real-world file access beyond the vault; safety via deny-list + confirmation gates, not allow-list friction |
| DL-36 | Knowledge graph | Obsidian-style interactive graph with wiki-links, semantic edges, entity nodes, memory-entity links | Visual knowledge exploration is a core differentiator; entity-centric graph enables structured traversal; `react-force-graph` for rendering, incremental graph maintenance |
| DL-37 | Web access architecture | 3-layer: search (core) → fetch (core) → browser (plugin) | Progressive capability: search + fetch cover 90% of use cases with zero setup; browser automation is opt-in for the 10% requiring interactive browsing |
| DL-38 | Default search provider | DuckDuckGo (no API key) | Works out of the box, privacy-respecting, no cost; users can switch to Brave/Tavily/Google/Bing/SearXNG |
| DL-39 | Web fetch approach | httpx + trafilatura (light) with Playwright fallback (full) | Light mode handles most pages in ~1s; full mode only for JS-heavy SPAs; auto-detection with per-domain caching |
| DL-40 | SSRF prevention | Block private network ranges, localhost, link-local; block file/ftp/data/javascript schemes | SSRF is the #1 web access attack vector; deny-list on private IPs catches all common vectors without breaking external access |
| DL-41 | Browser as plugin (not core) | Built-in plugin requiring opt-in activation | Playwright + browser binaries add ~280 MB; stateful sessions carry safety risk; most agents only need search + fetch |
| DL-42 | Browser engine | Playwright (Chromium default, Firefox/WebKit optional) | Playwright's unified API across engines avoids vendor lock-in; Chromium for compat, Firefox/WebKit for diversity |
| DL-43 | Vision system | Cross-cutting capability: 4 core tools (describe, extract_text, compare, analyze) that work on images from any source | Vision is not file-upload-specific — it applies equally to browser screenshots, chart renders, document images, clipboard pastes; unified pipeline avoids duplicating logic per source |
| DL-44 | Vision-driven browsing | `browser_act` tool: screenshot → vision model → coordinate extraction → action | Works on any page regardless of DOM structure; accessibility tree for structured data + vision for visual layout = best of both worlds |
| DL-45 | Browser profiles | Persistent cookie/localStorage profiles per domain | One-time login → reusable sessions; critical for authenticated browsing workflows without requiring users to re-enter credentials each time |
| DL-46 | Soul config model | Structured `SoulConfig` with persona, instructions, tone, verbosity, Jinja2 system prompt template (§4.1a) | Agent personality needs to be structured and templatable, not just a free-text system prompt; Jinja2 enables variable injection (datetime, user name, memory, tools) |
| DL-47 | Prompt assembly pipeline | 9-step ordered pipeline with explicit budget allocation and priority trimming (§4.3a) | "Assemble prompt" is too vague for implementation; each step has a token budget, ordering matters, and trimming must be deterministic |
| DL-48 | Tool-calling protocol | Unified `ProviderStreamEvent` + `ToolDef` + `ToolResult` models with provider-specific formatting in adapters (§4.6a) | Provider APIs use incompatible tool-call wire formats; the agent runtime must work with one internal model and let adapters translate |
| DL-49 | Model capability registry | Per-model `ModelCapabilities` with context window, max output, vision/tools/thinking/structured-output flags, cost rates (§4.6b) | Context budget, vision routing, and model selection all need per-model metadata; a single `supports_vision` boolean is insufficient |
| DL-50 | Proactive notification plumbing | `notification.push` gateway event + proactive session injection for background results (§24.5) | Background work (cron jobs, channel messages, budget alerts) must surface to the user without them asking; both UI toasts and in-session injection needed |
| DL-51 | Configuration persistence | `config` SQLite table with namespaced keys, types, defaults, hot-reload flags (§14.4) | Subsystem configs scattered across code need a single persistence layer; hot-reload vs restart-required distinction prevents user confusion |
| DL-52 | Health & status endpoints | Lightweight `/api/health` probe + full `/api/status` dashboard with per-subsystem status (§13.3) | Frontend needs connection status; diagnostics need provider circuit states, plugin health, scheduler status; liveness probe needed for monitoring |
| DL-53 | Structured logging | JSON structured logs with per-module levels, rotation, API access (§12.4) | Unstructured print statements are undebuggable in production; structured logs enable filtering, searching, and the UI diagnostics panel |
| DL-54 | First-run experience | Setup wizard via `POST /api/setup` — provider auth, model selection, main agent creation (§15.1) | Users need a guided path from empty database to working agent; auto-detecting first run and showing a wizard prevents "what do I do now?" confusion |
| DL-55 | File download & export | File cards in chat messages with local-app quick actions (open file, reveal in Explorer, download, view, pin), inline media rendering (§9.2a), session files panel (§9.2b), download/preview endpoints (§21.6) | Agent creates files but users had no specified path to access them; file cards with inline previews, OS-native open/reveal actions, and a session-level file inventory close the loop for a local desktop app |
| DL-56 | Session transcript export | Markdown, JSON, and PDF export formats with tool/cost inclusion options (§13.4) | Users need to share, archive, or migrate conversations; three formats cover human-readable, machine-readable, and printable use cases |
| DL-57 | Image generation (future) | `image_generation` plugin with DALL-E tools: generate, edit, variations (§8.6) | Natural complement to vision system; creative users benefit from text-to-image generation; deferred to Phase 7 to avoid scope creep |
| DL-58 | Message model | Full typed `Message` with `parent_id` branching, provenance enum, `ContentBlock` list, `ToolCallRecord`, `MessageFeedback` (§3.4) | Messages are the atomic unit of conversation; typed content blocks and tool records enable rich rendering and auditing; `parent_id` chain supports branching without a separate tree structure |
| DL-59 | Embedding engine | SQLite + numpy default, abstract `EmbeddingStore` ABC, `sentence-transformers/all-MiniLM-L6-v2` local default (§5.13) | Chroma adds a dependency for <50K vectors; brute-force cosine over numpy is <10ms at scale; abstract interface allows swapping to Chroma/pgvector later without consumer changes |
| DL-60 | WS reconnection | Seq-based event replay with bounded `EventBuffer` (200 events, 120s), exponential backoff, heartbeat (§2.5a) | WebSocket drops are inevitable; without replay the client loses in-flight tokens and tool results; seq-based approach is simpler than full event sourcing |
| DL-61 | Conversation branching | Moderate: linear rewind with `parent_id` + `active` flag, not full branch tree (§3.5) | Full tree UI is complex and rarely used; linear rewind (edit-and-resubmit, regenerate) covers 95% of user needs with minimal implementation cost |
| DL-62 | Session titles & summary | Auto-generated after first exchange, manual rename, auto-summarize on idle (§3.2, §3.7) | Untitled sessions are unusable once the list grows; auto-generation with manual override balances convenience and control |
| DL-63 | Ollama provider | First-class `OllamaProvider` adapter with model discovery, tiktoken token estimation, GPU/CPU support (§4.6c) | Local models are a core value proposition for local-first; Ollama is the most popular local model runner; first-class support (not just "compatible") ensures good UX |
| DL-64 | Plugin dependencies | Explicit user consent before install, isolated venv, startup verification, `PluginDependencies` model (§8.9) | Auto-installing packages is a security risk; explicit consent + isolated venv prevents dependency conflicts and maintains user trust |
| DL-65 | Message feedback | Thumbs up/down per assistant message, stored on message row, feeds extraction confidence (§3.6) | Simplest useful signal; up/down is unambiguous and low-friction; confidence boost/penalty creates a direct feedback loop into memory quality |
| DL-66 | Escalation protocol | Phrase-match + tool-call + failure-count triggers, gateway `escalation.triggered` event, context transfer (§4.2a) | Sub-agents need a defined handoff path; without escalation protocol, users get stuck when a sub-agent can't help; automated triggers catch failure loops |
| DL-67 | Frontend library stack | Zustand + React Router + Tailwind v4 + shadcn/ui + TanStack Query + Lucide (§9.1) | Locked choices eliminate analysis paralysis during implementation; each library is best-in-class for its concern with minimal overlap |
| DL-68 | Session idle management | 3-state lifecycle (active → idle → archived), auto-summarize on idle, configurable timeouts (§3.7) | Sessions accumulate indefinitely without lifecycle management; idle detection + auto-summarize keeps the sidebar clean while preserving all data |
| DL-69 | File cleanup & retention | Orphan detection, storage quota (5 GB default), soft-delete with grace period, per-category retention (§21.7) | Uploads consume disk indefinitely without cleanup; orphan detection prevents accumulation of unreferenced files; soft-delete prevents accidental data loss |
| DL-70 | Dark mode & theming | CSS custom properties, 3 modes (light/dark/system), localStorage persistence, no server sync (§9.3) | Dark mode is a baseline expectation; CSS variable approach works natively with Tailwind v4 and shadcn/ui; localStorage avoids unnecessary server roundtrips |
| DL-71 | Keyboard shortcuts | Global + context-specific shortcuts, help overlay (Ctrl+Shift+?), tooltip integration (§9.4) | Power users expect keyboard navigation; discoverable shortcuts reduce mouse dependency; approval shortcuts (Y/N/A) speed up tool confirmation workflows |
| DL-72 | Session search & filtering | Sidebar search + status/kind/agent/date filters + sort options, Zustand-stored filter state (§9.5) | Session lists become unmanageable at 50+ sessions; search + filters are essential for findability; client-side filter state keeps the UI responsive |
| DL-73 | Session status enum | `Literal["active", "idle", "archived"]` — `idle` added, `deleted` removed (§3.2, §3.7) | §3.7 defines an active→idle→archived lifecycle but §3.2 was missing `idle` and included `deleted`; deletion is a hard `DELETE` operation, not a status |
| DL-74 | Search config consolidation | `SearchConfig` (§17.1) is a convenience alias for `WebPolicy.search_*` fields (§17.5) — single source of truth in `web.*` namespace | Two overlapping config models caused ambiguity; `WebPolicy` is the canonical model, `SearchConfig` documents the field mapping |
| DL-75 | Quick-turn endpoint | `POST /api/agent/quick-turn` — one-shot agent call without persistent session (§13.1) | Programmatic integrations and quick queries need a stateless call path without session ceremony |
| DL-76 | Knowledge Source Registry | External vector store federation via `KnowledgeSourceRegistry` with hybrid access: auto-recall (gateway-mediated) + on-demand agent tools (`kb_search`, `kb_list_sources`). Per-source query mode (text or vector). 4 backend adapters: Chroma, pgvector, FAISS, generic HTTP (§5.14) | Users need to bring their own knowledge bases for RAG. A first-class registry with adapter ABC enables multiple stores without embedding-model lock-in. Hybrid access ensures important sources are always consulted while agents can also search on demand. |
| DL-77 | Knowledge source budget | Dedicated `knowledge_source_budget` (1500 tokens) in `ContextBudget`, separate from `memory_recall_budget` (§4.3a step 3a) | External knowledge competes with internal memory for context space. A separate budget prevents external sources from crowding out the agent's own memories and vice versa. |
| DL-78 | Knowledge source recall integration | Recall pipeline §5.6 Stage 2 gains steps 4a (parallel federation) and 4b (merge + normalize). Soft-failure with auto-disable after 5 consecutive errors. Prompt assembly renders a separate `## Knowledge Sources` block. | Federated retrieval must not block or degrade the core recall path. Parallel queries with per-source timeout + soft failure keep latency bounded. Separate context block preserves source attribution. |
| DL-79 | Project file structure | Backend: `app/` with sub-packages matching spec sections (gateway, sessions, agent, providers, memory, embeddings, knowledge, plugins, tools, web, etc.). Frontend: `frontend/src/` with pages, components, stores, hooks. Runtime data: `data/` (gitignored). Tests: `tests/` mirroring source structure. (§28) | Structure must map cleanly to spec sections for navigability, support plugin auto-discovery, and work in both dev and frozen-exe modes |
| DL-80 | Windows packaging toolchain | PyInstaller `--onedir` + Inno Setup installer. Per-user install (no admin). Optional deps excluded from base bundle. (§29) | PyInstaller is the most mature Python freezer for Windows. `--onedir` gives fast startup (~2s vs ~10s for `--onefile`) and allows in-place updates. Inno Setup is free, trusted, and produces clean `.exe` installers. |
| DL-81 | Frozen-mode data directory | `%LOCALAPPDATA%\Tequila\` for all user data (db, vault, uploads, logs, plugin venv). Centralized via `app/paths.py` with `is_frozen()` detection. (§28.4, §29.3) | Frozen bundle is read-only (`_MEIPASS`). User data must be in a writable, persistent location that survives updates. `%LOCALAPPDATA%` is the Windows standard for per-user app data. |
| DL-82 | Plugin venv in frozen mode | Dedicated `%LOCALAPPDATA%\Tequila\.venv\` for plugin pip installs. Created on first plugin dependency install. Added to `sys.path` at runtime. (§29.3) | Frozen executable's Python environment is read-only. Plugins that need additional pip packages (playwright, chromadb, duckdb) require a writable venv. Using the frozen Python as base interpreter ensures ABI compatibility. |
| DL-83 | Legacy Office file handling | Old formats (.xls, .doc, .ppt) accepted at upload but routed to a fallback handler that attempts OOXML tool processing; on failure, injects metadata placeholder advising user to re-save as modern format (§21.4) | python-pptx/python-docx/openpyxl only support OOXML. Rejecting old formats at upload would confuse users; graceful fallback with clear guidance is better UX |
| DL-84 | Proactive notification extensibility | Session injection is configurable per `notification_type` via `session_inject_template` with 5 default types; new types can be added without code changes (§24.5) | Hard-coded injection list doesn't scale; template-based approach lets new notification types opt into session injection declaratively |
| DL-85 | Skill system architecture | Three-level progressive disclosure: Level 1 (summary — always in prompt for all assigned skills, ~30 tokens each), Level 2 (instructions — loaded on activation), Level 3 (resources — agent fetches on-demand via tool). `SkillDef` model with summary, instructions, required_tools, trigger_patterns, priority. `SkillResource` model for Level 3 reference material. Three activation modes: always, trigger, manual. Agent has 7 skill tools including `skill_get_instructions` and `skill_read_resource` for navigating levels. 7 built-in skills. Session-scoped override state. Import/export as JSON/YAML v1.1. (§4.5) | Flat single-level model (inject full prompt_fragment or nothing) wastes tokens and blinds the agent to non-triggered skills. Three-level model gives the agent full awareness of available skills (Level 1 index, ~500 tokens for 15 skills) while only paying for detailed instructions when a skill actually activates. Level 3 resources keep reference material out of prompts entirely — the agent pulls them via tool results only when needed. Inspired by Claude Code's SKILL.md frontmatter/body/linked-files pattern. |
| DL-86 | Local-app file actions | "Open file" (OS default app) and "Reveal in Explorer" (open folder with file selected) as primary file card actions, backed by `POST /api/files/{id}/open` and `POST /api/files/{id}/reveal` endpoints (§21.6) | Tequila is a local desktop app — the most natural file interaction is opening it directly or navigating to it in the file manager, not downloading through a browser. These actions are trivial to implement (`os.startfile` / `subprocess`) and eliminate the friction of finding agent-generated files on disk. |
| DL-87 | Inline media rendering | Per-MIME-type rendering rules for chat messages: image lightbox with zoom/pan/navigation, PDF side-panel viewer (browser-native `<iframe>`), syntax-highlighted code previews, inline audio player. Side panel shared between PDF and code viewers. (§9.2a) | File cards with download buttons are functional but not the expected UX for a modern chat app. Inline previews let users see content without leaving the conversation. Browser-native PDF iframe avoids adding pdf.js (~300KB) while providing page nav, zoom, and search for free. Side panel (not modal) lets users reference the chat while reading a document. |
| DL-88 | Session files panel | Collapsible right sidebar panel listing all files in the current session, grouped by origin (upload vs agent-generated), with search, sort, and per-file quick actions. Backed by `GET /api/sessions/{id}/files` endpoint. (§9.2b) | Users lose track of agent-created files as conversations grow. A session-level file inventory provides a single access point without scrolling through messages. Grouped by origin helps distinguish user uploads from agent outputs. |
