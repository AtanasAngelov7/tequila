"""Sprint 10 — Knowledge Source data models (§5.14)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class QueryMode(str, Enum):
    """How the source receives the query — raw text or pre-embedded vector."""

    text = "text"
    vector = "vector"


class KnowledgeSource(BaseModel):
    """Persisted configuration for an external knowledge source."""

    source_id: str = Field(..., description="Unique identifier, e.g. 'legal_docs'")
    name: str = Field(..., description="Human-readable display name")
    description: str = Field(default="", description="What this source contains")
    backend: Literal["chroma", "pgvector", "faiss", "http"]
    query_mode: QueryMode = QueryMode.text
    embedding_provider: str | None = None
    """Required when query_mode=vector; references an EmbeddingProvider id."""

    auto_recall: bool = False
    """If True, queried automatically every turn via recall pipeline."""

    priority: int = 100
    """Lower number = higher priority for budget allocation."""

    max_results: int = 5
    similarity_threshold: float = 0.6
    connection: dict[str, Any] = Field(default_factory=dict)
    """Backend-specific connection config."""

    allowed_agents: list[str] | None = None
    """None = all agents; list = only these agent_ids."""

    status: Literal["active", "error", "disabled"] = "disabled"
    error_message: str | None = None
    consecutive_failures: int = 0
    last_health_check: datetime | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_row(cls, row: Any) -> "KnowledgeSource":
        """Deserialise an aiosqlite Row or mapping."""

        def _dt(v: str | None) -> datetime | None:
            if not v:
                return None
            if isinstance(v, datetime):
                return v
            return datetime.fromisoformat(v) if "+" in v or "T" in v else datetime.fromisoformat(v + "+00:00")

        def _dt_required(v: str | None) -> datetime:
            if not v:
                return datetime.now(timezone.utc)
            result = _dt(v)
            return result if result is not None else datetime.now(timezone.utc)

        return cls(
            source_id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            backend=row["backend"],
            query_mode=QueryMode(row["query_mode"]),
            embedding_provider=row["embedding_provider"],
            auto_recall=bool(row["auto_recall"]),
            priority=row["priority"],
            max_results=row["max_results"],
            similarity_threshold=row["similarity_threshold"],
            connection=json.loads(row["connection_json"] or "{}"),
            allowed_agents=json.loads(row["allowed_agents_json"]) if row["allowed_agents_json"] else None,
            status=row["status"],
            error_message=row["error_message"],
            consecutive_failures=row["consecutive_failures"],
            last_health_check=_dt(row["last_health_check"]),
            created_at=_dt_required(row["created_at"]),
            updated_at=_dt_required(row["updated_at"]),
        )


class KnowledgeChunk(BaseModel):
    """A single retrieved text chunk from a knowledge source."""

    source_id: str = Field(..., description="Which knowledge source produced this chunk")
    content: str = Field(..., description="The retrieved text")
    score: float = Field(..., description="Relevance score (0–1, normalised)")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("score")
    @classmethod
    def _clamp_score(cls, v: float) -> float:
        return max(0.0, min(1.0, v))
