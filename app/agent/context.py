"""Sprint 07 — Context window management (§4.7).

Provides ``ContextBudget`` — the single object responsible for all token
accounting during a turn:

* Counts tokens in the current prompt using ``tiktoken`` (with an in-process
  cache keyed on the message hash).
* Detects when usage exceeds the compression threshold (default 80 %).
* Applies three compression strategies in priority order:

  1. ``compress_drop_tool_results``  — replace large tool outputs with a
     ``[result truncated]`` placeholder.
  2. ``compress_trim_oldest``        — drop the oldest user / assistant
     exchange pairs until below target ratio.
  3. ``compress_summarize_old``      — ask the LLM to summarise the oldest
     portion of the conversation (requires an active provider).

Typical usage
-------------
::

    budget = ContextBudget.for_model("anthropic:claude-sonnet-4-6")
    if budget.needs_compression(messages):
        messages = await budget.auto_compress(
            messages, provider=provider, model="claude-sonnet-4-6"
        )
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Default model context windows ────────────────────────────────────────────

_MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # Anthropic — current
    "claude-opus-4-6":    1_000_000,
    "claude-sonnet-4-6":  1_000_000,
    "claude-haiku-4-5":     200_000,
    # Anthropic — legacy (backwards-compat for saved sessions)
    "claude-opus-4-5":    200_000,
    "claude-sonnet-4-5":  200_000,
    "claude-3-opus":      200_000,
    "claude-3-7-sonnet":  200_000,
    "claude-3-5-sonnet":  200_000,
    "claude-3-5-haiku":   200_000,
    # OpenAI — current
    "gpt-5.4":          1_000_000,
    "gpt-5.4-mini":       400_000,
    "gpt-5.4-nano":       400_000,
    # OpenAI — legacy (backwards-compat for saved sessions)
    "gpt-4o":             128_000,
    "gpt-4o-mini":        128_000,
    "gpt-4-turbo":        128_000,
    "gpt-4":                8_192,
    "gpt-3-5-turbo":       16_385,
    "o1":                 200_000,
    "o1-mini":            128_000,
    # Gemini — current
    "gemini-2.5-pro":   1_000_000,
    "gemini-2.5-flash": 1_000_000,
    # Ollama / local (conservative defaults)
    "llama3":               8_192,
    "llama3.1":           128_000,
    "llama3.2":           128_000,
    "mistral":             32_768,
    "mixtral":             32_768,
    "qwen2":              128_000,
}

_DEFAULT_CONTEXT_WINDOW = 128_000
_DEFAULT_RESERVED_OUTPUT = 4_096
_COMPRESSION_THRESHOLD = 0.80  # 80 % usage triggers compression
_COMPRESSION_TARGET = 0.70     # compress down to 70 %


# ── Token counting ────────────────────────────────────────────────────────────


def _tiktoken_encoding_for_model(model_id: str):  # type: ignore[return]
    """Return the best tiktoken encoding for *model_id*.

    Falls back to ``cl100k_base`` for unknown models.
    """
    try:
        import tiktoken
    except ImportError:
        return None

    # Strip provider prefix (e.g. "anthropic:claude-..." → "claude-...")
    bare = model_id.split(":")[-1] if ":" in model_id else model_id

    try:
        return tiktoken.encoding_for_model(bare)
    except KeyError:
        pass

    # Anthropic and most modern models use the cl100k_base vocabulary
    return tiktoken.get_encoding("cl100k_base")


class TokenCounter:
    """Per-session token counter with an in-process text-hash cache.

    The cache prevents re-counting unchanged messages on every turn
    iteration.
    """

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id
        self._enc = _tiktoken_encoding_for_model(model_id)
        # TD-221: Use LRU dict with max size to prevent unbounded growth
        self._cache: dict[str, int] = {}
        self._cache_max = 2048

    def count(self, text: str) -> int:
        """Return the token count for *text*, using the cache where possible."""
        if not text:
            return 0

        key = hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()
        if key in self._cache:
            return self._cache[key]

        if self._enc is not None:
            n = len(self._enc.encode(text))
        else:
            # Fallback: approximate at 4 chars / token
            n = max(1, len(text) // 4)

        # Evict oldest entries if cache is full
        if len(self._cache) >= self._cache_max:
            # Remove first ~25% of entries (oldest by insertion order)
            to_remove = self._cache_max // 4
            keys = list(self._cache.keys())[:to_remove]
            for k in keys:
                del self._cache[k]

        self._cache[key] = n
        return n

    def count_message(self, msg: Any) -> int:
        """Count tokens in a single provider ``Message`` object."""
        content = getattr(msg, "content", "") or ""
        if isinstance(content, list):
            # Multi-part content (vision, tool results, etc.)
            total = 0
            for part in content:
                if isinstance(part, dict):
                    total += self.count(str(part.get("text", "") or part.get("content", "")))
                else:
                    total += self.count(str(part))
            return total
        return self.count(str(content))

    def count_messages(self, messages: list[Any]) -> int:
        """Count tokens across a list of provider messages."""
        # Overhead per message (role tag, separator tokens)
        overhead_per_msg = 4
        return sum(self.count_message(m) + overhead_per_msg for m in messages)

    def clear_cache(self) -> None:
        """Clear the token count cache (e.g. after a message is edited)."""
        self._cache.clear()


# ── ContextBudget ─────────────────────────────────────────────────────────────


class ContextBudget:
    """Manages the token budget for one turn of the agent conversation.

    Parameters
    ----------
    model_id:
        Provider-qualified model ID (e.g. ``anthropic:claude-sonnet-4-6``).
        Used to select the tiktoken encoding and look up the default
        context-window size.
    context_window:
        Total input token limit for the model.  Defaults to a lookup from
        the built-in table or ``_DEFAULT_CONTEXT_WINDOW``.
    reserved_output:
        Tokens kept in reserve for the model's output.  The usable budget is
        ``context_window - reserved_output``.
    """

    def __init__(
        self,
        model_id: str = "",
        context_window: int | None = None,
        reserved_output: int = _DEFAULT_RESERVED_OUTPUT,
    ) -> None:
        self._model_id = model_id
        bare = model_id.split(":")[-1] if ":" in model_id else model_id
        cw = context_window or _MODEL_CONTEXT_WINDOWS.get(bare, _DEFAULT_CONTEXT_WINDOW)
        self.context_window = cw
        self.reserved_output = reserved_output
        self.total_budget = cw - reserved_output
        self._counter = TokenCounter(model_id)

    # ── Class-method constructor ─────────────────────────────────────────────

    @classmethod
    def for_model(cls, model_id: str, reserved_output: int = _DEFAULT_RESERVED_OUTPUT) -> "ContextBudget":
        """Convenient constructor that resolves context window from model ID."""
        return cls(model_id=model_id, reserved_output=reserved_output)

    # ── Token counting ───────────────────────────────────────────────────────

    def count_tokens(self, text: str) -> int:
        """Count tokens in *text* (cached)."""
        return self._counter.count(text)

    def count_messages(self, messages: list[Any]) -> int:
        """Count total tokens across a message list (cached)."""
        return self._counter.count_messages(messages)

    def usage_ratio(self, messages: list[Any]) -> float:
        """Return ``used_tokens / total_budget`` as a float in ``[0, ∞)``."""
        if self.total_budget <= 0:
            return 1.0
        return self.count_messages(messages) / self.total_budget

    def needs_compression(
        self,
        messages: list[Any],
        threshold: float = _COMPRESSION_THRESHOLD,
    ) -> bool:
        """Return ``True`` if current usage exceeds *threshold* (default 80 %)."""
        ratio = self.usage_ratio(messages)
        if ratio > threshold:
            logger.info(
                "ContextBudget[%s]: usage %.1f%% > threshold %.0f%% → compression needed",
                self._model_id,
                ratio * 100,
                threshold * 100,
            )
            return True
        return False

    # ── Compression strategies ───────────────────────────────────────────────

    def compress_drop_tool_results(self, messages: list[Any]) -> list[Any]:
        """Replace large tool-result message content with a truncation notice.

        Only messages where ``role == "tool"`` and the content is longer than
        500 characters are replaced.  Returns a *new* list (original is not
        mutated).
        """
        TOOL_RESULT_TRUNCATION_THRESHOLD = 500
        result: list[Any] = []

        for msg in messages:
            role = getattr(msg, "role", "")
            content = getattr(msg, "content", "")

            if (
                role == "tool"
                and isinstance(content, str)
                and len(content) > TOOL_RESULT_TRUNCATION_THRESHOLD
            ):
                import copy
                m = copy.copy(msg)
                # Replace content but keep all other fields
                object.__setattr__(m, "content", "[tool result truncated to save context]")
                result.append(m)
                logger.debug("compress_drop_tool_results: truncated %d chars", len(content))
            else:
                result.append(msg)

        return result

    def compress_trim_oldest(
        self,
        messages: list[Any],
        target_ratio: float = _COMPRESSION_TARGET,
    ) -> list[Any]:
        """Remove oldest non-system messages until usage is below *target_ratio*.

        System messages (``role == "system"``) and the most recent
        user/assistant exchange are preserved.

        Returns a *new* list.
        """
        # Separate system messages (always keep them)
        system_msgs = [m for m in messages if getattr(m, "role", "") == "system"]
        non_system = [m for m in messages if getattr(m, "role", "") != "system"]

        # Always preserve the last two non-system messages (current exchange)
        preserved_tail = non_system[-2:] if len(non_system) >= 2 else non_system[:]
        candidate_body = non_system[:-2] if len(non_system) >= 2 else []

        # TD-321: Pre-compute per-message token counts for O(n) trimming
        # instead of recomputing entire list each iteration.
        system_token_total = self.count_messages(system_msgs)
        tail_token_total = self.count_messages(preserved_tail)
        fixed_tokens = system_token_total + tail_token_total
        target_tokens = target_ratio * self.total_budget if self.total_budget > 0 else 0

        # Compute cumulative token count from front of candidate_body
        candidate_tokens = [self.count_tokens(getattr(m, "content", "") or "") for m in candidate_body]
        total_candidate = sum(candidate_tokens)

        drop_count = 0
        running_drop = 0
        while drop_count < len(candidate_body) and (fixed_tokens + total_candidate - running_drop) > target_tokens:
            removed = candidate_body[drop_count]
            running_drop += candidate_tokens[drop_count]
            logger.debug(
                "compress_trim_oldest: dropped message (role=%s)",
                getattr(removed, "role", "?"),
            )
            drop_count += 1
        candidate_body = candidate_body[drop_count:]

        trimmed = system_msgs + candidate_body + preserved_tail
        logger.info(
            "compress_trim_oldest: %d → %d messages (usage %.1f%%)",
            len(messages),
            len(trimmed),
            self.usage_ratio(trimmed) * 100,
        )
        return trimmed

    async def compress_summarize_old(
        self,
        messages: list[Any],
        provider: Any,
        model: str,
        keep_recent: int = 10,
    ) -> list[Any]:
        """Summarise the older portion of the conversation via the LLM.

        The most recent *keep_recent* non-system messages are preserved verbatim.
        Everything older is replaced with a single ``user``-role summary block
        (§4.7 "summarize_old" strategy).

        Parameters
        ----------
        messages:
            Current assembled message list.
        provider:
            Active ``LLMProvider`` instance used to generate the summary.
        model:
            Model identifier passed to the provider.
        keep_recent:
            Number of tail non-system messages to keep verbatim.
        """
        from app.providers.base import Message as ProviderMessage

        system_msgs = [m for m in messages if getattr(m, "role", "") == "system"]
        non_system = [m for m in messages if getattr(m, "role", "") != "system"]

        if len(non_system) <= keep_recent:
            # Nothing to summarise — not enough history
            return messages

        to_summarise = non_system[:-keep_recent]
        recent = non_system[-keep_recent:]

        # Build a condensed text representation for the summary prompt
        parts: list[str] = []
        for msg in to_summarise:
            role = getattr(msg, "role", "unknown")
            content = getattr(msg, "content", "")
            if isinstance(content, list):
                content = " ".join(
                    str(p.get("text", "") if isinstance(p, dict) else p)
                    for p in content
                )
            if content and str(content).strip():
                parts.append(f"{role.upper()}: {content[:500]}")

        if not parts:
            return messages

        transcript = "\n\n".join(parts[-30:])  # cap at 30 turns for the summary prompt

        summary_prompt = [
            ProviderMessage(
                role="user",
                content=(
                    "Please summarise the following conversation history concisely "
                    "in 200 words or fewer, preserving the key context, decisions, "
                    "and facts that are important for continuing the conversation:\n\n"
                    f"{transcript}\n\nSummary:"
                ),
            )
        ]

        try:
            summary_text_parts: list[str] = []
            # TD-366: stream_completion is an async generator — do NOT await it.
            stream = provider.stream_completion(
                messages=summary_prompt,
                model=model,
            )
            async for event in stream:
                if event.kind == "text_delta" and event.text:
                    summary_text_parts.append(event.text)
                elif event.kind == "done":
                    break

            summary_text = "".join(summary_text_parts).strip()
            if not summary_text:
                # Summary generation failed — fall back to trim_oldest
                logger.warning("compress_summarize_old: empty summary, falling back to trim_oldest")
                return self.compress_trim_oldest(messages)

            # Replace old messages with a summary block
            summary_msg = ProviderMessage(
                role="user",
                content=f"[Conversation summary — previous context]\n{summary_text}",
            )
            result = system_msgs + [summary_msg] + recent
            logger.info(
                "compress_summarize_old: condensed %d → %d messages (summary: %d chars)",
                len(messages),
                len(result),
                len(summary_text),
            )
            return result

        except Exception as exc:
            logger.warning("compress_summarize_old: failed (%s), falling back to trim_oldest", exc)
            return self.compress_trim_oldest(messages)

    # ── Auto-compress ────────────────────────────────────────────────────────

    async def auto_compress(
        self,
        messages: list[Any],
        provider: Any | None = None,
        model: str = "",
        threshold: float = _COMPRESSION_THRESHOLD,
    ) -> list[Any]:
        """Apply compression strategies until usage is below *threshold*.

        Strategies are tried in priority order:
        1. ``compress_drop_tool_results``
        2. ``compress_trim_oldest``
        3. ``compress_summarize_old``  (only when *provider* is supplied)

        Returns the compressed message list.
        """
        if not self.needs_compression(messages, threshold=threshold):
            return messages

        logger.info(
            "auto_compress: starting — usage %.1f%%, budget=%d tokens (model=%s)",
            self.usage_ratio(messages) * 100,
            self.total_budget,
            self._model_id,
        )

        # Strategy 1: drop tool results
        compressed = self.compress_drop_tool_results(messages)
        if not self.needs_compression(compressed, threshold=threshold):
            logger.info("auto_compress: done after drop_tool_results (usage %.1f%%)", self.usage_ratio(compressed) * 100)
            return compressed

        # Strategy 2: trim oldest
        compressed = self.compress_trim_oldest(compressed)
        if not self.needs_compression(compressed, threshold=threshold):
            logger.info("auto_compress: done after trim_oldest (usage %.1f%%)", self.usage_ratio(compressed) * 100)
            return compressed

        # Strategy 3: LLM summarisation (requires provider)
        if provider is not None and model:
            compressed = await self.compress_summarize_old(compressed, provider=provider, model=model)
            logger.info("auto_compress: done after summarize_old (usage %.1f%%)", self.usage_ratio(compressed) * 100)
            return compressed

        # All strategies exhausted — log a warning and return best effort
        logger.warning(
            "auto_compress: context still over budget (%.1f%%) after all strategies",
            self.usage_ratio(compressed) * 100,
        )
        return compressed


# ── Session-level budget cache (TD-220: capped) ──────────────────────────────

_budgets: dict[str, ContextBudget] = {}
_BUDGET_CACHE_MAX = 500


def get_or_create_budget(session_id: str, model_id: str, **kwargs: Any) -> ContextBudget:
    """Return the ``ContextBudget`` for *session_id*, creating it if needed.

    A new budget is created when the model changes between turns.
    """
    existing = _budgets.get(session_id)
    if existing is None or existing._model_id != model_id:
        # TD-220: Evict oldest entries if cache is full
        if len(_budgets) >= _BUDGET_CACHE_MAX:
            to_remove = _BUDGET_CACHE_MAX // 4
            keys = list(_budgets.keys())[:to_remove]
            for k in keys:
                del _budgets[k]
        existing = ContextBudget(model_id=model_id, **kwargs)
        _budgets[session_id] = existing
    return existing


def evict_budget(session_id: str) -> None:
    """Remove the cached budget for *session_id* (call on session close)."""
    _budgets.pop(session_id, None)
