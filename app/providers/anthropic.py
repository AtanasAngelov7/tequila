"""Sprint 04 — Anthropic provider adapter (§4.6).

Streams completions via the official ``anthropic`` Python SDK.  Converts
the unified ``ToolDef`` / ``Message`` types to Anthropic's wire format and
maps Anthropic's SSE stream back to ``ProviderStreamEvent``.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, AsyncIterator

from app.providers.base import (
    CostRate,
    LLMProvider,
    Message,
    ModelCapabilities,
    ModelInfo,
    ProviderStreamEvent,
    ResponseFormat,
    ToolDef,
)

logger = logging.getLogger(__name__)


# ── Per-model capability registry ─────────────────────────────────────────────

_ANTHROPIC_MODELS: dict[str, ModelCapabilities] = {
    "claude-opus-4-5": ModelCapabilities(
        model_id="claude-opus-4-5",
        provider_id="anthropic",
        display_name="Claude Opus 4.5 (powerful)",
        context_window=200_000,
        max_output_tokens=16_000,
        supports_tools=True,
        supports_vision=True,
        supports_structured_output=True,
        supports_streaming=True,
        supports_thinking=True,
        input_cost_per_1k=0.015,
        output_cost_per_1k=0.075,
    ),
    "claude-sonnet-4-5": ModelCapabilities(
        model_id="claude-sonnet-4-5",
        provider_id="anthropic",
        display_name="Claude Sonnet 4.5 (balanced)",
        context_window=200_000,
        max_output_tokens=8_192,
        supports_tools=True,
        supports_vision=True,
        supports_structured_output=True,
        supports_streaming=True,
        supports_thinking=False,
        input_cost_per_1k=0.003,
        output_cost_per_1k=0.015,
    ),
    "claude-haiku-4-5": ModelCapabilities(
        model_id="claude-haiku-4-5",
        provider_id="anthropic",
        display_name="Claude Haiku 4.5 (fast)",
        context_window=200_000,
        max_output_tokens=4_096,
        supports_tools=True,
        supports_vision=True,
        supports_structured_output=True,
        supports_streaming=True,
        supports_thinking=False,
        input_cost_per_1k=0.00025,
        output_cost_per_1k=0.00125,
    ),
}


def _tool_to_anthropic(tool: ToolDef) -> dict[str, Any]:
    """Convert unified ``ToolDef`` → Anthropic tool dict."""
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.parameters,
    }


def _messages_to_anthropic(
    messages: list[Message],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Split system message out and convert remaining messages.

    Anthropic takes ``system`` as a top-level parameter, not a message.
    Returns ``(system_text | None, anthropic_messages)``.
    """
    system: str | None = None
    out: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "system":
            system = msg.content if isinstance(msg.content, str) else str(msg.content)
        elif msg.role == "tool":
            # Tool result message — attach to the preceding assistant turn or
            # wrap in a user message as a tool_result content block
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.tool_call_id or "",
                            "content": (
                                msg.content
                                if isinstance(msg.content, str)
                                else str(msg.content)
                            ),
                        }
                    ],
                }
            )
        elif msg.role == "assistant" and msg.tool_calls:
            # Assistant message with pending tool calls
            content: list[dict[str, Any]] = []
            if msg.content:
                text = msg.content if isinstance(msg.content, str) else ""
                if text:
                    content.append({"type": "text", "text": text})
            for tc in msg.tool_calls:
                content.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id", str(uuid.uuid4())),
                        "name": tc.get("name", ""),
                        "input": tc.get("arguments", {}),
                    }
                )
            out.append({"role": "assistant", "content": content})
        else:
            out.append(
                {
                    "role": msg.role,
                    "content": (
                        msg.content
                        if isinstance(msg.content, (str, list))
                        else str(msg.content)
                    ),
                }
            )
    return system, out


class AnthropicProvider(LLMProvider):
    """LLM provider adapter for Anthropic Claude models.

    Reads ``ANTHROPIC_API_KEY`` from the environment (or accepts explicit key).
    """

    provider_id = "anthropic"

    def __init__(self, api_key: str | None = None) -> None:
        import anthropic  # type: ignore[import]
        import os

        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or None
        self._client = anthropic.AsyncAnthropic(api_key=resolved_key)

    async def stream_completion(
        self,
        messages: list[Message],
        model: str,
        tools: list[ToolDef] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        response_format: ResponseFormat | None = None,
    ) -> AsyncIterator[ProviderStreamEvent]:
        caps = self.get_model_capabilities(model)
        _max_tokens = max_tokens or caps.max_output_tokens

        system_text, anthropic_messages = _messages_to_anthropic(messages)

        api_tools = [_tool_to_anthropic(t) for t in tools] if tools else []

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": _max_tokens,
            "messages": anthropic_messages,
            "temperature": temperature,
        }
        if system_text:
            kwargs["system"] = system_text
        if api_tools:
            kwargs["tools"] = api_tools

        # Collect active tool calls during stream
        active_tool: dict[str, Any] | None = None

        async with self._client.messages.stream(**kwargs) as stream:
            async for event in stream:
                event_type = type(event).__name__

                if event_type == "RawContentBlockStartEvent":
                    block = event.content_block
                    if block.type == "text":
                        pass  # text deltas will follow
                    elif block.type == "tool_use":
                        active_tool = {"id": block.id, "name": block.name, "args_raw": ""}
                        yield ProviderStreamEvent(
                            kind="tool_call_start",
                            tool_call_id=block.id,
                            tool_name=block.name,
                        )

                elif event_type == "RawContentBlockDeltaEvent":
                    delta = event.delta
                    if delta.type == "text_delta":
                        yield ProviderStreamEvent(kind="text_delta", text=delta.text)
                    elif delta.type == "input_json_delta":
                        if active_tool:
                            active_tool["args_raw"] += delta.partial_json
                        yield ProviderStreamEvent(
                            kind="tool_call_delta",
                            tool_call_id=active_tool["id"] if active_tool else None,
                            tool_args_delta=delta.partial_json,
                        )

                elif event_type == "RawContentBlockStopEvent":
                    if active_tool:
                        import json
                        try:
                            parsed_args = json.loads(active_tool["args_raw"] or "{}")
                        except json.JSONDecodeError:
                            parsed_args = {}
                        yield ProviderStreamEvent(
                            kind="tool_call_end",
                            tool_call_id=active_tool["id"],
                            tool_name=active_tool["name"],
                            tool_args=parsed_args,
                        )
                        active_tool = None

                elif event_type == "RawMessageDeltaEvent":
                    usage = getattr(event, "usage", None)
                    if usage:
                        yield ProviderStreamEvent(
                            kind="usage",
                            output_tokens=getattr(usage, "output_tokens", None),
                        )

                elif event_type == "RawMessageStartEvent":
                    usage = getattr(event.message, "usage", None)
                    if usage:
                        yield ProviderStreamEvent(
                            kind="usage",
                            input_tokens=getattr(usage, "input_tokens", None),
                            output_tokens=getattr(usage, "output_tokens", None),
                        )

        yield ProviderStreamEvent(kind="done")

    async def count_tokens(self, messages: list[Message], model: str) -> int:
        """Use Anthropic's token counting endpoint."""
        try:
            system_text, anthropic_messages = _messages_to_anthropic(messages)
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": anthropic_messages,
            }
            if system_text:
                kwargs["system"] = system_text
            response = await self._client.messages.count_tokens(**kwargs)
            return response.input_tokens
        except Exception as exc:
            logger.warning("Anthropic token count failed: %s — using estimate", exc)
            # Rough fallback: 4 chars ≈ 1 token
            total_chars = sum(
                len(m.content) if isinstance(m.content, str) else 0 for m in messages
            )
            return max(1, total_chars // 4)

    async def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(
                id=f"anthropic:{model_id}",
                name=caps.display_name,
                provider_id="anthropic",
                capabilities=caps,
            )
            for model_id, caps in _ANTHROPIC_MODELS.items()
        ]

    def get_model_capabilities(self, model: str) -> ModelCapabilities:
        return _ANTHROPIC_MODELS.get(
            model,
            ModelCapabilities(
                model_id=model,
                provider_id="anthropic",
                display_name=model,
                context_window=200_000,
                max_output_tokens=4_096,
                supports_tools=True,
                supports_streaming=True,
            ),
        )

    def cost_per_token(self, model: str) -> CostRate:
        caps = self.get_model_capabilities(model)
        return CostRate(
            input_cost_per_1k=caps.input_cost_per_1k,
            output_cost_per_1k=caps.output_cost_per_1k,
        )
