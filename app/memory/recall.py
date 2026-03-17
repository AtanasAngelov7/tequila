"""Recall Pipeline — §5.6 three-stage memory and knowledge retrieval.

Stage 1 (session init): always-recall + pinned memories → ``memory_always`` str.
Stage 2 (per-turn):     embed user message → search memories + vault + entity
                         expansion + KB federation → ``memory_recall`` + ``knowledge_context``.
Stage 3 (background):   async entity graph traversal + access metadata bump.

Call ``init_recall_pipeline(config)`` once at startup, then grab the singleton
with ``get_recall_pipeline()``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────


class RecallConfig(BaseModel):
    """Runtime tuning knobs for the recall pipeline (§5.6)."""

    always_recall_types: list[str] = Field(
        default=["identity", "preference"],
        description="Memory types always injected at session init.",
    )
    max_always_recall_tokens: int = 500
    max_per_turn_results: int = 15
    max_per_turn_tokens: int = 2_000
    entity_expansion_hops: int = 1
    entity_match_bonus: float = 0.2
    similarity_threshold: float = 0.65
    kb_top_k: int = 5
    prefetch_enabled: bool = True


# ── Helpers ───────────────────────────────────────────────────────────────────


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (4 UTF-8 bytes ≈ 1 token)."""
    return max(1, len(text.encode("utf-8")) // 4)


def _format_memory_block(rows: list[dict]) -> str:
    """Render a list of memory dicts to a human-readable block."""
    parts: list[str] = []
    for r in rows:
        content = r.get("content", "")
        mem_type = r.get("memory_type", "")
        confidence = r.get("confidence", 1.0)
        line = f"- [{mem_type}] {content}"
        if confidence < 0.8:
            line += f" (confidence={confidence:.2f})"
        parts.append(line)
    return "\n".join(parts)


def _format_knowledge_block(chunks: list) -> str:
    """Render KnowledgeChunk list to the spec §5.6 format."""
    if not chunks:
        return ""
    parts: list[str] = []
    parts.append("## Knowledge Sources")
    for chunk in chunks:
        src = getattr(chunk, "source_id", "unknown")
        content = getattr(chunk, "content", "")
        parts.append(f"[{src}] {content}")
    return "\n".join(parts)


# ── Pipeline ──────────────────────────────────────────────────────────────────


class RecallPipeline:
    """Three-stage recall pipeline (§5.6).

    Parameters
    ----------
    config:
        Tuning configuration.
    """

    def __init__(self, config: RecallConfig | None = None) -> None:
        self._config = config or RecallConfig()

    # ── Stage 1 ───────────────────────────────────────────────────────────────

    async def load_always_recall(
        self,
        session_id: str,
        agent_id: str | None = None,
    ) -> tuple[str, list[dict]]:
        """Stage 1: load always-recall memories for session initialisation.

        Returns a tuple of:
        - formatted string ready for ``AssemblyContext.memory_always``
        - raw list of memory dicts for deduplication in Stage 2 (TD-52)
        """
        cfg = self._config
        rows: list[dict] = []

        try:
            from app.memory.store import get_memory_store
            store = get_memory_store()

            # a) always_recall flag — fetch by memory_type
            for mem_type in cfg.always_recall_types:
                results = await store.list(
                    memory_type=mem_type,
                    agent_id=agent_id,
                    limit=20,
                )
                for r in results:
                    rows.append({
                        "id": r.id,
                        "content": r.content,
                        "memory_type": r.memory_type,
                        "confidence": r.confidence,
                    })

            # b) always_recall=True flag
            always = await store.list(
                always_recall_only=True,
                agent_id=agent_id,
                limit=20,
            )
            for r in always:
                if not any(row["id"] == r.id for row in rows):
                    rows.append({
                        "id": r.id,
                        "content": r.content,
                        "memory_type": r.memory_type,
                        "confidence": r.confidence,
                    })

        except Exception as exc:
            logger.warning("load_always_recall failed: %s", exc)
            return "", []

        if not rows:
            return "", []

        block = _format_memory_block(rows)
        # Trim to token budget
        tokens = _estimate_tokens(block)
        if tokens > cfg.max_always_recall_tokens:
            approx_chars = cfg.max_always_recall_tokens * 4
            block = block[:approx_chars]

        return block, rows

    # ── Stage 2 ───────────────────────────────────────────────────────────────

    async def recall_for_turn(
        self,
        user_message: str,
        session_id: str,
        agent_id: str | None = None,
        always_recall_content: str = "",
        always_memories: list[dict] | None = None,
    ) -> tuple[str, str]:
        """Stage 2: per-turn recall.

        Embeds the user message and retrieves relevant memories + knowledge.

        Parameters
        ----------
        always_memories:
            Raw list of always-recall memory dicts from Stage 1 (TD-52: used for
            exact-string deduplication instead of substring check on formatted block).

        Returns
        -------
        (memory_recall_str, knowledge_context_str)
        """
        cfg = self._config
        candidates: list[dict] = []

        # 2a — Semantic memory search
        try:
            from app.knowledge.embeddings import get_embedding_store
            emb_store = get_embedding_store()
            emb_results = await emb_store.search(
                user_message,
                source_types=["memory"],
                limit=cfg.max_per_turn_results,
                threshold=cfg.similarity_threshold,
            )

            from app.memory.store import get_memory_store
            mem_store = get_memory_store()
            for r in emb_results:
                obj_id = r.source_id
                if not obj_id:
                    continue
                try:
                    mem = await mem_store.get(obj_id)
                except Exception:
                    continue
                score = float(r.similarity)
                candidates.append({
                    "id": mem.id,
                    "content": mem.content,
                    "memory_type": mem.memory_type,
                    "confidence": mem.confidence,
                    "_score": score,
                })
        except Exception as exc:
            logger.debug("Semantic memory search failed: %s", exc)

        # 2b — FTS fallback (if semantic returned nothing)
        if not candidates:
            try:
                from app.memory.store import get_memory_store
                mem_store = get_memory_store()
                fts_results = await mem_store.list(
                    agent_id=agent_id,
                    search=user_message[:200],  # LIKE query
                    limit=cfg.max_per_turn_results,
                )
                for r in fts_results:
                    candidates.append({
                        "id": r.id,
                        "content": r.content,
                        "memory_type": r.memory_type,
                        "confidence": r.confidence,
                        "_score": r.confidence,
                    })
            except Exception as exc:
                logger.debug("FTS memory search failed: %s", exc)

        # 2c — Entity expansion
        try:
            candidates = await self._entity_expand(user_message, candidates, agent_id, cfg)
        except Exception as exc:
            logger.debug("Entity expansion failed: %s", exc)

        # 2d — Deduplicate against always_recall content (TD-52: exact set membership)
        candidates = _dedup_against_always(candidates, always_memories or [])

        # 2e — Score, rank, budget-fit
        candidates.sort(key=lambda c: c.get("_score", 0.0), reverse=True)
        candidates = candidates[: cfg.max_per_turn_results]

        memory_block = _format_memory_block(candidates)
        if _estimate_tokens(memory_block) > cfg.max_per_turn_tokens:
            memory_block = memory_block[: cfg.max_per_turn_tokens * 4]

        # 2f — KB federation
        knowledge_block = ""
        try:
            from app.knowledge.sources.registry import get_knowledge_source_registry
            kb_reg = get_knowledge_source_registry()
            chunks = await kb_reg.search_auto_recall(
                query=user_message,
                agent_id=agent_id or "",
                top_k=cfg.kb_top_k,
            )
            knowledge_block = _format_knowledge_block(chunks)
        except Exception as exc:
            logger.debug("KB federation failed: %s", exc)

        return memory_block, knowledge_block

    async def _entity_expand(
        self,
        user_message: str,
        candidates: list[dict],
        agent_id: str | None,
        cfg: RecallConfig,
    ) -> list[dict]:
        """Expand candidates with entity-linked memories."""
        from app.memory.entity_store import get_entity_store
        from app.memory.entities import extract_entity_mentions
        from app.memory.store import get_memory_store
        from app.exceptions import NotFoundError

        mentions = extract_entity_mentions(user_message)
        if not mentions:
            return candidates

        entity_store = get_entity_store()
        mem_store = get_memory_store()
        existing_ids = {c["id"] for c in candidates}

        for mention_dict in mentions[:5]:  # cap to 5 entities
            mention_name = mention_dict.get("name", "")
            if not mention_name:
                continue
            entities = await entity_store.list(search=mention_name, limit=3)
            for entity in entities:
                # Get memory IDs linked to this entity
                try:
                    memory_ids = await entity_store.get_memories(entity.id)
                except NotFoundError:
                    continue
                for memory_id in memory_ids[: cfg.entity_expansion_hops * 3]:
                    if memory_id not in existing_ids:
                        try:
                            mem = await mem_store.get(memory_id)
                        except NotFoundError:
                            continue
                        existing_ids.add(memory_id)
                        candidates.append({
                            "id": mem.id,
                            "content": mem.content,
                            "memory_type": mem.memory_type,
                            "confidence": mem.confidence,
                            "_score": mem.confidence + cfg.entity_match_bonus,
                        })

        return candidates

    # ── Stage 3 ───────────────────────────────────────────────────────────────

    async def prefetch_background(
        self,
        user_message: str,
        session_id: str,
        agent_id: str | None = None,
    ) -> None:
        """Stage 3: background async tasks (entity graph traversal, access updates).

        Must be called as ``asyncio.create_task(pipeline.prefetch_background(...))``.
        """
        if not self._config.prefetch_enabled:
            return

        try:
            from app.memory.store import get_memory_store
            mem_store = get_memory_store()

            # Bump access timestamps for recalled memories (basic implementation)
            # In a future sprint this will do full graph traversal
            logger.debug(
                "Stage 3 prefetch running for session %s (stub)", session_id
            )

            # Update last_accessed for any memory accessed this turn
            # This is a lightweight stub — full graph traversal is a future sprint
            results = await mem_store.list(
                agent_id=agent_id,
                search=user_message[:200],
                limit=5,
            )
            for mem in results:
                try:
                    # touch() bumps last_accessed + access_count (TD-62: get() no longer does this)
                    await mem_store.touch(mem.id)
                except Exception:
                    pass  # silently skip access tracking failures

        except Exception as exc:
            logger.debug("Stage 3 prefetch failed: %s", exc)


# ── Dedup helpers ─────────────────────────────────────────────────────────────


def _dedup_against_always(
    candidates: list[dict], always_memories: list[dict]
) -> list[dict]:
    """Remove candidates whose content exactly matches a memory in always_memories.

    TD-52: uses set membership (exact string equality) instead of substring
    ``in`` check against the formatted string block.
    """
    if not always_memories:
        return candidates
    always_content_set = {item.get("content", "") for item in always_memories}
    return [c for c in candidates if c.get("content", "") not in always_content_set]


# ── Singleton ─────────────────────────────────────────────────────────────────

_recall_pipeline: RecallPipeline | None = None


def init_recall_pipeline(config: RecallConfig | None = None) -> RecallPipeline:
    """Create and store the process-wide ``RecallPipeline`` singleton."""
    global _recall_pipeline
    _recall_pipeline = RecallPipeline(config=config)
    logger.info("RecallPipeline initialised.")
    return _recall_pipeline


def get_recall_pipeline() -> RecallPipeline:
    """Return the singleton ``RecallPipeline``.

    Raises ``RuntimeError`` if ``init_recall_pipeline()`` has not been called.
    """
    if _recall_pipeline is None:
        raise RuntimeError(
            "RecallPipeline not initialised — call init_recall_pipeline() at startup."
        )
    return _recall_pipeline
