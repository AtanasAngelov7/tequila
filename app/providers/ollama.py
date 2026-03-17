"""Sprint 04 — Ollama provider adapter (§4.6).

Uses Ollama's OpenAI-compatible API (``/v1/chat/completions``) via
``httpx`` and discover models via ``GET /api/tags``.

Ollama is optional — if the server is not reachable the provider stays
available in the registry but ``health_check()`` returns ``False``.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncIterator

import httpx

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

_DEFAULT_BASE_URL = "http://localhost:11434"


def _tool_to_openai_format(tool: ToolDef) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _messages_to_openai_format(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        d: dict[str, Any] = {"role": msg.role}
        if msg.role == "tool":
            d["tool_call_id"] = msg.tool_call_id or ""
            d["content"] = msg.content if isinstance(msg.content, str) else str(msg.content)
        elif msg.role == "assistant" and msg.tool_calls:
            d["content"] = msg.content or ""
            d["tool_calls"] = msg.tool_calls
        else:
            d["content"] = (
                msg.content if isinstance(msg.content, (str, list)) else str(msg.content)
            )
        out.append(d)
    return out


class OllamaProvider(LLMProvider):
    """LLM provider adapter for locally-hosted Ollama models.

    All requests go to Ollama's OpenAI-compatible endpoint.  Model discovery
    uses the native ``/api/tags`` endpoint.

    Token counting uses tiktoken with ``cl100k_base`` as a fallback because
    Ollama doesn't expose a counting endpoint.
    """

    provider_id = "ollama"

    def __init__(self, base_url: str = _DEFAULT_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=120.0)

    async def stream_completion(
        self,
        messages: list[Message],
        model: str,
        tools: list[ToolDef] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        response_format: ResponseFormat | None = None,
    ) -> AsyncIterator[ProviderStreamEvent]:
        openai_messages = _messages_to_openai_format(messages)
        api_tools = [_tool_to_openai_format(t) for t in tools] if tools else []

        payload: dict[str, Any] = {
            "model": model,
            "messages": openai_messages,
            "stream": True,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if api_tools:
            payload["tools"] = api_tools
        if response_format and response_format.type == "json_object":
            payload["response_format"] = {"type": "json_object"}

        tool_call_buf: dict[int, dict[str, Any]] = {}

        try:
            async with self._http.stream(
                "POST",
                "/v1/chat/completions",
                json=payload,
                headers={"Accept": "text/event-stream"},
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    # Usage (may or may not be present)
                    usage = chunk.get("usage")
                    if usage:
                        yield ProviderStreamEvent(
                            kind="usage",
                            input_tokens=usage.get("prompt_tokens"),
                            output_tokens=usage.get("completion_tokens"),
                        )

                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta", {})

                        content = delta.get("content")
                        if content:
                            yield ProviderStreamEvent(kind="text_delta", text=content)

                        for tc_delta in delta.get("tool_calls", []):
                            idx = tc_delta.get("index", 0)
                            if idx not in tool_call_buf:
                                tc_id = tc_delta.get("id") or str(uuid.uuid4())
                                fn = tc_delta.get("function", {})
                                tc_name = fn.get("name", "")
                                # TD-263: Accumulate args from first chunk too
                                first_args = fn.get("arguments", "")
                                tool_call_buf[idx] = {
                                    "id": tc_id,
                                    "name": tc_name,
                                    "args_raw": first_args,
                                }
                                yield ProviderStreamEvent(
                                    kind="tool_call_start",
                                    tool_call_id=tc_id,
                                    tool_name=tc_name,
                                )
                            else:
                                fn = tc_delta.get("function", {})
                                args_delta = fn.get("arguments", "")
                                if args_delta:
                                    tool_call_buf[idx]["args_raw"] += args_delta
                                    yield ProviderStreamEvent(
                                        kind="tool_call_delta",
                                        tool_call_id=tool_call_buf[idx]["id"],
                                        tool_args_delta=args_delta,
                                    )

                        finish_reason = choice.get("finish_reason")
                        if finish_reason in ("tool_calls", "stop"):
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

        except httpx.ConnectError as exc:
            logger.warning("Ollama not reachable at %s: %s", self.base_url, exc)
            yield ProviderStreamEvent(
                kind="error",
                error_message=f"Ollama not reachable at {self.base_url}",
                error_code="connection_error",
            )
        except httpx.HTTPStatusError as exc:
            yield ProviderStreamEvent(
                kind="error",
                error_message=str(exc),
                error_code="http_error",
            )
        except Exception as exc:  # noqa: BLE001
            # TD-210: Catch-all to avoid unhandled stream errors propagating
            logger.exception("Unexpected error during Ollama streaming")
            yield ProviderStreamEvent(
                kind="error",
                error_message=str(exc),
                error_code="stream_error",
            )

        yield ProviderStreamEvent(kind="done")

    async def count_tokens(self, messages: list[Message], model: str) -> int:
        """Estimate via tiktoken (cl100k_base encoding)."""
        try:
            import tiktoken  # type: ignore[import]

            enc = tiktoken.get_encoding("cl100k_base")
            total = 0
            for msg in messages:
                total += 4
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                total += len(enc.encode(content))
            return total
        except Exception:
            total_chars = sum(
                len(m.content) if isinstance(m.content, str) else 0 for m in messages
            )
            return max(1, total_chars // 4)

    async def list_models(self) -> list[ModelInfo]:
        """Discover locally available models via ``GET /api/tags``."""
        try:
            response = await self._http.get("/api/tags")
            response.raise_for_status()
            data = response.json()
            models: list[ModelInfo] = []
            for entry in data.get("models", []):
                name: str = entry.get("name", "")
                if not name:
                    continue
                caps = self._build_capabilities(name)
                models.append(
                    ModelInfo(
                        id=f"ollama:{name}",
                        name=name,
                        provider_id="ollama",
                        capabilities=caps,
                    )
                )
            return models
        except (httpx.ConnectError, httpx.HTTPStatusError) as exc:
            logger.info("Ollama list_models unavailable: %s", exc)
            return []

    def _build_capabilities(self, model_name: str) -> ModelCapabilities:
        """Build capability metadata from the model name.

        Ollama doesn't expose capabilities via the API so we infer from
        the model name string.
        """
        lower = model_name.lower()
        context_window = 4_096
        if "llama3" in lower or "llama-3" in lower:
            context_window = 128_000
        elif "mistral" in lower:
            context_window = 32_000
        elif "gemma" in lower:
            context_window = 8_192
        supports_tools = any(
            kw in lower for kw in ("llama3", "mistral", "qwen", "phi")
        )
        return ModelCapabilities(
            model_id=model_name,
            provider_id="ollama",
            display_name=model_name,
            context_window=context_window,
            max_output_tokens=min(context_window, 4_096),
            supports_tools=supports_tools,
            supports_vision=False,
            supports_structured_output=False,
            supports_streaming=True,
            supports_thinking=False,
            input_cost_per_1k=0.0,
            output_cost_per_1k=0.0,
        )

    def get_model_capabilities(self, model: str) -> ModelCapabilities:
        return self._build_capabilities(model)

    def cost_per_token(self, model: str) -> CostRate:
        return CostRate(input_cost_per_1k=0.0, output_cost_per_1k=0.0)

    async def health_check(self) -> bool:
        try:
            response = await self._http.get("/api/tags", timeout=5.0)
            return response.status_code < 400
        except Exception:
            return False

    async def close(self) -> None:
        await self._http.aclose()
