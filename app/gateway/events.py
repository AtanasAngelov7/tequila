"""Typed event envelope and the exhaustive event-type catalog for Tequila v2 (§2.2, §2.3).

Every event flowing through the gateway is a ``GatewayEvent`` instance.
Runtime validation is provided by Pydantic; ``ET`` exposes string constants
for every valid ``event_type`` so callers never hard-code raw strings.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


# ── Event source ──────────────────────────────────────────────────────────────


class EventSource(BaseModel):
    """Identity of the component that emitted a gateway event."""

    kind: Literal["user", "agent", "channel", "scheduler", "webhook", "system"]
    """Category of emitter — used for routing decisions and audit logging."""

    id: str
    """Specific identifier of the emitter (agent_id, channel_id, etc.)."""


# ── Stream payload ────────────────────────────────────────────────────────────


class StreamPayload(BaseModel):
    """Typed payload for ``agent.run.stream`` events (§2.3).

    The ``kind`` field determines which other fields are populated.
    """

    kind: Literal[
        "text_delta",
        "tool_call_start",
        "tool_call_input_delta",
        "tool_result",
        "approval_request",
        "approval_resolved",
        "thinking",
        "error",
    ]
    """The kind of streaming event, determining which other fields are set."""

    text: str | None = None
    """Incremental text token (``text_delta``) or reasoning content (``thinking``)."""

    tool_name: str | None = None
    """Tool name for ``tool_call_start``, ``tool_result``, ``approval_request``."""

    tool_call_id: str | None = None
    """Correlates ``tool_call_start`` → input deltas → ``tool_result``."""

    tool_input: dict[str, Any] | None = None
    """Partial JSON input for ``tool_call_input_delta``."""

    tool_result: dict[str, Any] | None = None
    """Execution result payload for ``tool_result`` events."""

    approval_action: Literal["approve", "deny"] | None = None
    """User decision for ``approval_resolved`` events."""

    error_message: str | None = None
    """Non-fatal error description for ``error`` events."""


# ── Core event envelope ───────────────────────────────────────────────────────


class GatewayEvent(BaseModel):
    """Universal event envelope used by every gateway interaction (§2.2).

    All events flowing through ``GatewayRouter`` are wrapped in this model,
    providing a consistent structure for routing, filtering, and audit logging.
    """

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """UUID uniquely identifying this event — used for correlation and dedup."""

    event_type: str
    """Dot-namespaced event type string (e.g. ``"inbound.message"``).

    Must be one of the constants on ``ET``.  Validated against ``EVENT_TYPES``
    by callers when strict checking is required.
    """

    source: EventSource
    """The component that emitted this event."""

    session_key: str
    """The session this event belongs to (e.g. ``"user:main"``)."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    """UTC timestamp of event creation."""

    payload: dict[str, Any] = Field(default_factory=dict)
    """Event-type-specific data.  Schema varies by ``event_type``."""

    # TD-217: Validate event_type at construction
    @model_validator(mode="after")
    def _check_event_type(self) -> "GatewayEvent":
        # Import lazily to avoid circular import (EVENT_TYPES defined below)
        if hasattr(self, "event_type") and EVENT_TYPES and self.event_type not in EVENT_TYPES:
            logger.warning("Unknown event_type: %r", self.event_type)
        return self


# ── Event type catalog ────────────────────────────────────────────────────────


class ET:
    """All valid event type strings (§2.2).

    Use these constants instead of raw strings everywhere in the codebase.
    """

    # Inbound
    INBOUND_MESSAGE: str = "inbound.message"
    """User/channel message received by the gateway."""

    # Agent run lifecycle
    AGENT_RUN_START: str = "agent.run.start"
    """Router triggers agent turn execution."""

    AGENT_RUN_STREAM: str = "agent.run.stream"
    """Streaming token/tool event from a running agent turn."""

    AGENT_RUN_COMPLETE: str = "agent.run.complete"
    """Agent turn finished successfully."""

    AGENT_RUN_ERROR: str = "agent.run.error"
    """Agent turn failed with an error."""

    # Delivery
    DELIVERY_SEND: str = "delivery.send"
    """Agent requests delivery to an outbound channel."""

    DELIVERY_RESULT: str = "delivery.result"
    """Channel adapter reports send success or failure."""

    # Session lifecycle
    SESSION_CREATED: str = "session.created"
    """New session opened."""

    SESSION_UPDATED: str = "session.updated"
    """Session state changed (status, summary, title, etc.)."""

    # UI
    UI_EVENT: str = "ui.event"
    """Frontend-specific event (typing indicator, status change, progress)."""

    # Plugin lifecycle
    PLUGIN_INSTALLED: str = "plugin.installed"
    """New plugin registered in the registry."""

    PLUGIN_ACTIVATED: str = "plugin.activated"
    """Plugin started successfully."""

    PLUGIN_ERROR: str = "plugin.error"
    """Plugin encountered a fatal error."""

    PLUGIN_DEACTIVATED: str = "plugin.deactivated"
    """Plugin stopped."""

    PLUGIN_HEALTH_CHANGED: str = "plugin.health_changed"
    """Plugin health-check result changed."""

    # Notifications
    NOTIFICATION_PUSH: str = "notification.push"
    """User-facing notification pushed to the frontend via the gateway."""

    # Multi-agent
    ESCALATION_TRIGGERED: str = "escalation.triggered"
    """Sub-agent escalation handoff initiated (§4.2a)."""

    # Tool approval (§11.2)
    APPROVAL_REQUEST: str = "approval.request"
    """Tool execution requires user approval — emitted before execution pauses."""

    APPROVAL_RESPONSE: str = "approval.response"
    """User decision on a pending approval request (approve / deny)."""

    # Budget / cost
    BUDGET_TURN_COST: str = "budget.turn_cost"
    """Per-turn LLM cost recorded (§23.2)."""

    BUDGET_WARNING: str = "budget.warning"
    """Spend reached warning threshold (§23.3)."""

    BUDGET_EXCEEDED: str = "budget.exceeded"
    """Spend reached cap limit (§23.3)."""

    # Provider circuit breaker
    PROVIDER_UNAVAILABLE: str = "provider.unavailable"
    """Provider circuit breaker opened (§19)."""

    # Transcription
    TRANSCRIPTION_COMPLETE: str = "transcription.complete"
    """Audio transcription pipeline finished (§22.1)."""

    # Scheduler
    SCHEDULER_SKIPPED: str = "scheduler.skipped"
    """Cron job was skipped due to contention (§20.8)."""

    # TD-262: Cancellation and timeout event types
    AGENT_RUN_CANCELLED: str = "agent.run.cancelled"
    """Agent turn was cancelled by user or system."""

    AGENT_RUN_TIMEOUT: str = "agent.run.timeout"
    """Agent turn exceeded maximum allowed execution time."""


# ── Validation set ────────────────────────────────────────────────────────────

EVENT_TYPES: frozenset[str] = frozenset(
    value
    for name, value in vars(ET).items()
    if not name.startswith("_") and isinstance(value, str)
)
"""All valid event type strings — use for runtime validation of ``event_type``."""
