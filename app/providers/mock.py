"""Mock LLM provider for testing (Sprint 05).

``MockProvider`` replays a pre-scripted sequence of responses without making
any network calls.  It is used in integration tests for the turn loop,
approval flow, and branching.

Script format
-------------
The ``script`` is a list of "turns" — each turn is a list of events to emit
for one ``stream_completion`` call.  Events within a turn are:

``{"text": "..."}``
    Emits a ``text_delta`` event for each character, then ``done``.

``{"tool_call": {"name": "tool_name", "arguments": {...}}}``
    Emits ``tool_call_start``, ``tool_call_end``, then continues to the
    next event in the same turn (or emits ``done``).

``{"error": "message"}``
    Emits an ``error`` event.

``{"usage": {"input_tokens": N, "output_tokens": M}}``
    Emits a ``usage`` event before ``done``.

Example::

    script = [
        # Turn 1: text response
        [{"text": "Hello, world!"}],
        # Turn 2: tool call, then text
        [
            {"tool_call": {"name": "get_weather", "arguments": {"city": "London"}}},
            {"text": "The weather in London is sunny."},
        ],
    ]
    provider = MockProvider(script=script)

If the script is exhausted, subsequent calls raise ``RuntimeError``.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, AsyncIterator

from app.providers.base import (
    LLMProvider,
    Message,
    ModelCapabilities,
    ModelInfo,
    ProviderStreamEvent,
    ResponseFormat,
    ToolDef,
)


class MockProvider(LLMProvider):
    """Scripted test provider — replays a fixed sequence of stream events.

    Parameters
    ----------
    script:
        List of turns; each turn is a list of event dicts.  See module
        docstring for the supported formats.
    model_id:
        Model identifier reported by ``list_models()``.
    token_multiplier:
        Multiplier applied to word-count for ``count_tokens``.  Default 2.
    delay:
        Simulated per-token delay in seconds (default 0 = instant).
    """

    provider_id = "mock"

    def __init__(
        self,
        script: list[list[dict[str, Any]]] | None = None,
        model_id: str = "mock-v1",
        token_multiplier: float = 2.0,
        delay: float = 0.0,
    ) -> None:
        self._script = list(script or [])
        self._call_index = 0
        self._model_id = model_id
        self._token_multiplier = token_multiplier
        self._delay = delay

    # ── LLMProvider interface ─────────────────────────────────────────────────

    async def stream_completion(
        self,
        messages: list[Message],
        model: str,
        tools: list[ToolDef] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        response_format: ResponseFormat | None = None,
    ) -> AsyncIterator[ProviderStreamEvent]:
        if self._call_index >= len(self._script):
            raise RuntimeError(
                f"MockProvider: script exhausted after {self._call_index} calls "
                f"(script has {len(self._script)} turns)"
            )

        turn_events = self._script[self._call_index]
        self._call_index += 1

        async def _generate() -> AsyncIterator[ProviderStreamEvent]:
            input_tokens = self._count_messages(messages)
            output_tokens = 0

            for event_spec in turn_events:
                if "text" in event_spec:
                    text: str = event_spec["text"]
                    for char in text:
                        if self._delay:
                            await asyncio.sleep(self._delay)
                        yield ProviderStreamEvent(kind="text_delta", text=char)
                    output_tokens += max(1, int(len(text.split()) * self._token_multiplier))

                elif "tool_call" in event_spec:
                    tc = event_spec["tool_call"]
                    tool_call_id = event_spec.get("tool_call_id", str(uuid.uuid4()))
                    tool_name: str = tc["name"]
                    args: dict[str, Any] = tc.get("arguments", {})
                    args_json = json.dumps(args)

                    yield ProviderStreamEvent(
                        kind="tool_call_start",
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                    )
                    # Emit args as one delta
                    yield ProviderStreamEvent(
                        kind="tool_call_delta",
                        tool_call_id=tool_call_id,
                        tool_args_delta=args_json,
                    )
                    yield ProviderStreamEvent(
                        kind="tool_call_end",
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        tool_args=args,
                    )
                    output_tokens += max(1, int(len(args_json.split()) * self._token_multiplier))

                elif "error" in event_spec:
                    yield ProviderStreamEvent(
                        kind="error",
                        error_message=event_spec["error"],
                        error_code=event_spec.get("error_code", "mock_error"),
                    )

                elif "usage" in event_spec:
                    u = event_spec["usage"]
                    yield ProviderStreamEvent(
                        kind="usage",
                        input_tokens=u.get("input_tokens", input_tokens),
                        output_tokens=u.get("output_tokens", output_tokens),
                    )

            # Always emit usage + done at end of turn
            yield ProviderStreamEvent(
                kind="usage",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            yield ProviderStreamEvent(kind="done")

        return _generate()

    async def count_tokens(self, messages: list[Message], model: str) -> int:
        return self._count_messages(messages)

    async def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(
                id=f"mock:{self._model_id}",
                name=f"Mock Model ({self._model_id})",
                provider_id="mock",
                capabilities=ModelCapabilities(
                    model_id=self._model_id,
                    provider_id="mock",
                    display_name=f"Mock ({self._model_id})",
                    supports_tools=True,
                    supports_streaming=True,
                    context_window=128_000,
                    max_output_tokens=4_096,
                ),
            )
        ]

    def get_model_capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(
            model_id=model,
            provider_id="mock",
            display_name=f"Mock ({model})",
            supports_tools=True,
            supports_streaming=True,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _count_messages(self, messages: list[Message]) -> int:
        total = 0
        for m in messages:
            content = m.content if isinstance(m.content, str) else str(m.content)
            total += max(1, int(len(content.split()) * self._token_multiplier))
        return total

    # ── Test helpers ──────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Reset the call index — reuse the same script."""
        self._call_index = 0

    @property
    def calls_made(self) -> int:
        """How many ``stream_completion`` calls were made."""
        return self._call_index

    @property
    def script_exhausted(self) -> bool:
        """True if all script turns have been consumed."""
        return self._call_index >= len(self._script)
