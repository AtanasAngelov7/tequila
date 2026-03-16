"""Workflow data models for Tequila v2 (§10.1–10.3, Sprint 08).

Provides:
- ``WorkflowStep``  — one step in a workflow definition (agent + prompt).
- ``Workflow``      — reusable workflow definition with one or more steps.
- ``WorkflowRun``   — a single execution instance of a workflow.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── WorkflowStep ──────────────────────────────────────────────────────────────


class WorkflowStep(BaseModel):
    """One step in a workflow definition."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    """Short unique identifier for this step within the workflow."""

    agent_id: str
    """ID of the agent that executes this step (must exist in the agent store)."""

    prompt_template: str
    """Prompt sent to the agent.  Use ``{context}`` to inject the previous step's output."""

    timeout_s: int = 60
    """Maximum seconds to wait for the agent to complete this step."""

    retry: int = 0
    """Number of times to retry on failure before propagating the error."""


# ── Workflow ──────────────────────────────────────────────────────────────────


class Workflow(BaseModel):
    """Reusable workflow definition (§10.1, §10.2)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """UUID assigned at creation time."""

    name: str
    """Human-readable workflow name."""

    description: str = ""
    """Optional description shown in the UI."""

    mode: Literal["pipeline", "parallel"] = "pipeline"
    """Execution mode: ``pipeline`` = sequential, ``parallel`` = fan-out."""

    steps: list[WorkflowStep] = Field(default_factory=list)
    """Ordered list of steps.  In pipeline mode the order determines execution order."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    """UTC creation time."""

    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    """UTC last-modified time."""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Workflow":
        """Deserialise a DB row (with JSON-encoded steps) into a Workflow."""
        import json
        steps_data = json.loads(row.get("steps_json", "[]"))
        steps = [WorkflowStep(**s) for s in steps_data]
        return cls(
            id=row["id"],
            name=row["name"],
            description=row.get("description", ""),
            mode=row.get("mode", "pipeline"),
            steps=steps,
            created_at=_parse_dt(row.get("created_at")),
            updated_at=_parse_dt(row.get("updated_at")),
        )


# ── WorkflowRun ───────────────────────────────────────────────────────────────


class WorkflowRun(BaseModel):
    """One execution instance of a workflow (§10.3)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """UUID assigned when the run is created."""

    workflow_id: str
    """ID of the parent workflow definition."""

    status: Literal["pending", "running", "completed", "failed", "cancelled"] = "pending"
    """Lifecycle state of this run."""

    step_results: dict[str, str] = Field(default_factory=dict)
    """Mapping of step_id → result text collected so far."""

    current_step: str | None = None
    """ID of the step currently executing (None when not running)."""

    error: str | None = None
    """Error message if the run or a step failed."""

    started_at: datetime | None = None
    """When the run transitioned from pending → running."""

    completed_at: datetime | None = None
    """When the run reached a terminal state."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    """UTC creation time."""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "WorkflowRun":
        """Deserialise a DB row (with JSON-encoded step_results) into a WorkflowRun."""
        import json
        return cls(
            id=row["id"],
            workflow_id=row["workflow_id"],
            status=row.get("status", "pending"),
            step_results=json.loads(row.get("step_results_json", "{}")),
            current_step=row.get("current_step"),
            error=row.get("error"),
            started_at=_parse_dt(row.get("started_at")),
            completed_at=_parse_dt(row.get("completed_at")),
            created_at=_parse_dt(row.get("created_at")),
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO-8601 string from SQLite into a datetime, or return None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
