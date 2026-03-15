"""Domain exception hierarchy for Tequila v2 (§2.3, §3.7, §28).

All feature code raises subclasses of ``TequilaError``. FastAPI exception handlers
in ``app.api.app`` convert each subclass to the appropriate HTTP response, so route
handlers should *never* catch these exceptions themselves — let them propagate.
"""
from __future__ import annotations

# ── Base ─────────────────────────────────────────────────────────────────────


class TequilaError(Exception):
    """Base class for all Tequila domain exceptions.

    HTTP equivalent: 500 Internal Server Error (unless overridden by a subclass).
    """

    http_status: int = 500
    """Default HTTP status code for this exception type."""

    def __init__(self, message: str = "An unexpected error occurred.") -> None:
        super().__init__(message)
        self.message = message

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.message!r})"


# ── Generic HTTP-mapped errors ────────────────────────────────────────────────


class NotFoundError(TequilaError):
    """A requested resource does not exist in the database.

    HTTP equivalent: 404 Not Found.
    """

    http_status = 404

    def __init__(self, resource: str = "Resource", id: str | None = None) -> None:
        msg = f"{resource} not found" if id is None else f"{resource} '{id}' not found"
        super().__init__(msg)


class ConflictError(TequilaError):
    """Duplicate key or optimistic-concurrency version mismatch.

    HTTP equivalent: 409 Conflict.
    Raised when an INSERT would create a duplicate, or when an OCC update finds
    ``changes() == 0`` after max retries (§20.3b).
    """

    http_status = 409


class AccessDeniedError(TequilaError):
    """Authentication or scope check failed.

    HTTP equivalent: 403 Forbidden.
    """

    http_status = 403


class ValidationError(TequilaError):
    """Domain-level validation failure (not a Pydantic schema error).

    HTTP equivalent: 422 Unprocessable Entity.
    Use when business-rule validation fails after Pydantic has already parsed the input.
    """

    http_status = 422


# ── Config errors ─────────────────────────────────────────────────────────────


class ConfigKeyNotFoundError(NotFoundError):
    """``ConfigStore.get()`` — key absent and no default was provided.

    HTTP equivalent: 404 Not Found.
    """

    def __init__(self, key: str) -> None:
        super().__init__(resource="Config key", id=key)


class ConfigValidationError(ValidationError):
    """A config value fails its type or range check.

    HTTP equivalent: 422 Unprocessable Entity.
    """

    def __init__(self, key: str, reason: str) -> None:
        super().__init__(f"Config key '{key}' validation failed: {reason}")


# ── Gateway / auth errors ─────────────────────────────────────────────────────


class GatewayTokenRequired(TequilaError):
    """The ``X-Gateway-Token`` header is missing or incorrect.

    HTTP equivalent: 401 Unauthorized.
    """

    http_status = 401

    def __init__(self) -> None:
        super().__init__("Gateway token required.")


# ── Session errors ────────────────────────────────────────────────────────────


class SessionBusyError(TequilaError):
    """The session's turn queue is full — cannot accept another message right now.

    HTTP equivalent: 429 Too Many Requests.
    """

    http_status = 429

    def __init__(self, session_key: str) -> None:
        super().__init__(f"Session '{session_key}' is busy; turn queue is full.")


class SessionNotFoundError(NotFoundError):
    """The requested session key does not exist in the database.

    HTTP equivalent: 404 Not Found.
    """

    def __init__(self, session_key: str) -> None:
        super().__init__(resource="Session", id=session_key)


# ── Agent errors ─────────────────────────────────────────────


class AgentNotFoundError(NotFoundError):
    """The requested agent ID does not exist in the database.

    HTTP equivalent: 404 Not Found.
    """

    def __init__(self, agent_id: str) -> None:
        super().__init__(resource="Agent", id=agent_id)


# ── Database errors ───────────────────────────────────────────────────────────


class DatabaseError(TequilaError):
    """Low-level database operation failed in an unrecoverable way.

    HTTP equivalent: 500 Internal Server Error.
    """
