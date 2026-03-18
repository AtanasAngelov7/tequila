"""Sprint 10 — Memory extraction pipeline (§5.5).

Converts raw session messages into structured ``MemoryExtract`` records
via a 6-step LLM-assisted pipeline.

Entry point: ``ExtractionPipeline.run(session_id, messages)``

LLM calls are injected via ``llm_fn`` to allow test mocking::

    pipeline = ExtractionPipeline(llm_fn=my_mock)

When ``llm_fn`` is None the pipeline uses the default active provider.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Awaitable
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# TD-131: named constant for per-message content truncation in prompt builders
EXTRACTION_CONTENT_MAX_CHARS: int = 500

# TD-113: fallback message count when classification step fails
_MAX_FALLBACK_MESSAGES: int = 10

_LLMFn = Callable[[list[dict[str, str]]], Awaitable[str]]

# ── Configuration ─────────────────────────────────────────────────────────────


class ExtractionConfig(BaseModel):
    """Hot-reloadable extraction configuration (§5.5)."""

    enabled: bool = True
    trigger_interval_messages: int = 10
    trigger_on_session_close: bool = True
    trigger_on_context_pressure: bool = True
    min_confidence: float = 0.5
    dedup_similarity_threshold: float = 0.95
    merge_similarity_threshold: float = 0.85
    max_extracts_per_batch: int = 20
    confidence_boost: float = 0.2
    confidence_penalty: float = 0.3
    entity_extraction_enabled: bool = True
    contradiction_auto_resolve: bool = False


# ── Extraction result ─────────────────────────────────────────────────────────


class ExtractionResult(BaseModel):
    """Outcome of one extraction run."""

    session_id: str
    messages_processed: int
    candidates: int
    created: int
    merged: int
    skipped: int
    errors: int


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_classify_prompt(messages: list[dict[str, Any]]) -> str:
    """Render the classification prompt for step 1."""
    lines = ["You are a memory extraction assistant."]
    lines.append(
        "Review the following conversation messages and identify which contain "
        "information worth remembering long-term: facts about the user, their "
        "preferences, relationships, skills, tasks, or significant experiences.\n"
        "Ignore chitchat, acknowledgments, filler, and procedural exchanges.\n"
        'Respond with a JSON array of message indices (0-based) that are relevant, '
        'e.g. [0, 2, 4].  Respond with ONLY the JSON array — no prose.'
    )
    lines.append("\n--- Messages ---")
    for i, msg in enumerate(messages):
        role = msg.get("role", "unknown")
        content = (msg.get("content") or "")[:EXTRACTION_CONTENT_MAX_CHARS]
        lines.append(f"[{i}] {role}: {content}")
    return "\n".join(lines)


def _build_extract_prompt(messages: list[dict[str, Any]]) -> str:
    """Render the extraction prompt for step 2."""
    lines = [
        "You are a memory extraction assistant.\n"
        "Extract structured memories from the following conversation messages.\n"
        "For each memory, output a JSON object with these fields:\n"
        '  "content": string (the memory, stated factually),\n'
        '  "memory_type": one of [identity, preference, fact, experience, task, relationship, skill],\n'
        '  "confidence": float 0.0–1.0,\n'
        '  "tags": list of short string tags (optional, may be empty),\n'
        '  "entity_mentions": list of names mentioned (optional, may be empty)\n'
        "\nRespond with a JSON array of memory objects only — no prose."
    ]
    lines.append("\n--- Messages ---")
    for msg in messages:
        role = msg.get("role", "unknown")
        content = (msg.get("content") or "")[:EXTRACTION_CONTENT_MAX_CHARS]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _parse_json_response(text: str) -> list[dict[str, Any]]:
    """Extract the first valid JSON array from an LLM response."""
    text = text.strip()
    # Try direct parse
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return obj
    except json.JSONDecodeError:
        pass
    # Fallback: find first balanced [...] block
    start = text.find("[")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                        if isinstance(obj, list):
                            return obj
                    except json.JSONDecodeError:
                        pass
                    break
    return []


async def _default_llm_fn(messages: list[dict[str, str]]) -> str:
    """Call the active LLM provider with a list of chat messages."""
    try:
        from app.providers.registry import get_registry
        registry = get_registry()
        providers = [p for p in registry.list_providers() if getattr(p, "provider_id", "") != "mock"]
        if not providers:
            providers = registry.list_providers()
        if not providers:
            return "[]"
        provider = providers[0]
        # Use the first available model
        qualified_model = getattr(provider, "default_model", None) or ""
        if not qualified_model:
            return "[]"
        # Build simple full-text completion via stream_completion
        from app.providers.base import Message as ProvMsg
        prov_messages = [ProvMsg(role=m["role"], content=m["content"]) for m in messages]
        chunks: list[str] = []
        stream = provider.stream_completion(
            messages=prov_messages, model=qualified_model, tools=[]
        )
        async for event in stream:
            if event.kind == "text_delta" and event.text:
                chunks.append(event.text)
        return "".join(chunks)
    except Exception as exc:
        logger.warning("ExtractionPipeline: default LLM call failed: %s", exc)
        return "[]"


# ── Pipeline ──────────────────────────────────────────────────────────────────


class ExtractionPipeline:
    """6-step extraction pipeline (§5.5).

    Args:
        llm_fn: Optional injectable LLM callable for testing.
                Signature: async (messages: list[{role, content}]) -> str
        config: ExtractionConfig; uses defaults if not provided.
    """

    def __init__(
        self,
        llm_fn: _LLMFn | None = None,
        config: ExtractionConfig | None = None,
    ) -> None:
        self._llm_fn = llm_fn or _default_llm_fn
        self.config = config or ExtractionConfig()

    async def run(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> ExtractionResult:
        """Run the full extraction pipeline on a batch of conversation messages.

        Args:
            session_id: The session the messages belong to.
            messages: List of message dicts with at least ``role`` and ``content``.
        """
        result = ExtractionResult(
            session_id=session_id,
            messages_processed=len(messages),
            candidates=0,
            created=0,
            merged=0,
            skipped=0,
            errors=0,
        )

        if not self.config.enabled or not messages:
            return result

        # Apply feedback weighting: boost/penalise based on feedback_rating
        # TD-50: use index-based mutation so the list is actually updated, not just the loop var
        weighted = list(messages)
        for i, msg in enumerate(weighted):
            rating = msg.get("feedback_rating")
            if rating == "up":
                weighted[i] = dict(msg, _confidence_boost=self.config.confidence_boost)
            elif rating == "down":
                weighted[i] = dict(msg, _confidence_penalty=self.config.confidence_penalty)

        # ── Step 1: Relevance classification ─────────────────────────────────
        relevant_indices = await self._step1_classify(weighted)
        if not relevant_indices:
            logger.debug("Extraction step 1: no relevant messages in session %s", session_id)
            return result

        relevant_messages = [weighted[i] for i in relevant_indices if i < len(weighted)]

        # ── Step 2: Structured extraction ────────────────────────────────────
        candidates = await self._step2_extract(relevant_messages)
        candidates = candidates[:self.config.max_extracts_per_batch]
        result.candidates = len(candidates)

        if not candidates:
            return result

        # Apply feedback confidence adjustment
        # TD-51: attribute all relevant_messages as sources for each candidate (best
        # approximation without per-message-attribution from the LLM).  Use max()
        # rather than sum() to prevent boost amplification across multiple messages.
        _adjusted: list[dict[str, Any]] = []
        for cand in candidates:
            conf = float(cand.get("confidence", 0.7))
            boost = max((m.get("_confidence_boost", 0.0) for m in relevant_messages), default=0.0)
            penalty = max(
                (m.get("_confidence_penalty", 0.0) for m in relevant_messages), default=0.0
            )
            conf = min(1.0, max(0.0, conf + boost - penalty))
            if conf < self.config.min_confidence:
                result.skipped += 1
                continue
            cand["confidence"] = conf
            _adjusted.append(cand)
        candidates = _adjusted

        # ── Step 3: Deduplication ─────────────────────────────────────────────
        to_create: list[dict[str, Any]] = []
        to_merge: list[tuple[dict[str, Any], str]] = []

        for cand in candidates:
            action, existing_id = await self._step3_dedup(cand)
            if action == "skip":
                result.skipped += 1
            elif action == "merge" and existing_id:
                to_merge.append((cand, existing_id))
            else:
                to_create.append(cand)

        # ── Step 4: Contradiction detection ──────────────────────────────────
        filtered_create: list[dict[str, Any]] = []
        for cand in to_create:
            resolved = await self._step4_contradiction(cand)
            if resolved is not None:
                filtered_create.append(resolved)
            else:
                result.skipped += 1
        to_create = filtered_create

        # ── Step 5: Entity extraction + linking ───────────────────────────────
        if self.config.entity_extraction_enabled:
            for cand in to_create:
                await self._step5_entity_link(cand, session_id)

        # ── Persist ──────────────────────────────────────────────────────────
        for cand in to_create:
            try:
                await self._persist_memory(cand, session_id)
                result.created += 1
            except Exception as exc:
                logger.warning("Extraction: failed to persist memory: %s", exc)
                result.errors += 1

        for cand, existing_id in to_merge:
            try:
                await self._merge_memory(cand, existing_id)
                result.merged += 1
            except Exception as exc:
                logger.warning("Extraction: failed to merge memory %s: %s", existing_id, exc)
                result.errors += 1

        logger.info(
            "Extraction complete for session %s: created=%d merged=%d skipped=%d",
            session_id, result.created, result.merged, result.skipped,
        )
        return result

    # ── Step implementations ──────────────────────────────────────────────────

    async def _step1_classify(self, messages: list[dict[str, Any]]) -> list[int]:
        """Return indices of messages worth extracting."""
        prompt = _build_classify_prompt(messages)
        try:
            response = await self._llm_fn([
                {"role": "user", "content": prompt}
            ])
            raw = _parse_json_response(response)
            return [int(i) for i in raw if isinstance(i, (int, float)) and int(i) >= 0 and int(i) < len(messages)]
        except Exception as exc:
            logger.warning("Extraction step 1 failed: %s", exc)
            # Fallback: cap to most-recent N messages to avoid swamping the pipeline
            fallback = [i for i, m in enumerate(messages) if m.get("role") in ("user", "assistant")]
            return fallback[-_MAX_FALLBACK_MESSAGES:]

    async def _step2_extract(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Extract structured memory candidates from relevant messages."""
        prompt = _build_extract_prompt(messages)
        try:
            response = await self._llm_fn([
                {"role": "user", "content": prompt}
            ])
            raw = _parse_json_response(response)
            # Validate each candidate minimally
            valid: list[dict[str, Any]] = []
            for item in raw:
                if isinstance(item, dict) and item.get("content") and item.get("memory_type"):
                    valid.append(item)
            return valid
        except Exception as exc:
            logger.warning("Extraction step 2 failed: %s", exc)
            return []

    async def _step3_dedup(
        self, candidate: dict[str, Any]
    ) -> tuple[str, str | None]:
        """Deduplicate against existing memories using embedding similarity.

        Returns: ("create"|"merge"|"skip", existing_memory_id_or_None)
        """
        try:
            from app.knowledge.embeddings import get_embedding_store
            from app.memory.store import get_memory_store
            emb_store = get_embedding_store()
            mem_store = get_memory_store()
            if emb_store is None or mem_store is None:
                return "create", None

            content = candidate.get("content", "")
            results = await emb_store.search(
                content,
                source_types=["memory"],
                limit=3,
                threshold=self.config.merge_similarity_threshold,
            )
            if not results:
                return "create", None

            top = results[0]
            if top.similarity >= self.config.dedup_similarity_threshold:
                return "skip", top.source_id
            if top.similarity >= self.config.merge_similarity_threshold:
                return "merge", top.source_id
            return "create", None
        except Exception as exc:
            logger.debug("Dedup check failed (skipping): %s", exc)
            return "create", None

    async def _step4_contradiction(
        self, candidate: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Return candidate unchanged, or None if a contradiction is unresolvable.

        TODO: Implement actual contradiction detection using embedding similarity
        and LLM comparison. Currently a no-op placeholder (TD-87).
        """
        logger.debug(
            "Contradiction detection step — not yet implemented (candidate content=%r)",
            (candidate.get("content") or "")[:80],
        )
        return candidate

    async def _step5_entity_link(
        self, candidate: dict[str, Any], session_id: str
    ) -> None:
        """Extract entity mentions and link them (creating new entities as needed)."""
        try:
            from app.memory.entity_store import get_entity_store
            entity_store = get_entity_store()
            if entity_store is None:
                return
            content = candidate.get("content", "")
            # Extract via NER (no memory_id yet — link after creation)
            from app.memory.entities import extract_entity_mentions
            mentions = extract_entity_mentions(content)
            entity_ids: list[str] = []
            for mention in mentions:
                entity = await entity_store.resolve(mention["name"])
                if entity is None:
                    entity = await entity_store.create(
                        name=mention["name"],
                        entity_type=mention["entity_type"],
                    )
                await entity_store.increment_reference(entity.id)
                entity_ids.append(entity.id)
            candidate["_entity_ids"] = entity_ids
        except Exception as exc:
            logger.debug("Entity linking failed (step 5): %s", exc)

    async def _persist_memory(
        self, candidate: dict[str, Any], session_id: str
    ) -> None:
        """Write a candidate to the memory store."""
        from app.memory.store import get_memory_store
        mem_store = get_memory_store()
        if mem_store is None:
            raise RuntimeError("MemoryStore not initialised")

        memory = await mem_store.create(
            content=candidate["content"],
            memory_type=candidate.get("memory_type", "fact"),
            confidence=float(candidate.get("confidence", 0.7)),
            tags=candidate.get("tags") or [],
            source_session_id=session_id,
        )
        # Link extracted entities
        entity_ids = candidate.get("_entity_ids") or []
        for eid in entity_ids:
            try:
                await mem_store.link_entity(memory.id, eid)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to link entity %r for memory %s",
                    eid, memory.id, exc_info=True,
                )
        # Embed the new memory
        try:
            from app.knowledge.embeddings import get_embedding_store
            emb_store = get_embedding_store()
            if emb_store:
                await emb_store.add("memory", memory.id, memory.content)
        except Exception as exc:
            logger.debug("Failed to embed extracted memory: %s", exc)

    async def _merge_memory(
        self, candidate: dict[str, Any], existing_id: str
    ) -> None:
        """Merge candidate into an existing memory (bump confidence, add tags)."""
        from app.memory.store import get_memory_store
        mem_store = get_memory_store()
        if mem_store is None:
            return
        try:
            existing = await mem_store.get(existing_id)
            new_confidence = min(1.0, float(existing.confidence) + 0.05)
            new_tags = list({*(existing.tags or []), *(candidate.get("tags") or [])})
            await mem_store.update(
                existing_id,
                confidence=new_confidence,
                tags=new_tags,
            )
        except Exception as exc:
            logger.warning("Memory merge failed for %s: %s", existing_id, exc)


# ── Singleton ─────────────────────────────────────────────────────────────────

_pipeline: ExtractionPipeline | None = None


def get_extraction_pipeline() -> ExtractionPipeline:
    """Return the process-wide extraction pipeline singleton."""
    global _pipeline
    if _pipeline is None:
        _pipeline = ExtractionPipeline()
    return _pipeline


def init_extraction_pipeline(
    llm_fn: _LLMFn | None = None,
    config: ExtractionConfig | None = None,
) -> ExtractionPipeline:
    """Initialise (or replace) the extraction pipeline singleton."""
    global _pipeline
    _pipeline = ExtractionPipeline(llm_fn=llm_fn, config=config)
    return _pipeline
