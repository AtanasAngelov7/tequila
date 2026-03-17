"""Pydantic models for the Tequila v2 scheduler (§7.1–§7.2).

``ScheduledTask`` represents a cron-based agent run definition stored in
the ``scheduled_tasks`` table.  The scheduler engine (engine.py) fires
these tasks on their cron schedule using a lightweight asyncio-based loop.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ScheduledTask(BaseModel):
    """A cron-driven agent session definition."""

    id: str = Field(..., description="Unique task UUID.")
    name: str = Field(..., description="Human-readable task name.")
    description: str = Field(default="", description="Optional description of what this task does.")
    cron_expression: str = Field(
        ...,
        description=(
            "Standard 5-field cron expression (minute hour dom month dow). "
            "Examples: '0 9 * * 1-5' (weekdays 9 AM), '*/30 * * * *' (every 30 min)."
        ),
    )
    agent_id: str = Field(..., description="ID of the agent that will run the session.")
    prompt_template: str = Field(
        default="",
        description=(
            "Prompt injected as the first user message when the session fires. "
            "Supports {now}, {date}, {time} substitutions."
        ),
    )
    enabled: bool = Field(default=True, description="Whether this task is active.")
    announce: bool = Field(
        default=False,
        description="If True, results are surfaced as a notification to the user.",
    )
    last_run_at: datetime | None = Field(default=None, description="Timestamp of last execution.")
    last_run_status: Literal["success", "error", "skipped"] | None = Field(
        default=None, description="Outcome of the last execution."
    )
    last_run_error: str | None = Field(default=None, description="Error message from last run (if any).")
    next_run_at: datetime | None = Field(default=None, description="Computed next fire time.")
    run_count: int = Field(default=0, description="Total successful executions.")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CreateTaskRequest(BaseModel):
    """Request body for POST /api/scheduled-tasks."""

    name: str = Field(..., description="Human-readable task name.")
    description: str = Field(default="")
    cron_expression: str = Field(..., description="Standard 5-field cron expression.")
    agent_id: str = Field(..., description="Agent to run.")
    prompt_template: str = Field(default="", description="Opening user prompt.")
    enabled: bool = Field(default=True)
    announce: bool = Field(default=False)


class UpdateTaskRequest(BaseModel):
    """Request body for PATCH /api/scheduled-tasks/{id}."""

    name: str | None = None
    description: str | None = None
    cron_expression: str | None = None
    agent_id: str | None = None
    prompt_template: str | None = None
    enabled: bool | None = None
    announce: bool | None = None


class RunNowRequest(BaseModel):
    """Request body for POST /api/scheduled-tasks/{id}/run."""

    override_prompt: str | None = Field(
        default=None, description="Override the prompt_template for this single run."
    )
