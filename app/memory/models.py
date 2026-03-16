"""Structured memory data model for Tequila v2 (§5.3, Sprint 09).

Provides:
- ``MemoryType``     — enum of all seven memory type literals.
- ``MemoryExtract``  — the primary memory record with type-specific fields,
                       provenance, decay, entity links, and OCC version.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ── Constants ─────────────────────────────────────────────────────────────────

MEMORY_TYPES = Literal[
    "identity",
    "preference",
    "fact",
    "experience",
    "task",
    "relationship",
    "skill",
]

SOURCE_TYPES = Literal[
    "extraction",
    "user_created",
    "agent_created",
    "promoted",
    "merged",
]

MEMORY_SCOPES = Literal["global", "agent", "session"]

MEMORY_STATUSES = Literal["active", "archived", "deleted"]

# Per-type default recall behaviour (§5.3 table)
_TYPE_DEFAULTS: dict[str, dict[str, Any]] = {
    "identity":     {"always_recall": True,  "recall_weight": 1.5},
    "preference":   {"always_recall": True,  "recall_weight": 1.2},
    "fact":         {"always_recall": False, "recall_weight": 1.0},
    "experience":   {"always_recall": False, "recall_weight": 1.1},
    "task":         {"always_recall": False, "recall_weight": 1.3},
    "relationship": {"always_recall": False, "recall_weight": 1.0},
    "skill":        {"always_recall": False, "recall_weight": 0.9},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(val: str | None) -> datetime:
    if not val:
        return _now()
    try:
        if val.endswith("Z"):
            val = val[:-1] + "+00:00"
        return datetime.fromisoformat(val)
    except ValueError:
        return _now()


# ── MemoryExtract ─────────────────────────────────────────────────────────────


class MemoryExtract(BaseModel):
    """A single structured memory record (§5.3).

    Supports all seven memory types with optional type-specific field validation.
    Includes provenance, temporal decay, entity links, and optimistic concurrency.
    """

    id: str
    """UUID assigned at creation."""

    content: str
    """The human-readable memory text."""

    memory_type: MEMORY_TYPES  # type: ignore[valid-type]
    """Semantic category of this memory."""

    # ── Recall behaviour ──────────────────────────────────────────────────────

    always_recall: bool = False
    """If ``True``, always included in the system prompt (used for identity/preference)."""

    recall_weight: float = 1.0
    """Boost factor applied during ranked recall (higher = more likely to surface)."""

    pinned: bool = False
    """User or agent manually pinned — always recalled in the current session."""

    # ── Temporal ──────────────────────────────────────────────────────────────

    created_at: datetime = Field(default_factory=_now)
    """UTC creation timestamp."""

    updated_at: datetime = Field(default_factory=_now)
    """UTC last-modified timestamp."""

    last_accessed: datetime = Field(default_factory=_now)
    """UTC timestamp of most recent read (used for decay scoring)."""

    access_count: int = 0
    """Number of times this memory has been recalled."""

    expires_at: datetime | None = None
    """Optional expiration time (e.g., task deadlines)."""

    decay_score: float = 1.0
    """Current relevance score in [0, 1].  Decays over time for applicable types."""

    # ── Provenance ────────────────────────────────────────────────────────────

    source_type: SOURCE_TYPES = "user_created"  # type: ignore[valid-type]
    """How this memory was created."""

    source_session_id: str | None = None
    """Session from which this memory was extracted (if applicable)."""

    source_message_id: str | None = None
    """Exact message from which this memory was extracted."""

    confidence: float = 1.0
    """Extraction model's confidence in this memory (0.0 – 1.0)."""

    # ── Entity links ──────────────────────────────────────────────────────────

    entity_ids: list[str] = Field(default_factory=list)
    """IDs of entities referenced by this memory."""

    tags: list[str] = Field(default_factory=list)
    """User-defined or auto-extracted tags."""

    # ── Scope ─────────────────────────────────────────────────────────────────

    scope: MEMORY_SCOPES = "global"  # type: ignore[valid-type]
    """Visibility scope for this memory."""

    agent_id: str | None = None
    """Owning agent (set when ``scope="agent"``)."""

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    status: MEMORY_STATUSES = "active"  # type: ignore[valid-type]
    """Active, archived, or soft-deleted."""

    version: int = 1
    """Optimistic concurrency control counter (§20.3b)."""

    # ── Validators ───────────────────────────────────────────────────────────

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    @field_validator("decay_score")
    @classmethod
    def _clamp_decay(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    @field_validator("recall_weight")
    @classmethod
    def _positive_weight(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("recall_weight must be positive")
        return v

    # ── Factory helpers ──────────────────────────────────────────────────────

    @classmethod
    def with_type_defaults(cls, **kwargs: Any) -> "MemoryExtract":
        """Create a ``MemoryExtract``, applying per-type default recall settings.

        Caller-supplied values override defaults.
        """
        memory_type = kwargs.get("memory_type", "fact")
        defaults = _TYPE_DEFAULTS.get(memory_type, {})
        for key, val in defaults.items():
            kwargs.setdefault(key, val)
        return cls(**kwargs)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "MemoryExtract":
        """Deserialise a DB row dict into a ``MemoryExtract``."""
        return cls(
            id=row["id"],
            content=row["content"],
            memory_type=row["memory_type"],
            always_recall=bool(row.get("always_recall", 0)),
            recall_weight=float(row.get("recall_weight", 1.0)),
            pinned=bool(row.get("pinned", 0)),
            created_at=_parse_dt(row.get("created_at")),
            updated_at=_parse_dt(row.get("updated_at")),
            last_accessed=_parse_dt(row.get("last_accessed")),
            access_count=int(row.get("access_count", 0)),
            expires_at=_parse_dt(row["expires_at"]) if row.get("expires_at") else None,
            decay_score=float(row.get("decay_score", 1.0)),
            source_type=row.get("source_type", "user_created"),
            source_session_id=row.get("source_session_id"),
            source_message_id=row.get("source_message_id"),
            confidence=float(row.get("confidence", 1.0)),
            entity_ids=json.loads(row.get("entity_ids", "[]")),
            tags=json.loads(row.get("tags", "[]")),
            scope=row.get("scope", "global"),
            agent_id=row.get("agent_id"),
            status=row.get("status", "active"),
            version=int(row.get("version", 1)),
        )
