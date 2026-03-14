"""Pydantic models for sessions and messages (§3.2, §3.4).

Sprint 02 implements the full Session model and a *stub* Message model
(id, session_id, role, content, created_at only).  The complete Message model
with tool_calls, branching, provenance, and feedback fields ships in Sprint 05.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.sessions.policy import SessionPolicy


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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Extension
    metadata: dict[str, Any] = Field(default_factory=dict)

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


# ── Message (stub — full model in Sprint 05) ──────────────────────────────────


class Message(BaseModel):
    """A single message in a session (§3.4 stub).

    Sprint 02 exposes only the fields required for basic echo-back chat.
    The complete model (tool_calls, provenance, branching, feedback, costs)
    is added in Sprint 05 when the agent turn loop is implemented.
    """

    id: str
    session_id: str
    role: Literal["user", "assistant", "system", "tool_result"]
    content: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Message":
        """Construct a Message from a raw ``aiosqlite`` row-as-dict."""
        data = dict(row)
        for key in ("created_at", "updated_at"):
            if isinstance(data.get(key), str):
                data[key] = datetime.fromisoformat(data[key])
        return cls(**data)

    def to_row(self) -> dict[str, Any]:
        """Return a flat dict suitable for SQLite INSERT."""
        d = self.model_dump()
        for key in ("created_at", "updated_at"):
            v = d[key]
            if isinstance(v, datetime):
                d[key] = v.isoformat()
        return d
