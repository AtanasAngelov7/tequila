"""Pydantic models for sessions and messages (§3.2, §3.4).

Sprint 05 adds the full Message model: ContentBlock, ToolCallRecord,
MessageFeedback, branching (parent_id / active), provenance, costs, and
feedback fields.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.sessions.policy import SessionPolicy

# TD-375: Maximum allowed byte-size of JSON-serialised session metadata
_MAX_METADATA_BYTES = 65_536  # 64 KiB


# ── Session ───────────────────────────────────────────────────────────────────


class Session(BaseModel):
    """A single conversation session (§3.2).

    Fields mirror the ``sessions`` SQLite table column-for-column so that
    :func:`from_row` / :meth:`to_row` stay trivial.
    """

    # Identity
    session_id: str
    session_key: str

    # Classification
    kind: Literal["user", "agent", "channel", "cron", "webhook", "workflow"] = "user"
    agent_id: str = "main"
    channel: str = "webchat"

    # Policy & lifecycle
    policy: SessionPolicy = Field(default_factory=SessionPolicy)
    status: Literal["active", "idle", "archived"] = "active"
    parent_session_key: str | None = None

    # Display
    title: str | None = None
    summary: str | None = None

    # Stats
    message_count: int = 0
    last_message_at: datetime | None = None

    # Concurrency
    version: int = 1

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Extension
    metadata: dict[str, Any] = Field(default_factory=dict)

    # TD-375: Guard against runaway metadata blobs
    @model_validator(mode="after")
    def _check_metadata_size(self) -> "Session":
        raw = json.dumps(self.metadata, default=str)
        if len(raw.encode()) > _MAX_METADATA_BYTES:
            raise ValueError(
                f"Session.metadata exceeds maximum size "
                f"({len(raw.encode())} B > {_MAX_METADATA_BYTES} B)"
            )
        return self

    # ── Serialisation helpers ─────────────────────────────────────────────────

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Session":
        """Construct a Session from a raw ``aiosqlite`` row-as-dict."""
        data = dict(row)
        # Deserialise JSON columns
        if isinstance(data.get("policy"), str):
            data["policy"] = SessionPolicy(**json.loads(data["policy"]))
        if isinstance(data.get("metadata"), str):
            data["metadata"] = json.loads(data["metadata"])
        # Parse ISO datetime strings
        for key in ("created_at", "updated_at", "last_message_at"):
            if isinstance(data.get(key), str):
                data[key] = datetime.fromisoformat(data[key])
        return cls(**data)

    def to_row(self) -> dict[str, Any]:
        """Return a flat dict suitable for SQLite INSERT/UPDATE."""
        d = self.model_dump()
        # Serialise JSON columns
        d["policy"] = self.policy.model_dump_json()
        d["metadata"] = json.dumps(self.metadata)
        # Convert datetimes to ISO strings
        for key in ("created_at", "updated_at", "last_message_at"):
            v = d[key]
            if isinstance(v, datetime):
                d[key] = v.isoformat()
        return d


# ── Message sub-models (Sprint 05 — §3.4) ────────────────────────────────────


class ContentBlock(BaseModel):
    """Structured content block for multi-modal messages (§3.4)."""

    type: Literal["text", "image", "file_ref"]
    """Block type: plain text, image attachment, or file reference."""

    text: str | None = None
    """Text content for ``type='text'`` blocks."""

    file_id: str | None = None
    """File ID for ``type='image'`` or ``type='file_ref'`` blocks."""

    mime_type: str | None = None
    """MIME type hint for rendering (e.g. ``'image/png'``)."""

    alt_text: str | None = None
    """Image description (from vision pipeline or user)."""


class ToolCallRecord(BaseModel):
    """Record of a single tool invocation made by an assistant (§3.4, §4.6a)."""

    tool_call_id: str
    """Provider-assigned tool call ID for correlation."""

    tool_name: str
    """Registered tool name (e.g. ``'fs_read_file'``)."""

    arguments: dict[str, Any] = Field(default_factory=dict)
    """Parsed JSON arguments passed to the tool."""

    result: str | dict[str, Any] | None = None
    """Tool execution output (stringified for injection into prompt)."""

    success: bool | None = None
    """``True`` if the tool completed without error."""

    execution_time_ms: int | None = None
    """Wall-clock time the tool took to execute."""

    approval_status: Literal["auto_approved", "user_approved", "user_denied"] | None = None
    """How this tool call was authorised."""


class MessageFeedback(BaseModel):
    """User quality signal on an assistant message (§3.6)."""

    rating: Literal["up", "down"]
    """Thumbs up or thumbs down."""

    note: str | None = None
    """Optional free-text explanation (usually provided with 'down' ratings)."""

    created_at: datetime
    """When the feedback was submitted."""


# ── Message (full model — Sprint 05 §3.4) ─────────────────────────────────────


class Message(BaseModel):
    """A single message in a session (§3.4 — full Sprint 05 model).

    Fields mirror the ``messages`` SQLite table column-for-column so that
    :meth:`from_row` / :meth:`to_row` stay trivial.
    """

    id: str
    """Unique message UUID."""

    session_id: str
    """Session this message belongs to."""

    role: Literal["user", "assistant", "system", "tool_result", "tool"]
    """Sender role."""

    content: str = ""
    """Primary text content (markdown for assistant, plain for user)."""

    # ── Multi-modal ───────────────────────────────────────────────────────────

    content_blocks: list[ContentBlock] = Field(default_factory=list)
    """Structured content blocks (images, file refs) for multi-modal messages."""

    # ── Tool calls ────────────────────────────────────────────────────────────

    tool_calls: list[ToolCallRecord] | None = None
    """Tool invocations made by this assistant message."""

    tool_call_id: str | None = None
    """For ``role='tool_result'``: the tool call this responds to."""

    # ── File references ───────────────────────────────────────────────────────

    file_ids: list[str] = Field(default_factory=list)
    """Files attached to or generated by this message."""

    # ── Branching (§3.5) ──────────────────────────────────────────────────────

    parent_id: str | None = None
    """Previous message in the conversation thread."""

    active: bool = True
    """``False`` when this message is in an inactive branch (replaced by edit/regen)."""

    # ── Provenance ────────────────────────────────────────────────────────────

    provenance: Literal[
        "user_input",
        "assistant_response",
        "tool_result",
        "system_injected",
        "inter_session",
        "channel_inbound",
        "transcription",
        "file_context",
    ] = "user_input"
    """Where this message originated."""

    # ── Compression ───────────────────────────────────────────────────────────

    compressed: bool = False
    """``True`` if this message replaced a batch of older messages."""

    compressed_source_ids: list[str] = Field(default_factory=list)
    """Original message IDs compressed into this one."""

    # ── Cost tracking ─────────────────────────────────────────────────────────

    turn_cost_id: str | None = None
    """Reference to TurnCost record (assistant messages only)."""

    # ── Feedback (§3.6) ───────────────────────────────────────────────────────

    feedback: MessageFeedback | None = None
    """User quality rating (not a DB column — assembled from feedback_* columns)."""

    # ── LLM metadata ─────────────────────────────────────────────────────────

    model: str | None = None
    """Which model generated this (e.g. ``'anthropic:claude-sonnet-4-6'``)."""

    input_tokens: int | None = None
    """Input token count (assistant messages only)."""

    output_tokens: int | None = None
    """Output token count (assistant messages only)."""

    # ── Timestamps ────────────────────────────────────────────────────────────

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime | None = None

    # ── Serialisation helpers ─────────────────────────────────────────────────

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Message":
        """Construct a Message from a raw ``aiosqlite`` row-as-dict."""
        data = dict(row)

        # Parse ISO datetime strings
        for key in ("created_at", "updated_at", "feedback_at"):
            v = data.get(key)
            if isinstance(v, str):
                data[key] = datetime.fromisoformat(v)

        # Deserialise JSON columns
        for key in ("content_blocks", "file_ids", "compressed_source_ids"):
            v = data.get(key)
            if isinstance(v, str):
                data[key] = json.loads(v)
            elif v is None:
                data[key] = []

        # tool_calls: list of ToolCallRecord dicts
        tc_raw = data.get("tool_calls")
        if isinstance(tc_raw, str):
            data["tool_calls"] = json.loads(tc_raw)
        elif tc_raw is None:
            data["tool_calls"] = None

        # Assemble feedback from flat columns
        rating = data.pop("feedback_rating", None)
        note = data.pop("feedback_note", None)
        feedback_at = data.pop("feedback_at", None)
        if rating:
            data["feedback"] = MessageFeedback(
                rating=rating,
                note=note,
                created_at=feedback_at or datetime.now(timezone.utc),
            )
        else:
            data["feedback"] = None

        return cls(**data)

    def to_row(self) -> dict[str, Any]:
        """Return a flat dict suitable for SQLite INSERT/UPDATE."""
        d: dict[str, Any] = {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "content_blocks": json.dumps([cb.model_dump() for cb in self.content_blocks]),
            "tool_calls": json.dumps(
                [tc.model_dump() for tc in self.tool_calls]
            ) if self.tool_calls is not None else None,
            "tool_call_id": self.tool_call_id,
            "file_ids": json.dumps(self.file_ids),
            "parent_id": self.parent_id,
            "active": 1 if self.active else 0,
            "provenance": self.provenance,
            "compressed": 1 if self.compressed else 0,
            "compressed_source_ids": json.dumps(self.compressed_source_ids),
            "turn_cost_id": self.turn_cost_id,
            "feedback_rating": self.feedback.rating if self.feedback else None,
            "feedback_note": self.feedback.note if self.feedback else None,
            "feedback_at": self.feedback.created_at.isoformat() if self.feedback else None,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        return d
