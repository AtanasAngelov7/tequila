"""Audit event persistence and query helpers for Tequila v2 (§12.1).

Every security-relevant action (auth, config change, tool execution, file
access) is recorded in the ``audit_log`` table as an ``AuditEvent``.
Writes use ``write_transaction`` from ``app.db.connection`` for serialisation.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite
from pydantic import BaseModel, Field

from app.db.connection import write_transaction

logger = logging.getLogger(__name__)

# ── Model ─────────────────────────────────────────────────────────────────────


class AuditEvent(BaseModel):
    """A single entry in the audit trail.

    Audit events are immutable once written — there is no update or delete
    operation on this table.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Primary-key UUID, auto-generated on creation."""

    actor: str
    """Who performed the action — a user ID, agent ID, or ``"system"``."""

    action: str
    """Dot-namespaced action string, e.g. ``"config.update"``, ``"tool.exec"``."""

    resource_type: str | None = None
    """Category of the affected resource, e.g. ``"session"``, ``"config"``."""

    resource_id: str | None = None
    """Specific ID of the affected resource (session_id, config key, etc.)."""

    outcome: str = "success"
    """Result of the action: ``"success"``, ``"failure"``, or ``"error"``."""

    detail: dict[str, Any] | None = None
    """Arbitrary JSON metadata about the action (tool name, error message, etc.)."""

    ip_address: str | None = None
    """Remote IP address of the client, if applicable."""

    session_key: str | None = None
    """Session context in which the action occurred, if applicable."""

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    """UTC timestamp of event creation."""


# ── Write ─────────────────────────────────────────────────────────────────────


async def write_audit_event(db: aiosqlite.Connection, event: AuditEvent) -> None:
    """Insert one ``AuditEvent`` row into the ``audit_log`` table.

    Uses ``write_transaction`` for serialisation (§20.2).
    """
    import json

    detail_json = json.dumps(event.detail) if event.detail is not None else None

    async with write_transaction(db):
        await db.execute(
            """
            INSERT INTO audit_log
                (id, actor, action, resource_type, resource_id, outcome,
                 detail, ip_address, session_key, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.actor,
                event.action,
                event.resource_type,
                event.resource_id,
                event.outcome,
                detail_json,
                event.ip_address,
                event.session_key,
                event.created_at.isoformat(),
            ),
        )
    logger.debug(
        "Audit event written",
        extra={"actor": event.actor, "action": event.action, "outcome": event.outcome},
    )


# ── Query ─────────────────────────────────────────────────────────────────────


async def query_audit_log(
    db: aiosqlite.Connection,
    *,
    actor: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
    session_key: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditEvent]:
    """Query the audit log with optional filters, newest first.

    Args:
        db: Read-only database connection.
        actor: Filter by actor identifier.
        action: Filter by (prefix of) action string.
        outcome: Filter by outcome (``"success"`` / ``"failure"`` / ``"error"``).
        session_key: Filter by session key.
        since: Only return events on or after this UTC datetime.
        limit: Maximum number of rows to return.
        offset: Pagination offset.

    Returns:
        List of ``AuditEvent`` objects ordered by ``created_at DESC``.
    """
    import json

    clauses: list[str] = []
    params: list[Any] = []

    if actor:
        clauses.append("actor = ?")
        params.append(actor)
    if action:
        clauses.append("action LIKE ?")
        params.append(f"{action}%")
    if outcome:
        clauses.append("outcome = ?")
        params.append(outcome)
    if session_key:
        clauses.append("session_key = ?")
        params.append(session_key)
    if since:
        clauses.append("created_at >= ?")
        params.append(since.isoformat())

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([limit, offset])

    cursor = await db.execute(
        f"""
        SELECT id, actor, action, resource_type, resource_id, outcome,
               detail, ip_address, session_key, created_at
        FROM   audit_log
        {where}
        ORDER  BY created_at DESC
        LIMIT  ? OFFSET ?
        """,
        params,
    )
    rows = await cursor.fetchall()
    events = []
    for row in rows:
        d = dict(row)
        if d.get("detail"):
            try:
                d["detail"] = json.loads(d["detail"])
            except Exception:
                d["detail"] = {"raw": d["detail"]}
        if d.get("created_at"):
            d["created_at"] = datetime.fromisoformat(d["created_at"])
        events.append(AuditEvent.model_validate(d))
    return events
