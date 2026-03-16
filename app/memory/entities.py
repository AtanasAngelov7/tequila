"""Entity model for the memory system (§5.4, Sprint 09).

Entities are the first-class "things" referenced by memories —
people, organizations, projects, locations, tools, concepts, events, and dates.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Constants ─────────────────────────────────────────────────────────────────

ENTITY_TYPES = Literal[
    "person",
    "organization",
    "project",
    "location",
    "tool",
    "concept",
    "event",
    "date",
]

ENTITY_STATUSES = Literal["active", "merged", "deleted"]


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


# ── Entity ────────────────────────────────────────────────────────────────────


class Entity(BaseModel):
    """A named entity in the knowledge graph (§5.4)."""

    id: str
    """UUID assigned at creation."""

    name: str
    """Canonical display name for this entity."""

    entity_type: ENTITY_TYPES  # type: ignore[valid-type]
    """Semantic type of this entity."""

    aliases: list[str] = Field(default_factory=list)
    """Alternative names/spellings that resolve to this entity."""

    summary: str = ""
    """Auto-generated or user-written summary of this entity."""

    properties: dict[str, Any] = Field(default_factory=dict)
    """Flexible key-value metadata (email, role, URL, etc.)."""

    first_seen: datetime = Field(default_factory=_now)
    """UTC timestamp when this entity was first created."""

    last_referenced: datetime = Field(default_factory=_now)
    """UTC timestamp of the most recent memory referencing this entity."""

    reference_count: int = 0
    """Total number of memories linked to this entity."""

    status: ENTITY_STATUSES = "active"  # type: ignore[valid-type]
    """Lifecycle state."""

    merged_into: str | None = None
    """If ``status="merged"``, the ID of the surviving entity."""

    updated_at: datetime = Field(default_factory=_now)
    """UTC timestamp of the last update to this entity record."""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Entity":
        """Deserialise a DB row into an ``Entity``."""
        return cls(
            id=row["id"],
            name=row["name"],
            entity_type=row["entity_type"],
            aliases=json.loads(row.get("aliases", "[]")),
            summary=row.get("summary", ""),
            properties=json.loads(row.get("properties", "{}")),
            first_seen=_parse_dt(row.get("first_seen")),
            last_referenced=_parse_dt(row.get("last_referenced")),
            reference_count=int(row.get("reference_count", 0)),
            status=row.get("status", "active"),
            merged_into=row.get("merged_into"),
            updated_at=_parse_dt(row.get("updated_at")),
        )

    def matches(self, name: str) -> bool:
        """Return ``True`` if *name* matches this entity's canonical name or any alias."""
        target = name.strip().lower()
        if self.name.lower() == target:
            return True
        return any(a.lower() == target for a in self.aliases)


# ── Lightweight NER ───────────────────────────────────────────────────────────

# Common English words that look capitalised but aren't entities
_NER_STOPWORDS: frozenset[str] = frozenset({
    "The", "A", "An", "In", "On", "At", "To", "For", "Of", "And", "Or", "But",
    "I", "We", "They", "He", "She", "It", "You", "My", "Our", "Their", "His", "Her",
    "This", "That", "These", "Those", "Is", "Are", "Was", "Were", "Be", "Been",
    "Have", "Has", "Had", "Do", "Does", "Did", "Will", "Would", "Could", "Should",
    "May", "Might", "Must", "Shall", "Can",
    "Also", "Just", "Very", "Much", "Some", "Any", "All", "Both", "Each", "Few",
    "More", "Most", "Other", "Such", "Even", "Now", "Then", "So", "Because",
    "When", "Where", "While", "After", "Before", "Since", "Until", "Though",
    "Although", "If", "Unless", "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday", "January", "February", "March", "April",
    "May", "June", "July", "August", "September", "October", "November", "December",
    # Common conversational words that generate false positives (TD-84)
    "Yes", "No", "Ok", "Okay", "Sure", "Thanks", "Thank",
    "Hello", "Hi", "Hey", "Bye", "Sorry", "Please",
    "Today", "Tomorrow", "Yesterday", "Here", "There", "What", "Who", "How", "Why",
    "Well", "Right", "Like", "Know", "Think", "See", "Need", "Want", "Let",
})


def extract_entity_mentions(text: str) -> list[dict[str, str]]:
    """Extract potential entity mentions from *text* using regex heuristics.

    Returns a list of ``{"name": ..., "entity_type": ...}`` dicts.

    This is a lightweight fallback when spaCy is not available.  It identifies:
    - Multi-word proper nouns (1–4 consecutive title-cased or all-caps words).
    - Single capitalised words that are not common stopwords.
    """
    # Strip fenced code blocks to avoid false positives in code
    cleaned = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"`[^`]+`", "", cleaned)

    # Pattern: 1-4 consecutive capitalised words (allows hyphenated words)
    pattern = re.compile(
        r"\b(?:[A-Z][A-Za-z0-9'-]*(?:\s+[A-Z][A-Za-z0-9'-]*){0,3})\b"
    )
    matches = pattern.findall(cleaned)

    seen: set[str] = set()
    results: list[dict[str, str]] = []
    for m in matches:
        m = m.strip()
        if not m or m in _NER_STOPWORDS:
            continue
        # Skip pure numbers or very short tokens (TD-84: minimum 2 chars)
        if re.match(r"^\d+$", m) or len(m) < 2:
            continue
        if m not in seen:
            seen.add(m)
            # Heuristic type assignment (very simple)
            if re.search(r"\bInc\b|\bLtd\b|\bLLC\b|\bCorp\b|\bCo\b|\bGmbH\b", m):
                etype = "organization"
            elif re.search(r"\bProject\b|\bPlan\b|\bInitiative\b", m):
                etype = "project"
            elif re.search(r"\b(Dr|Mr|Mrs|Ms|Prof)\b", m):
                etype = "person"
            else:
                etype = "concept"
            results.append({"name": m, "entity_type": etype})

    return results
