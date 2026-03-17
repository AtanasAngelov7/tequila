"""Webhooks inbound channel plugin (Sprint 12, §8.6).

Provides an HTTP endpoint (``POST /api/webhooks/{endpoint_id}``) that
external services can POST to.  Optionally validates an HMAC-SHA256
signature, deduplicates payloads via the ``dedup_keys`` table, and
forwards the payload to an active session.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from app.plugins.base import PluginBase
from app.plugins.models import ChannelAdapterSpec, PluginAuth, PluginHealthResult, PluginTestResult

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class WebhooksPlugin(PluginBase):
    """Inbound webhook channel plugin."""

    plugin_id = "webhooks"
    name = "Webhooks"
    description = "Receive inbound HTTP webhooks from external services."
    version = "1.0.0"
    plugin_type = "connector"
    connector_type = "builtin"

    def __init__(self) -> None:
        self._db: aiosqlite.Connection | None = None
        self._active = False

    async def configure(self, config: dict[str, Any], auth_store: Any) -> None:
        """No per-endpoint credentials needed at configure time.

        Individual endpoints are managed via ``/api/webhooks/endpoints``.
        """
        self._config = config

    async def activate(self) -> None:
        self._active = True

    async def deactivate(self) -> None:
        self._active = False

    async def get_tools(self) -> list[Any]:
        return []

    async def get_channel_adapter(self) -> ChannelAdapterSpec:
        return ChannelAdapterSpec(
            channel_name="webhooks",
            supports_inbound=True,
            supports_outbound=False,
            polling_mode=False,
        )

    def get_auth_spec(self) -> PluginAuth:
        return PluginAuth(kind="none")

    def get_config_schema(self) -> dict[str, Any]:
        return {}

    async def health_check(self) -> PluginHealthResult:
        return PluginHealthResult(
            healthy=self._active,
            message="active" if self._active else "not activated",
        )

    async def test(self) -> PluginTestResult:
        return PluginTestResult(success=True, message="Webhooks plugin ready.")


# ── Standalone webhook endpoint helpers (used by the webhooks router) ─────────


async def validate_hmac_signature(
    payload_bytes: bytes,
    secret: str,
    signature_header: str,
) -> bool:
    """Verify ``X-Hub-Signature-256`` or ``sha256=<hex>`` style HMAC headers."""
    expected = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    # Strip algorithm prefix if present
    received = re.sub(r"^sha256=", "", signature_header)
    return hmac.compare_digest(expected, received)


async def check_dedup(
    db: aiosqlite.Connection,
    source: str,
    dedup_key: str,
) -> bool:
    """Return ``True`` if this ``(source, dedup_key)`` has NOT been seen before,
    and record it so subsequent calls return ``False``.
    """
    async with db.execute(
        "SELECT 1 FROM dedup_keys WHERE source = ? AND dedup_key = ?",
        (source, dedup_key),
    ) as cur:
        existing = await cur.fetchone()

    if existing:
        return False  # duplicate

    # Record it
    from app.db.connection import write_transaction

    async with write_transaction(db):
        await db.execute(
            "INSERT OR IGNORE INTO dedup_keys (source, dedup_key, created_at) VALUES (?, ?, ?)",
            (source, dedup_key, _now()),
        )
    return True


async def get_endpoint(
    db: aiosqlite.Connection,
    endpoint_id: str,
) -> dict[str, Any] | None:
    """Fetch a webhook endpoint record by its ``id``."""
    async with db.execute(
        "SELECT id, name, plugin_id, session_key, secret_hash, payload_path, active "
        "FROM webhook_endpoints WHERE id = ?",
        (endpoint_id,),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def list_endpoints(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    async with db.execute(
        "SELECT id, name, plugin_id, session_key, secret_hash, payload_path, active, "
        "created_at, updated_at FROM webhook_endpoints ORDER BY created_at DESC"
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def create_endpoint(
    db: aiosqlite.Connection,
    endpoint_id: str,
    name: str,
    session_key: str,
    secret: str | None = None,
    payload_path: str | None = None,
) -> dict[str, Any]:
    """Insert a new webhook endpoint row.  Hashes the secret before storing."""
    from app.db.connection import write_transaction

    secret_hash: str | None = None
    if secret:
        secret_hash = hashlib.sha256(secret.encode()).hexdigest()

    now = _now()
    async with write_transaction(db):
        await db.execute(
            """
            INSERT INTO webhook_endpoints
              (id, name, plugin_id, session_key, secret_hash, payload_path, active, created_at, updated_at)
            VALUES (?, ?, 'webhooks', ?, ?, ?, 1, ?, ?)
            """,
            (endpoint_id, name, session_key, secret_hash, payload_path, now, now),
        )
    return {
        "id": endpoint_id,
        "name": name,
        "session_key": session_key,
        "active": True,
        "created_at": now,
    }


async def delete_endpoint(db: aiosqlite.Connection, endpoint_id: str) -> bool:
    from app.db.connection import write_transaction

    async with write_transaction(db):
        cur = await db.execute(
            "DELETE FROM webhook_endpoints WHERE id = ?",
            (endpoint_id,),
        )
    return (cur.rowcount or 0) > 0
