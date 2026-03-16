"""Knowledge base agent tools — kb_search and kb_list_sources (§11, Sprint 10)."""
from __future__ import annotations

import asyncio
import logging

from app.tools.registry import tool

logger = logging.getLogger(__name__)


@tool(
    description=(
        "Search one or more knowledge base sources for information relevant to a query. "
        "Returns ranked text chunks with source identifiers. "
        "Use this tool when you need to retrieve factual information from connected knowledge bases."
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "source_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of specific knowledge source IDs to search. "
                               "If omitted, searches all auto-recall sources.",
            },
            "top_k": {
                "type": "integer",
                "description": "Maximum number of results to return (default 10).",
            },
        },
        "required": ["query"],
    },
)
async def kb_search(
    query: str,
    source_ids: list[str] | None = None,
    top_k: int = 10,
) -> str:
    """Search knowledge base sources and return relevant chunks."""
    try:
        from app.knowledge.sources.registry import get_knowledge_source_registry
        registry = get_knowledge_source_registry()
    except RuntimeError:
        return "Knowledge base registry is not available."

    try:
        if source_ids:
            chunks = await registry.search(
                query=query,
                source_ids=source_ids,
                agent_id=None,
                top_k=top_k,
            )
        else:
            chunks = await registry.search_auto_recall(
                query=query,
                agent_id=None,
                top_k=top_k,
            )
    except Exception as exc:
        logger.error("kb_search failed: %s", exc)
        return f"Knowledge base search failed: {exc}"

    if not chunks:
        return "No relevant results found in the knowledge base."

    lines = [f"Found {len(chunks)} result(s):"]
    for i, chunk in enumerate(chunks, 1):
        src = getattr(chunk, "source_id", "unknown")
        score = getattr(chunk, "score", 0.0)
        content = getattr(chunk, "content", "")
        lines.append(f"\n[{i}] Source: {src} (score={score:.3f})")
        lines.append(content)

    return "\n".join(lines)


@tool(
    description=(
        "List all registered knowledge base sources and their current status. "
        "Returns source names, descriptions, backends, and availability. "
        "Use this to discover what knowledge bases are available before searching."
    ),
    safety="read_only",
    parameters={
        "type": "object",
        "properties": {
            "status_filter": {
                "type": "string",
                "description": "Optional status filter: 'active', 'disabled', or 'error'.",
            },
        },
        "required": [],
    },
)
async def kb_list_sources(
    status_filter: str | None = None,
) -> str:
    """List all available knowledge base sources."""
    try:
        from app.knowledge.sources.registry import get_knowledge_source_registry
        registry = get_knowledge_source_registry()
    except RuntimeError:
        return "Knowledge base registry is not available."

    try:
        sources = await registry.list(
            status=status_filter,
        )
    except Exception as exc:
        logger.error("kb_list_sources failed: %s", exc)
        return f"Failed to list knowledge sources: {exc}"

    if not sources:
        return "No knowledge sources registered."

    lines = [f"Knowledge Sources ({len(sources)} total):"]
    for src in sources:
        auto = " [auto-recall]" if src.auto_recall else ""
        lines.append(
            f"  - {src.name} (id={src.source_id}, backend={src.backend}, "
            f"status={src.status}{auto})"
        )
        if src.description:
            lines.append(f"    {src.description}")

    return "\n".join(lines)
