"""Sprint 04 / Sprint 07 — Circuit breaker + graceful degradation (§4.6c, §19.3).

States:  closed → open → half-open → closed

``RetryPolicy``         — controls per-provider retry behaviour.
``CircuitBreaker``      — wraps any ``LLMProvider.stream_completion()`` call.
``GracefulDegradation`` — (Sprint 07) chains multiple providers as fallbacks.
``get_circuit_breaker`` — (Sprint 07) global per-provider registry.
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
        """Return ``True`` if the circuit is closed or ready for a probe.

        Reads mutable state that may be written under ``_lock`` — the
        method itself is synchronous but guards with a snapshot to avoid
        torn reads on CPython.
        """
        state = self._state
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.HALF_OPEN:
            return True
        # OPEN — check if reset timeout has elapsed
        last_fail = self._last_failure_time
        if last_fail and (time.monotonic() - last_fail) >= self.reset_timeout:
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

        # TD-271: Wrap iteration (not creation) of the async generator so
        # that errors during streaming are caught, recorded, and optionally
        # retried by the circuit breaker.
        async def _guarded_stream() -> AsyncIterator[Any]:
            attempt = 0
            while True:
                started = False
                try:
                    async for item in fn():
                        started = True  # at least one event yielded
                        yield item
                    await self.record_success()
                    return  # stream consumed successfully
                except Exception as exc:
                    await self.record_failure()
                    # TD-341: Never retry after streaming has started — events
                    # already yielded to the caller cannot be replayed, so
                    # a retry would send duplicate events.
                    if started or attempt >= self.retry_policy.max_retries:
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

        return _guarded_stream()

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


# ── GracefulDegradation (Sprint 07) ───────────────────────────────────────────


class GracefulDegradation:
    """Ordered fallback chain for provider resilience (§19.3).

    When the primary provider fails (circuit open, network error, etc.),
    ``GracefulDegradation`` transparently retries the request on the next
    provider in the chain.

    Usage::

        gd = GracefulDegradation(
            chain=[
                (anthropic_provider, "claude-sonnet-4-6"),
                (openai_provider,    "gpt-5.4"),
                (ollama_provider,    "llama3.1"),
            ]
        )
        stream = await gd.stream_completion(messages, tools=tools)
        async for event in stream:
            ...
    """

    def __init__(self, chain: list[tuple[Any, str]]) -> None:
        """
        Parameters
        ----------
        chain:
            Ordered list of ``(provider, model_id)`` pairs.  The first entry
            is the primary provider; subsequent entries are fallbacks.
        """
        if not chain:
            raise ValueError("GracefulDegradation chain must have at least one entry.")
        self.chain = chain

    async def stream_completion(
        self,
        messages: Any,
        tools: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Try each provider in the chain and return the first successful stream.

        Raises
        ------
        RuntimeError
            When every provider in the chain fails.
        """
        last_exc: Exception | None = None
        for provider, model_id in self.chain:
            cb = get_circuit_breaker(provider.provider_id)
            if not cb.is_available():
                logger.info(
                    "GracefulDegradation: skipping %r (circuit OPEN)", provider.provider_id
                )
                continue
            try:
                # TD-197/TD-272: Wrap iteration so fallback fires on streaming errors.
                stream = provider.stream_completion(
                    messages=messages,
                    model=model_id,
                    tools=tools or [],
                    **kwargs,
                )

                # Prefetch first event inside try block to catch immediate failures.
                aiter = stream.__aiter__()
                first_event = await aiter.__anext__()

                # Re-assemble: yield first event, then rest of stream.
                async def _chain(first: Any, rest: Any) -> AsyncIterator[Any]:
                    yield first
                    async for item in rest:
                        yield item

                return _chain(first_event, aiter)
            except StopAsyncIteration:
                # Empty stream from this provider — try next
                logger.warning(
                    "GracefulDegradation: provider %r returned empty stream, trying next",
                    provider.provider_id,
                )
                last_exc = RuntimeError(f"Empty stream from {provider.provider_id}")
                continue
            except Exception as exc:
                logger.warning(
                    "GracefulDegradation: provider %r failed (%s), trying next",
                    provider.provider_id,
                    exc,
                )
                await cb.record_failure()
                last_exc = exc

        raise RuntimeError(
            f"All providers in GracefulDegradation chain failed. "
            f"Last error: {last_exc}"
        )


# ── Circuit-breaker registry (Sprint 07) ─────────────────────────────────────

_circuit_registry: dict[str, CircuitBreaker] = {}


def remove_circuit_breaker(provider_id: str) -> None:
    """Remove the circuit breaker for *provider_id* (TD-289)."""
    _circuit_registry.pop(provider_id, None)


def get_circuit_breaker(
    provider_id: str,
    *,
    failure_threshold: int = 5,
    success_threshold: int = 2,
    reset_timeout: float = 30.0,
    retry_policy: RetryPolicy | None = None,
) -> CircuitBreaker:
    """Return (creating if necessary) the ``CircuitBreaker`` for *provider_id*.

    The same instance is reused across calls so that state (failure count,
    circuit state) persists for the lifetime of the process.

    Parameters
    ----------
    provider_id:
        Unique provider identifier (e.g. ``"anthropic"``).
    failure_threshold, success_threshold, reset_timeout, retry_policy:
        CircuitBreaker constructor arguments — only used when creating a new
        instance; ignored on cache hit.
    """
    if provider_id not in _circuit_registry:
        _circuit_registry[provider_id] = CircuitBreaker(
            provider_id=provider_id,
            failure_threshold=failure_threshold,
            success_threshold=success_threshold,
            reset_timeout=reset_timeout,
            retry_policy=retry_policy,
        )
    return _circuit_registry[provider_id]


def get_all_circuit_breakers() -> dict[str, CircuitBreaker]:
    """Return a copy of the current circuit-breaker registry."""
    return dict(_circuit_registry)



