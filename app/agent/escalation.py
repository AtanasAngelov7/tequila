"""Sprint 04 — Escalation protocol (§4.7).

``EscalationDetector`` checks whether an ongoing run should be handed off
to a different agent.  It tracks consecutive failure counts and tests for
trigger phrases configured in ``EscalationConfig`` / ``SoulConfig``.

This module only contains *detection* logic.  The actual context transfer
and spawn of a new session is done by the gateway / run-loop layer (Sprint 06).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.agent.models import EscalationConfig, SoulConfig

logger = logging.getLogger(__name__)


@dataclass
class EscalationState:
    """Per-session mutable escalation tracking state."""

    consecutive_failures: int = 0
    """Number of consecutive LLM errors / tool failures in this run."""

    triggered: bool = False
    """Set to ``True`` once escalation has fired (idempotent)."""

    trigger_reason: str = ""
    """Human-readable description of why escalation was triggered."""


def _compile_phrase_pattern(phrases: list[str]) -> re.Pattern[str] | None:
    """Build a case-insensitive OR pattern from a list of trigger phrases."""
    if not phrases:
        return None
    escaped = [re.escape(p) for p in phrases]
    return re.compile("|".join(escaped), re.IGNORECASE)


class EscalationDetector:
    """Detects escalation triggers for a single session run.

    Usage::

        detector = EscalationDetector(config=agent.escalation, soul=agent.soul)

        # After each LLM response text:
        if detector.check_phrase(llm_text):
            handle_escalation(detector.state.trigger_reason)

        # After each failure:
        if detector.check_failures():
            handle_escalation(detector.state.trigger_reason)
    """

    def __init__(
        self,
        config: EscalationConfig | None = None,
        soul: SoulConfig | None = None,
    ) -> None:
        self.config: EscalationConfig = config or EscalationConfig()
        self._phrase_pattern: re.Pattern[str] | None = None

        if soul and soul.escalation_phrases:
            self._phrase_pattern = _compile_phrase_pattern(soul.escalation_phrases)

        self.state = EscalationState()

    # ── Public API ────────────────────────────────────────────────────────────

    def record_failure(self) -> None:
        """Increment the consecutive failure counter."""
        self.state.consecutive_failures += 1

    def clear_failures(self) -> None:
        """Reset failure counter on a successful turn."""
        self.state.consecutive_failures = 0

    def check_failures(self) -> bool:
        """Return ``True`` (and mark state) if failure threshold reached."""
        if self.state.triggered:
            return True
        if not self.config.enabled:
            return False
        threshold = self.config.max_consecutive_failures
        if self.state.consecutive_failures >= threshold:
            self.state.triggered = True
            self.state.trigger_reason = (
                f"Consecutive failure threshold reached "
                f"({self.state.consecutive_failures} ≥ {threshold})"
            )
            logger.info(
                "Escalation triggered (failures): agent=%s reason='%s'",
                self.config.target_agent_id,
                self.state.trigger_reason,
            )
            return True
        return False

    def check_phrase(self, text: str) -> bool:
        """Return ``True`` (and mark state) if a trigger phrase is found in *text*."""
        if self.state.triggered:
            return True
        if not self.config.enabled:
            return False
        if not self._phrase_pattern:
            return False
        m = self._phrase_pattern.search(text)
        if m:
            self.state.triggered = True
            self.state.trigger_reason = f"Trigger phrase matched: '{m.group(0)}'"
            logger.info(
                "Escalation triggered (phrase): agent=%s reason='%s'",
                self.config.target_agent_id,
                self.state.trigger_reason,
            )
            return True
        return False

    def should_escalate(self, text: str = "") -> bool:
        """Convenience: run both checks and return True if either fires."""
        return self.check_phrase(text) or self.check_failures()

    def build_context_message(
        self,
        recent_messages: list[dict],
        summary: str = "",
    ) -> str:
        """Build a handoff context message for the target agent.

        Includes the last ``config.context_message_count`` messages plus
        an optional summary.
        """
        count = self.config.context_message_count
        selected = recent_messages[-count:] if recent_messages else []
        lines: list[str] = ["[Escalation context]"]
        if summary:
            lines.append(f"Session summary: {summary}")
        lines.append(f"Trigger: {self.state.trigger_reason}")
        lines.append("")
        for msg in selected:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        return "\n".join(lines)
