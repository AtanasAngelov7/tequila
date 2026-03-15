"""Sprint 04 — Circuit breaker for provider resilience (§4.6c).

States:  closed → open → half-open → closed

``RetryPolicy`` controls per-provider retry behaviour.
``CircuitBreaker`` wraps any ``LLMProvider.stream_completion()`` call.
"""
from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Any, AsyncIterator, Callable

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"
    """Normal operation — requests pass through."""

    OPEN = "open"
    """Failing — requests are rejected immediately."""

    HALF_OPEN = "half_open"
    """Testing recovery — one probe request is allowed through."""


class RetryPolicy(BaseModel):
    """Retry configuration for a provider or model."""

    max_retries: int = 3
    """Maximum retry attempts before raising."""

    base_delay: float = 1.0
    """Initial backoff delay in seconds."""

    backoff_factor: float = 2.0
    """Multiplicative factor applied to *base_delay* after each attempt."""

    max_delay: float = 30.0
    """Upper-bound on backoff delay in seconds."""

    retry_on_status_codes: list[int] = [429, 500, 502, 503, 504]
    """HTTP status codes that trigger a retry."""

    retry_on_error_codes: list[str] = ["rate_limit", "overloaded", "server_error"]
    """Provider error codes that trigger a retry."""

    def delay_for(self, attempt: int) -> float:
        """Return the delay (seconds) for *attempt* (0-indexed)."""
        d = self.base_delay * (self.backoff_factor ** attempt)
        return min(d, self.max_delay)


class CircuitBreaker:
    """Implements the three-state circuit breaker pattern.

    Usage::

        cb = CircuitBreaker(provider_id="anthropic")
        async for event in cb.stream_completion(provider, messages, model):
            ...
    """

    def __init__(
        self,
        provider_id: str,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        reset_timeout: float = 30.0,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.failure_threshold = failure_threshold
        """Consecutive failures needed to open the circuit."""

        self.success_threshold = success_threshold
        """Consecutive successes in HALF_OPEN needed to close the circuit."""

        self.reset_timeout = reset_timeout
        """Seconds to wait in OPEN state before transitioning to HALF_OPEN."""

        self.retry_policy: RetryPolicy = retry_policy or RetryPolicy()

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    def is_available(self) -> bool:
        """Return ``True`` if the circuit is closed or ready for a probe."""
        if self._state == CircuitState.CLOSED:
            return True
        if self._state == CircuitState.HALF_OPEN:
            return True
        # OPEN — check if reset timeout has elapsed
        if self._last_failure_time and (time.monotonic() - self._last_failure_time) >= self.reset_timeout:
            return True
        return False

    async def _transition_to(self, state: CircuitState) -> None:
        async with self._lock:
            if self._state != state:
                logger.info(
                    "Circuit breaker [%s]: %s → %s",
                    self.provider_id,
                    self._state.value,
                    state.value,
                )
                self._state = state

    async def record_success(self) -> None:
        """Call after a successful completion event stream."""
        async with self._lock:
            self._failure_count = 0
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    logger.info(
                        "Circuit breaker [%s]: HALF_OPEN → CLOSED (recovered)",
                        self.provider_id,
                    )
                    self._state = CircuitState.CLOSED
                    self._success_count = 0
            else:
                self._success_count = 0

    async def record_failure(self) -> None:
        """Call after a failed completion attempt."""
        async with self._lock:
            self._failure_count += 1
            self._success_count = 0
            self._last_failure_time = time.monotonic()
            if self._state == CircuitState.HALF_OPEN:
                logger.warning(
                    "Circuit breaker [%s]: HALF_OPEN → OPEN (probe failed)",
                    self.provider_id,
                )
                self._state = CircuitState.OPEN
            elif self._state == CircuitState.CLOSED and self._failure_count >= self.failure_threshold:
                logger.warning(
                    "Circuit breaker [%s]: CLOSED → OPEN (failure threshold=%d reached)",
                    self.provider_id,
                    self.failure_threshold,
                )
                self._state = CircuitState.OPEN

    async def _maybe_transition_open_to_half_open(self) -> None:
        async with self._lock:
            if (
                self._state == CircuitState.OPEN
                and self._last_failure_time is not None
                and (time.monotonic() - self._last_failure_time) >= self.reset_timeout
            ):
                logger.info(
                    "Circuit breaker [%s]: OPEN → HALF_OPEN (timeout elapsed)",
                    self.provider_id,
                )
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0

    async def call(
        self,
        fn: Callable[[], AsyncIterator[Any]],
    ) -> AsyncIterator[Any]:
        """Wrap an async-generator factory *fn* with circuit-breaker logic.

        Transparently re-raises ``CircuitOpenError`` when the circuit is open
        and the reset timeout has not elapsed.

        Example::

            async for event in cb.call(lambda: provider.stream_completion(...)):
                yield event
        """
        await self._maybe_transition_open_to_half_open()

        if self._state == CircuitState.OPEN:
            raise CircuitOpenError(
                f"Circuit breaker [provider={self.provider_id}] is OPEN — "
                "provider unavailable. Wait and retry later."
            )

        attempt = 0
        while True:
            try:
                items: list[Any] = []
                async for item in fn():
                    items.append(item)
                await self.record_success()
                return self._iter_list(items)
            except Exception as exc:
                await self.record_failure()
                if attempt >= self.retry_policy.max_retries:
                    raise
                delay = self.retry_policy.delay_for(attempt)
                logger.warning(
                    "Circuit breaker [%s]: attempt %d failed (%s), retrying in %.1fs",
                    self.provider_id,
                    attempt,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                attempt += 1

    @staticmethod
    async def _iter_list(items: list[Any]) -> AsyncIterator[Any]:
        for item in items:
            yield item

    # ── State snapshot ────────────────────────────────────────────────────────

    def status_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable status snapshot."""
        return {
            "provider_id": self.provider_id,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure_time": self._last_failure_time,
        }


class CircuitOpenError(RuntimeError):
    """Raised when a request is rejected because the circuit is OPEN."""
