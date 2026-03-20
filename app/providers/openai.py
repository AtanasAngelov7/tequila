"""Sprint 04 — OpenAI provider adapter (§4.6).

Streams completions via the official ``openai`` Python SDK.
"""
from __future__ import annotations

import json
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

_OPENAI_MODELS: dict[str, ModelCapabilities] = {
    "gpt-5.4": ModelCapabilities(
        model_id="gpt-5.4",
        provider_id="openai",
        display_name="GPT-5.4 (flagship)",
        context_window=1_000_000,
        max_output_tokens=128_000,
        supports_tools=True,
        supports_vision=True,
        supports_structured_output=True,
        supports_streaming=True,
        supports_thinking=False,
        input_cost_per_1k=0.0025,
        output_cost_per_1k=0.015,
    ),
    "gpt-5.4-mini": ModelCapabilities(
        model_id="gpt-5.4-mini",
        provider_id="openai",
        display_name="GPT-5.4 Mini (fast)",
        context_window=400_000,
        max_output_tokens=128_000,
        supports_tools=True,
        supports_vision=True,
        supports_structured_output=True,
        supports_streaming=True,
        supports_thinking=False,
        input_cost_per_1k=0.00075,
        output_cost_per_1k=0.0045,
    ),
    "gpt-5.4-nano": ModelCapabilities(
        model_id="gpt-5.4-nano",
        provider_id="openai",
        display_name="GPT-5.4 Nano (budget)",
        context_window=400_000,
        max_output_tokens=128_000,
        supports_tools=True,
        supports_vision=True,
        supports_structured_output=True,
        supports_streaming=True,
        supports_thinking=False,
        input_cost_per_1k=0.0002,
        output_cost_per_1k=0.00125,
    ),
}

# Deprecated/superseded models kept for backwards-compatibility.
# list_models() does NOT include these; get_model_capabilities() resolves them
# so that existing sessions with legacy model IDs don't break.
_OPENAI_LEGACY_MODELS: dict[str, ModelCapabilities] = {
    "gpt-4o": ModelCapabilities(
        model_id="gpt-4o",
        provider_id="openai",
        display_name="GPT-4o (legacy)",
        context_window=128_000,
        max_output_tokens=16_384,
        supports_tools=True,
        supports_vision=True,
        supports_structured_output=True,
        supports_streaming=True,
        supports_thinking=False,
        input_cost_per_1k=0.0025,
        output_cost_per_1k=0.01,
    ),
    "gpt-4o-mini": ModelCapabilities(
        model_id="gpt-4o-mini",
        provider_id="openai",
        display_name="GPT-4o Mini (legacy)",
        context_window=128_000,
        max_output_tokens=16_384,
        supports_tools=True,
        supports_vision=True,
        supports_structured_output=True,
        supports_streaming=True,
        supports_thinking=False,
        input_cost_per_1k=0.00015,
        output_cost_per_1k=0.0006,
    ),
    "o1": ModelCapabilities(
        model_id="o1",
        provider_id="openai",
        display_name="o1 (legacy)",
        context_window=200_000,
        max_output_tokens=100_000,
        supports_tools=True,
        supports_vision=False,
        supports_structured_output=True,
        supports_streaming=True,
        supports_thinking=False,
        input_cost_per_1k=0.015,
        output_cost_per_1k=0.06,
    ),
    "o3-mini": ModelCapabilities(
        model_id="o3-mini",
        provider_id="openai",
        display_name="o3 Mini (legacy)",
        context_window=200_000,
        max_output_tokens=100_000,
        supports_tools=True,
        supports_vision=False,
        supports_structured_output=True,
        supports_streaming=True,
        supports_thinking=False,
        input_cost_per_1k=0.0011,
        output_cost_per_1k=0.0044,
    ),
}


def _tool_to_openai(tool: ToolDef) -> dict[str, Any]:
    """Convert unified ``ToolDef`` → OpenAI function tool dict."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _messages_to_openai(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert internal ``Message`` list to OpenAI messages format."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        d: dict[str, Any] = {"role": msg.role}
        if msg.role == "tool":
            d["tool_call_id"] = msg.tool_call_id or ""
            d["content"] = msg.content if isinstance(msg.content, str) else str(msg.content)
            if msg.name:
                d["name"] = msg.name
        elif msg.role == "assistant" and msg.tool_calls:
            d["content"] = msg.content or ""
            d["tool_calls"] = msg.tool_calls
        else:
            d["content"] = (
                msg.content if isinstance(msg.content, (str, list)) else str(msg.content)
            )
        out.append(d)
    return out


class OpenAIProvider(LLMProvider):
    """LLM provider adapter for OpenAI models.

    Reads ``OPENAI_API_KEY`` from the environment (or accepts explicit key).
    """

    provider_id = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        import openai  # type: ignore[import]
        import os

        resolved_key = api_key or os.environ.get("OPENAI_API_KEY") or None
        # TD-361: Warn early so the error surfaces at startup, not mid-request
        if not resolved_key:
            logger.warning(
                "OpenAIProvider: no API key found. "
                "Set OPENAI_API_KEY or pass api_key= to the constructor."
            )
        # TD-368: Set explicit timeout; openai SDK default is 600s which is too long
        # for interactive streaming. 60s connect, 300s read allows long generations.
        self._client = openai.AsyncOpenAI(
            api_key=resolved_key,
            base_url=base_url,
            timeout=300.0,
        )

    async def close(self) -> None:
        """TD-362: Close the underlying httpx client to release connection pools."""
        try:
            await self._client.close()
        except Exception:
            pass

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

        openai_messages = _messages_to_openai(messages)
        api_tools = [_tool_to_openai(t) for t in tools] if tools else []

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": openai_messages,
            "max_tokens": _max_tokens,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if api_tools:
            kwargs["tools"] = api_tools
            kwargs["tool_choice"] = "auto"
        if response_format and response_format.type == "json_object":
            kwargs["response_format"] = {"type": "json_object"}

        # Track in-progress tool calls keyed by index
        tool_call_buf: dict[int, dict[str, Any]] = {}

        # TD-210: Wrap stream in try/except so errors yield proper events
        try:
            async for chunk in await self._client.chat.completions.create(**kwargs):
                # Usage event (sent in the last chunk when stream_options.include_usage=True)
                if chunk.usage:
                    yield ProviderStreamEvent(
                        kind="usage",
                        input_tokens=chunk.usage.prompt_tokens,
                        output_tokens=chunk.usage.completion_tokens,
                    )

                for choice in chunk.choices:
                    delta = choice.delta

                    # Text delta
                    if delta.content:
                        yield ProviderStreamEvent(kind="text_delta", text=delta.content)

                    # Tool call deltas
                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in tool_call_buf:
                                tc_id = tc_delta.id or str(uuid.uuid4())
                                tc_name = tc_delta.function.name if tc_delta.function else ""
                                # TD-345: capture first chunk's arguments (previously discarded)
                                first_args = (tc_delta.function.arguments or "") if tc_delta.function else ""
                                tool_call_buf[idx] = {"id": tc_id, "name": tc_name, "args_raw": first_args}
                                yield ProviderStreamEvent(
                                    kind="tool_call_start",
                                    tool_call_id=tc_id,
                                    tool_name=tc_name,
                                )
                                if first_args:
                                    yield ProviderStreamEvent(
                                        kind="tool_call_delta",
                                        tool_call_id=tc_id,
                                        tool_args_delta=first_args,
                                    )
                            else:
                                if tc_delta.function and tc_delta.function.arguments:
                                    tool_call_buf[idx]["args_raw"] += tc_delta.function.arguments
                                    yield ProviderStreamEvent(
                                        kind="tool_call_delta",
                                        tool_call_id=tool_call_buf[idx]["id"],
                                        tool_args_delta=tc_delta.function.arguments,
                                    )

                    # Finish reason — flush completed tool calls
                    if choice.finish_reason in ("tool_calls", "stop"):
                        for buf in tool_call_buf.values():
                            try:
                                parsed_args = json.loads(buf["args_raw"] or "{}")
                            except json.JSONDecodeError:
                                parsed_args = {}
                            yield ProviderStreamEvent(
                                kind="tool_call_end",
                                tool_call_id=buf["id"],
                                tool_name=buf["name"],
                                tool_args=parsed_args,
                            )
                        tool_call_buf.clear()

            yield ProviderStreamEvent(kind="done")
        except Exception as exc:
            logger.error("OpenAI stream error: %s", exc)
            yield ProviderStreamEvent(kind="error", error_message=str(exc), error_code="stream_error")
            yield ProviderStreamEvent(kind="done")

    async def count_tokens(self, messages: list[Message], model: str) -> int:
        """Estimate token count using tiktoken."""
        try:
            import tiktoken  # type: ignore[import]

            try:
                enc = tiktoken.encoding_for_model(model)
            except KeyError:
                enc = tiktoken.get_encoding("cl100k_base")

            total = 0
            for msg in messages:
                total += 4  # per-message overhead
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                total += len(enc.encode(content))
            return total
        except Exception as exc:
            logger.warning("OpenAI token count failed: %s — using estimate", exc)
            total_chars = sum(
                len(m.content) if isinstance(m.content, str) else 0 for m in messages
            )
            return max(1, total_chars // 4)

    async def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(
                id=f"openai:{model_id}",
                name=caps.display_name,
                provider_id="openai",
                capabilities=caps,
            )
            for model_id, caps in _OPENAI_MODELS.items()
        ]

    def get_model_capabilities(self, model: str) -> ModelCapabilities:
        if model in _OPENAI_MODELS:
            return _OPENAI_MODELS[model]
        if model in _OPENAI_LEGACY_MODELS:
            return _OPENAI_LEGACY_MODELS[model]
        return ModelCapabilities(
            model_id=model,
            provider_id="openai",
            display_name=model,
            context_window=128_000,
            max_output_tokens=4_096,
            supports_tools=True,
            supports_streaming=True,
        )

    def cost_per_token(self, model: str) -> CostRate:
        caps = self.get_model_capabilities(model)
        return CostRate(
            input_cost_per_1k=caps.input_cost_per_1k,
            output_cost_per_1k=caps.output_cost_per_1k,
        )
