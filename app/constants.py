"""App-wide string literals and numeric defaults for Tequila v2 (§2.1, §20.6, §28.4).

Zero imports from ``app/``. All values are plain Python literals so this module
loads without any transitive dependency chain.
"""
from __future__ import annotations

# ── Application identity ──────────────────────────────────────────────────────

APP_VERSION: str = "0.1.0"
"""Semantic version string returned by the health endpoint."""

APP_NAME: str = "Tequila"
"""Human-readable application name used in log headers and UI."""

# ── Database ──────────────────────────────────────────────────────────────────

DB_FILENAME: str = "tequila.db"
"""SQLite database filename inside ``data/``."""

# ── Server defaults ───────────────────────────────────────────────────────────

DEFAULT_HOST: str = "127.0.0.1"
"""Default server bind host (loopback — not exposed to the network by default)."""

DEFAULT_PORT: int = 8000
"""Default HTTP server port."""

# ── Gateway ───────────────────────────────────────────────────────────────────

GATEWAY_TOKEN_HEADER: str = "X-Gateway-Token"
"""HTTP header name that carries the gateway authentication token."""

# ── Turn / session limits ─────────────────────────────────────────────────────

MAX_BUFFERED_MESSAGES: int = 10
"""Maximum number of inbound messages held in the per-session turn queue (§20.6)."""

MAX_CONCURRENT_SUBAGENTS: int = 3
"""Maximum number of sub-agent sessions that may run concurrently (§20.7)."""

# ── OCC ───────────────────────────────────────────────────────────────────────

MAX_OCC_RETRIES: int = 3
"""Maximum optimistic-concurrency retry attempts before raising ConflictError (§20.3b)."""
