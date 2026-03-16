"""Agent memory tools — 13 tools for memory and entity management (§5.7, Sprint 11).

Tools:
  memory_save         — Create a new long-term memory.
  memory_update       — Modify an existing memory.
  memory_forget       — Soft-delete a memory.
  memory_search       — Semantic + FTS search over memories.
  memory_list         — List memories with filters.
  memory_pin          — Pin a memory (always-recall).
  memory_unpin        — Unpin a memory.
  memory_link         — Link a memory to an entity (or add a graph edge).
  entity_create       — Create a new entity.
  entity_merge        — Merge two entities.
  entity_update       — Update entity metadata.
  entity_search       — Search entities.
  memory_extract_now  — Trigger immediate memory extraction on text.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from app.tools.registry import tool

logger = logging.getLogger(__name__)


# ── memory_save ───────────────────────────────────────────────────────────────

@tool(
    description=(
        "Persist a new long-term memory. "
        "Use this to store facts, preferences, tasks, relationships etc. "
        "that should be recalled in future sessions."
    ),
    safety="side_effect",
    parameters={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The information to remember.",
            },
            "memory_type": {
                "type": "string",
                "enum": ["fact", "preference", "task", "experience", "relationship",
                         "skill", "identity"],
                "description": "Category of memory (default: 'fact').",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of tags.",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence [0.0–1.0] in this memory (default: 1.0).",
            },
        },
        "required": ["content"],
    },
)
async def memory_save(
    content: str,
    memory_type: str = "fact",
    tags: list[str] | None = None,
    confidence: float = 1.0,
) -> str:
    """Create and persist a long-term memory."""
    try:
        from app.memory.store import get_memory_store
        store = get_memory_store()
    except RuntimeError:
        return "Memory store is not available."

    try:
        mem = await store.create(
            content=content,
            memory_type=memory_type,
            tags=tags or [],
            confidence=confidence,
            source_type="agent",
        )
    except Exception as exc:
        logger.error("memory_save failed: %s", exc)
        return f"Failed to save memory: {exc}"

    _audit("created", memory_id=mem.id, new_content=content)
    return f"Memory saved (id={mem.id}, type={memory_type})."


# ── memory_update ─────────────────────────────────────────────────────────────

@tool(
    description=(
        "Update the content or metadata of an existing memory by its ID. "
        "Use when you have new or corrected information about something already stored."
    ),
    safety="side_effect",
    parameters={
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "The memory ID to update.",
            },
            "content": {
                "type": "string",
                "description": "New content to replace the existing text (optional).",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Replacement tag list (optional).",
            },
            "confidence": {
                "type": "number",
                "description": "Updated confidence score (optional).",
            },
        },
        "required": ["memory_id"],
    },
)
async def memory_update(
    memory_id: str,
    content: str | None = None,
    tags: list[str] | None = None,
    confidence: float | None = None,
) -> str:
    """Update an existing memory."""
    try:
        from app.memory.store import get_memory_store
        store = get_memory_store()
    except RuntimeError:
        return "Memory store is not available."

    if content is None and tags is None and confidence is None:
        return "Nothing to update — provide at least one of: content, tags, confidence."

    try:
        old = await store.get(memory_id)
        mem = await store.update(
            memory_id,
            content=content,
            tags=tags,
            confidence=confidence,
        )
    except Exception as exc:
        logger.error("memory_update failed: %s", exc)
        return f"Failed to update memory {memory_id}: {exc}"

    _audit(
        "updated",
        memory_id=memory_id,
        old_content=old.content if content else None,
        new_content=content,
    )
    return f"Memory {memory_id} updated."


# ── memory_forget ─────────────────────────────────────────────────────────────

@tool(
    description=(
        "Forget (soft-delete) a memory by its ID. "
        "The memory is marked as deleted but not permanently removed. "
        "Use when information is no longer relevant or was incorrect."
    ),
    safety="destructive",
    parameters={
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "The memory ID to forget.",
            },
            "reason": {
                "type": "string",
                "description": "Optional reason for forgetting.",
            },
        },
        "required": ["memory_id"],
    },
)
async def memory_forget(
    memory_id: str,
    reason: str | None = None,
) -> str:
    """Soft-delete a memory."""
    try:
        from app.memory.store import get_memory_store
        store = get_memory_store()
    except RuntimeError:
        return "Memory store is not available."

    try:
        mem = await store.get(memory_id)
        await store.soft_delete(memory_id)
    except Exception as exc:
        logger.error("memory_forget failed: %s", exc)
        return f"Failed to forget memory {memory_id}: {exc}"

    _audit("deleted", memory_id=memory_id, old_content=mem.content, reason=reason)
    return f"Memory {memory_id} forgotten."


# ── memory_search ─────────────────────────────────────────────────────────────

@tool(
    description=(
        "Search long-term memories using semantic similarity or keyword matching. "
        "Returns the most relevant memories for a query."
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to search for.",
            },
            "memory_type": {
                "type": "string",
                "description": "Filter by memory type (optional).",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results to return (default 10).",
            },
            "threshold": {
                "type": "number",
                "description": "Similarity threshold 0.0–1.0 (default 0.5).",
            },
        },
        "required": ["query"],
    },
)
async def memory_search(
    query: str,
    memory_type: str | None = None,
    limit: int = 10,
    threshold: float = 0.5,
) -> str:
    """Search memories by semantic similarity."""
    # Try embeddings first, fall back to text search
    results: list[Any] = []
    try:
        from app.knowledge.embeddings import get_embedding_store
        emb = get_embedding_store()
        hits = await emb.search(query, source_types=["memory"], limit=limit, threshold=threshold)
        # TD-101: apply memory_type post-filter on embedding results
        # EmbeddingSearchResult only has source_id; need to load the memory to check type.
        if memory_type and hits:
            from app.memory.store import get_memory_store as _ms
            mem_store = _ms()
            filtered: list[Any] = []
            for h in hits:
                try:
                    mem = await mem_store.get(h.source_id)
                    if mem.memory_type == memory_type:
                        filtered.append(h)
                except Exception:  # noqa: BLE001
                    pass
            hits = filtered
        results = hits
    except RuntimeError:
        pass
    except Exception as exc:
        logger.warning("memory_search embedding query failed: %s", exc)

    if not results:
        # Fallback: text filter via MemoryStore.list
        try:
            from app.memory.store import get_memory_store
            store = get_memory_store()
            memories = await store.list(
                memory_type=memory_type,
                search=query,
                limit=limit,
            )
            if not memories:
                return "No matching memories found."
            lines = [f"Found {len(memories)} memory(ies) (text match):"]
            for m in memories:
                lines.append(f"  [{m.id}] ({m.memory_type}) {m.content[:200]}")
            return "\n".join(lines)
        except RuntimeError:
            return "Memory store is not available."
        except Exception as exc:
            return f"Memory search failed: {exc}"

    lines = [f"Found {len(results)} memory result(s):"]
    for hit in results:
        sid = getattr(hit, "source_id", "?")
        score = getattr(hit, "score", 0.0)
        content = getattr(hit, "content", "")
        lines.append(f"  [{sid}] (score={score:.3f}) {content[:200]}")
    return "\n".join(lines)


# ── memory_list ───────────────────────────────────────────────────────────────

@tool(
    description=(
        "List stored memories with optional filters. "
        "Useful for reviewing what has been remembered."
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "memory_type": {
                "type": "string",
                "description": "Filter by type (fact, preference, task, …).",
            },
            "status": {
                "type": "string",
                "description": "Filter by status (active, archived, deleted). Default: active.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results (default 20).",
            },
        },
        "required": [],
    },
)
async def memory_list(
    memory_type: str | None = None,
    status: str = "active",
    limit: int = 20,
) -> str:
    """List memories with optional filters."""
    try:
        from app.memory.store import get_memory_store
        store = get_memory_store()
    except RuntimeError:
        return "Memory store is not available."

    try:
        memories = await store.list(memory_type=memory_type, status=status, limit=limit)
    except Exception as exc:
        return f"Failed to list memories: {exc}"

    if not memories:
        return "No memories found."

    lines = [f"{len(memories)} memory(ies) [{status}]:"]
    for m in memories:
        pinned = " [pinned]" if m.pinned else ""
        lines.append(f"  [{m.id}] ({m.memory_type}){pinned} {m.content[:120]}")
    return "\n".join(lines)


# ── memory_pin / memory_unpin ─────────────────────────────────────────────────

@tool(
    description="Pin a memory so it is always recalled regardless of decay.",
    safety="side_effect",
    parameters={
        "type": "object",
        "properties": {
            "memory_id": {"type": "string", "description": "Memory ID to pin."},
        },
        "required": ["memory_id"],
    },
)
async def memory_pin(memory_id: str) -> str:
    """Pin a memory."""
    try:
        from app.memory.store import get_memory_store
        store = get_memory_store()
        await store.update(memory_id, pinned=True)
    except RuntimeError:
        return "Memory store is not available."
    except Exception as exc:
        return f"Failed to pin memory {memory_id}: {exc}"
    _audit("pinned", memory_id=memory_id)
    return f"Memory {memory_id} pinned."


@tool(
    description="Unpin a memory, allowing normal decay to apply.",
    safety="side_effect",
    parameters={
        "type": "object",
        "properties": {
            "memory_id": {"type": "string", "description": "Memory ID to unpin."},
        },
        "required": ["memory_id"],
    },
)
async def memory_unpin(memory_id: str) -> str:
    """Unpin a memory."""
    try:
        from app.memory.store import get_memory_store
        store = get_memory_store()
        await store.update(memory_id, pinned=False)
    except RuntimeError:
        return "Memory store is not available."
    except Exception as exc:
        return f"Failed to unpin memory {memory_id}: {exc}"
    _audit("unpinned", memory_id=memory_id)
    return f"Memory {memory_id} unpinned."


# ── memory_link ───────────────────────────────────────────────────────────────

@tool(
    description=(
        "Link a memory to an entity or add a graph edge between two knowledge artifacts. "
        "Use to build explicit connections in the knowledge graph."
    ),
    safety="side_effect",
    parameters={
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "Source memory ID.",
            },
            "entity_id": {
                "type": "string",
                "description": "Entity ID to link to the memory (optional).",
            },
            "target_id": {
                "type": "string",
                "description": "Target artifact ID for graph edge (optional).",
            },
            "target_type": {
                "type": "string",
                "description": "Type of target artifact, e.g. 'memory', 'entity', 'note'.",
            },
            "edge_type": {
                "type": "string",
                "description": "Edge relation type (default: 'linked_to').",
            },
        },
        "required": ["memory_id"],
    },
)
async def memory_link(
    memory_id: str,
    entity_id: str | None = None,
    target_id: str | None = None,
    target_type: str = "memory",
    edge_type: str = "linked_to",
) -> str:
    """Link a memory to an entity or add a graph edge."""
    msgs: list[str] = []
    if entity_id:
        try:
            from app.memory.store import get_memory_store
            store = get_memory_store()
            await store.link_entity(memory_id, entity_id)
            msgs.append(f"Memory {memory_id} linked to entity {entity_id}.")
            _audit("updated", memory_id=memory_id, reason=f"linked to entity {entity_id}")
        except RuntimeError:
            msgs.append("Memory store not available.")
        except Exception as exc:
            msgs.append(f"Failed to link entity: {exc}")

    if target_id:
        try:
            from app.knowledge.graph import get_graph_store
            gs = get_graph_store()
            await gs.add_edge(
                source_id=memory_id,
                source_type="memory",
                target_id=target_id,
                target_type=target_type,
                edge_type=edge_type,
            )
            msgs.append(f"Graph edge created: memory {memory_id} → {target_type} {target_id} [{edge_type}].")
        except RuntimeError:
            msgs.append("Graph store not available.")
        except Exception as exc:
            msgs.append(f"Failed to add graph edge: {exc}")

    if not msgs:
        return "No action taken — provide entity_id and/or target_id."
    return "\n".join(msgs)


# ── entity_create ─────────────────────────────────────────────────────────────

@tool(
    description=(
        "Create a new entity (person, place, organisation, concept, etc.) "
        "in the knowledge graph."
    ),
    safety="side_effect",
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Primary name of the entity.",
            },
            "entity_type": {
                "type": "string",
                "description": "Type of entity (person, organisation, place, concept, …).",
            },
            "summary": {
                "type": "string",
                "description": "Short description of the entity.",
            },
            "aliases": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Alternative names or nicknames.",
            },
        },
        "required": ["name"],
    },
)
async def entity_create(
    name: str,
    entity_type: str = "concept",
    summary: str = "",
    aliases: list[str] | None = None,
) -> str:
    """Create a new entity."""
    try:
        from app.memory.entity_store import get_entity_store
        store = get_entity_store()
    except RuntimeError:
        return "Entity store is not available."

    try:
        entity = await store.create(
            name=name,
            entity_type=entity_type,
            summary=summary,
            aliases=aliases or [],
        )
    except Exception as exc:
        return f"Failed to create entity: {exc}"

    _audit("entity_created", entity_id=entity.entity_id)
    return f"Entity created (id={entity.entity_id}, name={entity.name}, type={entity_type})."


# ── entity_merge ──────────────────────────────────────────────────────────────

@tool(
    description=(
        "Merge two entities into one. "
        "The target entity absorbs the source's aliases and memory links; "
        "the source is soft-deleted."
    ),
    safety="side_effect",
    parameters={
        "type": "object",
        "properties": {
            "source_entity_id": {
                "type": "string",
                "description": "Entity to be merged (will be soft-deleted).",
            },
            "target_entity_id": {
                "type": "string",
                "description": "Entity to keep (absorbs the source).",
            },
            "reason": {
                "type": "string",
                "description": "Optional reason for the merge.",
            },
        },
        "required": ["source_entity_id", "target_entity_id"],
    },
)
async def entity_merge(
    source_entity_id: str,
    target_entity_id: str,
    reason: str | None = None,
) -> str:
    """Merge two entities."""
    try:
        from app.memory.entity_store import get_entity_store
        store = get_entity_store()
    except RuntimeError:
        return "Entity store is not available."

    try:
        source = await store.get(source_entity_id)
        target = await store.get(target_entity_id)

        failures: list[str] = []

        # Transfer aliases
        for alias in (source.aliases or []):
            try:
                await store.add_alias(target_entity_id, alias)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"alias '{alias}': {exc}")
                logger.warning(
                    "entity_merge: failed to transfer alias %r from %s to %s",
                    alias, source_entity_id, target_entity_id, exc_info=True,
                )

        # Re-link all memories from source → target
        # TD-49: if any re-link fails, report it and leave both entities intact
        source_memory_ids = await store.get_memories(source_entity_id)
        relink_failed = False
        for mid in source_memory_ids:
            try:
                from app.memory.store import get_memory_store
                ms = get_memory_store()
                await ms.link_entity(mid, target_entity_id)
                await ms.unlink_entity(mid, source_entity_id)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"memory '{mid}': {exc}")
                logger.warning(
                    "entity_merge: failed to re-link memory %s", mid, exc_info=True,
                )
                relink_failed = True

        if relink_failed:
            # Do not delete source — leave both alive for manual resolution
            partial_msg = "; ".join(failures)
            return (
                f"Entity merge partially failed — source entity {source_entity_id} "
                f"was NOT deleted. Failures: {partial_msg}"
            )

        # Update source to point to target (merged_into)
        await store.update(source_entity_id, merged_into=target_entity_id, status="merged")

        # Mark alias on target
        await store.add_alias(target_entity_id, source.name)

    except Exception as exc:
        logger.error("entity_merge failed: %s", exc)
        return f"Failed to merge entities: {exc}"

    _audit(
        "entity_merged",
        entity_id=source_entity_id,
        reason=reason or f"merged into {target_entity_id}",
        metadata={"survivor_id": target_entity_id},
    )
    base_msg = (
        f"Entity {source_entity_id} ({source.name}) merged into "
        f"{target_entity_id} ({target.name})."
    )
    if failures:
        return base_msg + f" Partial failures: {'; '.join(failures)}"
    return base_msg


# ── entity_update ─────────────────────────────────────────────────────────────

@tool(
    description="Update an entity's name, summary, type, or properties.",
    safety="side_effect",
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "Entity ID to update."},
            "name": {"type": "string", "description": "New primary name (optional)."},
            "summary": {"type": "string", "description": "Updated description (optional)."},
            "aliases": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Replacement alias list (optional).",
            },
        },
        "required": ["entity_id"],
    },
)
async def entity_update(
    entity_id: str,
    name: str | None = None,
    summary: str | None = None,
    aliases: list[str] | None = None,
) -> str:
    """Update an entity."""
    try:
        from app.memory.entity_store import get_entity_store
        store = get_entity_store()
        await store.update(entity_id, name=name, summary=summary, aliases=aliases)
    except RuntimeError:
        return "Entity store is not available."
    except Exception as exc:
        return f"Failed to update entity {entity_id}: {exc}"

    _audit("entity_updated", entity_id=entity_id)
    return f"Entity {entity_id} updated."


# ── entity_search ─────────────────────────────────────────────────────────────

@tool(
    description="Search entities by name, alias, or type.",
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search term."},
            "entity_type": {"type": "string", "description": "Filter by entity type."},
            "limit": {"type": "integer", "description": "Maximum results (default 10)."},
        },
        "required": ["query"],
    },
)
async def entity_search(
    query: str,
    entity_type: str | None = None,
    limit: int = 10,
) -> str:
    """Search entities by name or alias."""
    try:
        from app.memory.entity_store import get_entity_store
        store = get_entity_store()
        entities = await store.list(entity_type=entity_type, search=query, limit=limit)
    except RuntimeError:
        return "Entity store is not available."
    except Exception as exc:
        return f"Failed to search entities: {exc}"

    if not entities:
        return "No matching entities found."

    lines = [f"Found {len(entities)} entity(ies):"]
    for e in entities:
        aliases = ", ".join(e.aliases or [])
        alias_note = f" (also: {aliases})" if aliases else ""
        lines.append(f"  [{e.entity_id}] {e.name} [{e.entity_type}]{alias_note}")
        if e.summary:
            lines.append(f"    {e.summary[:100]}")
    return "\n".join(lines)


# ── memory_extract_now ────────────────────────────────────────────────────────

@tool(
    description=(
        "Immediately run memory extraction on the provided text, "
        "storing resulting memories and entity links. "
        "Useful when you have received important information outside the normal session flow."
    ),
    safety="side_effect",
    parameters={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to extract memories from.",
            },
            "session_id": {
                "type": "string",
                "description": "Session ID to associate extracted memories with (optional).",
            },
        },
        "required": ["text"],
    },
)
async def memory_extract_now(
    text: str,
    session_id: str | None = None,
) -> str:
    """Trigger immediate extraction of memories from text."""
    try:
        from app.memory.extraction import get_extraction_pipeline
        pipeline = get_extraction_pipeline()
    except RuntimeError:
        return "Extraction pipeline is not available."

    try:
        fake_messages = [{
            "role": "user",
            "content": text,
        }]
        result = await pipeline.run(
            session_id=session_id or f"direct_extract:{uuid.uuid4().hex[:12]}",
            messages=fake_messages,
        )
    except Exception as exc:
        logger.error("memory_extract_now failed: %s", exc)
        return f"Extraction failed: {exc}"

    extracted = getattr(result, "memories_created", None)
    count = len(extracted) if extracted else 0
    return f"Extraction complete: {count} memory(ies) saved from provided text."


# ── Internal audit helper ─────────────────────────────────────────────────────

def _audit(
    event_type: str,
    *,
    memory_id: str | None = None,
    entity_id: str | None = None,
    old_content: str | None = None,
    new_content: str | None = None,
    reason: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Best-effort fire-and-forget audit event (does not block the tool result)."""
    import asyncio as _asyncio

    async def _log() -> None:
        try:
            from app.memory.audit import get_memory_audit
            audit = get_memory_audit()
            await audit.log(
                event_type=event_type,
                memory_id=memory_id,
                entity_id=entity_id,
                actor="agent",
                old_content=old_content,
                new_content=new_content,
                reason=reason,
                metadata=metadata or {},
            )
        except Exception:  # noqa: BLE001
            logger.warning("Audit event failed for %s", event_type, exc_info=True)

    try:
        loop = _asyncio.get_running_loop()
        loop.create_task(_log())
    except RuntimeError:
        # No running event loop — caller is synchronous; skip the audit
        logger.debug("_audit: no running event loop; skipping audit for %s", event_type)
    except Exception:  # noqa: BLE001
        logger.warning("_audit: failed to schedule audit task for %s", event_type, exc_info=True)
