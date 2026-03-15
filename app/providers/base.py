"""Sprint 04 — Provider abstraction layer base types (§4.6, §4.6a, §4.6b).

Defines the abstract ``LLMProvider`` interface and all shared data models:
- ``ToolDef`` / ``ToolResult`` / ``ResponseFormat`` — tool-calling protocol
- ``ProviderStreamEvent`` — unified streaming event from any provider
- ``ModelCapabilities`` / ``ModelInfo`` / ``CostRate`` — model & capability registry
- ``Message`` — internal message representation

All provider adapters (Anthropic, OpenAI, Ollama) implement ``LLMProvider``.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Literal

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── MESSAGE ───────────────────────────────────────────────────────────────────


class Message(BaseModel):
    """Internal message representation passed to providers."""

    role: Literal["system", "user", "assistant", "tool"]
    """Message role."""

    content: str | list[Any]
    """Text content or multi-part content list (for vision / tool results)."""

    tool_call_id: str | None = None
    """For ``role=tool`` messages — matches the originating ``tool_call_start`` id."""

    tool_calls: list[dict[str, Any]] | None = None
    """For assistant messages that contain one or more tool call requests."""

    name: str | None = None
    """Optional name field (used by some providers for tool messages)."""


# ── TOOL PROTOCOL (§4.6a) ─────────────────────────────────────────────────────


class ToolDef(BaseModel):
    """Unified internal tool definition sent to providers."""

    name: str
    """Tool identifier, e.g. ``fs_read_file``."""

    description: str
    """Human (and LLM) readable description of what the tool does."""

    parameters: dict[str, Any]
    """JSON Schema for the tool's input parameters."""

    safety: Literal["read_only", "side_effect", "destructive", "critical"] = "side_effect"
    """Safety classification — used for policy checks and confirmation gates."""


class ToolResult(BaseModel):
    """Result from executing a tool call."""

    tool_call_id: str
    """Matches the ``tool_call_id`` from the originating ``ProviderStreamEvent``."""

    success: bool
    """Whether the tool executed without error."""

    result: str | dict[str, Any] | list[Any]
    """Tool output.  Stringified before injection into messages."""

    error: str | None = None
    """Error message if ``success=False``."""

    execution_time_ms: int = 0
    """Wall-clock time for the tool execution."""


class ResponseFormat(BaseModel):
    """Controls the output format of a completion."""

    type: Literal["text", "json_object"] = "text"
    """``json_object`` enables JSON mode / structured output."""

    json_schema: dict[str, Any] | None = None
    """Schema for structured output (used by OpenAI ``response_format``)."""


# ── STREAMING EVENTS (§4.6a) ──────────────────────────────────────────────────


class ProviderStreamEvent(BaseModel):
    """Unified streaming event yielded by ``LLMProvider.stream_completion()``."""

    kind: Literal[
        "text_delta",
        "tool_call_start",
        "tool_call_delta",
        "tool_call_end",
        "thinking_delta",
        "usage",
        "done",
        "error",
    ]
    """Event type."""

    text: str | None = None
    """Incremental text content (``text_delta``, ``thinking_delta``)."""

    tool_call_id: str | None = None
    """Unique ID for this tool call invocation."""

    tool_name: str | None = None
    """Tool name (``tool_call_start``)."""

    tool_args_delta: str | None = None
    """Partial JSON argument string (``tool_call_delta``)."""

    tool_args: dict[str, Any] | None = None
    """Fully parsed arguments dict (``tool_call_end``)."""

    input_tokens: int | None = None
    """Input token count (``usage`` event)."""

    output_tokens: int | None = None
    """Output token count (``usage`` event)."""

    error_message: str | None = None
    """Error description (``error`` event)."""

    error_code: str | None = None
    """Machine-readable error code, e.g. ``rate_limit``, ``context_length_exceeded``."""


# ── COST RATE ─────────────────────────────────────────────────────────────────


class CostRate(BaseModel):
    """Per-token cost information for a model."""

    input_cost_per_1k: float = 0.0
    """USD cost per 1 000 input tokens."""

    output_cost_per_1k: float = 0.0
    """USD cost per 1 000 output tokens."""


# ── MODEL CAPABILITY REGISTRY (§4.6b) ────────────────────────────────────────


class ModelCapabilities(BaseModel):
    """Per-model capability metadata used by prompt assembly and vision."""

    model_id: str
    """Provider's model identifier, e.g. ``claude-sonnet-4-5``."""

    provider_id: str
    """Provider name, e.g. ``anthropic``."""

    display_name: str
    """Human-readable model name for the UI, e.g. ``Claude Sonnet 4.5``."""

    context_window: int = 128_000
    """Maximum input token count."""

    max_output_tokens: int = 4_096
    """Maximum output token count."""

    supports_tools: bool = True
    """Whether this model accepts tool definitions."""

    supports_vision: bool = False
    """Whether this model can process image content blocks."""

    supports_structured_output: bool = False
    """JSON mode / response_format support."""

    supports_streaming: bool = True
    """Whether streaming completions are available."""

    supports_thinking: bool = False
    """Extended thinking / reasoning tokens (Anthropic Claude ≥ 3.7)."""

    input_cost_per_1k: float = 0.0
    """USD per 1k input tokens."""

    output_cost_per_1k: float = 0.0
    """USD per 1k output tokens."""


class ModelInfo(BaseModel):
    """Lightweight model listing entry for the UI model selector."""

    id: str
    """Provider-qualified model ID, e.g. ``anthropic:claude-sonnet-4-5``."""

    name: str
    """Display name, e.g. ``Claude Sonnet 4.5 (balanced)``."""

    provider_id: str
    """Provider name."""

    capabilities: ModelCapabilities | None = None
    """Full capability metadata (populated when available)."""


# ── ABSTRACT PROVIDER (§4.6) ─────────────────────────────────────────────────


class LLMProvider(ABC):
    """Abstract base class for all LLM provider adapters.

    Concrete implementations: ``AnthropicProvider``, ``OpenAIProvider``,
    ``OllamaProvider``.  Register via ``ProviderRegistry``.
    """

    provider_id: str = ""
    """Must be set on each concrete subclass, e.g. ``"anthropic"``."""

    # ─── Abstract interface ─────────────────────────────────────────────────

    @abstractmethod
    async def stream_completion(
        self,
        messages: list[Message],
        model: str,
        tools: list[ToolDef] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        response_format: ResponseFormat | None = None,
    ) -> AsyncIterator[ProviderStreamEvent]:
        """Stream a completion from the provider.

        Yields ``ProviderStreamEvent`` objects in the unified format.
        """
        ...
        # Make mypy happy — concrete subclasses must implement this.
        if False:
            yield ProviderStreamEvent(kind="done")  # type: ignore[misc]

    @abstractmethod
    async def count_tokens(self, messages: list[Message], model: str) -> int:
        """Count the tokens consumed by *messages* for *model*.

        Used by prompt assembly budget calculations.  Should return an
        accurate count without making a provider round-trip if possible
        (e.g. via tiktoken or the provider's counting endpoint).
        """
        ...

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """Return a list of models available on this provider."""
        ...

    # ─── Optional / default implementations ────────────────────────────────

    def get_model_capabilities(self, model: str) -> ModelCapabilities:
        """Return capability metadata for *model*.

        Base implementation returns a conservative default.  Concrete
        providers override this with per-model data.
        """
        return ModelCapabilities(
            model_id=model,
            provider_id=self.provider_id,
            display_name=model,
        )

    def cost_per_token(self, model: str) -> CostRate:
        """Return the cost rate for *model*.  ``$0`` by default."""
        caps = self.get_model_capabilities(model)
        return CostRate(
            input_cost_per_1k=caps.input_cost_per_1k,
            output_cost_per_1k=caps.output_cost_per_1k,
        )

    async def health_check(self) -> bool:
        """Return ``True`` if the provider is reachable.

        Used by the startup sequence (§15.2) to populate ``ProviderStatus``.
        """
        try:
            await self.list_models()
            return True
        except Exception:
            return False
