"""Knowledge graph API — edge management and graph queries (§5.11, Sprint 11).

Endpoints
---------
GET    /api/graph                      — full graph (with filters)
GET    /api/graph/stats                — graph statistics
GET    /api/graph/orphans              — nodes with no edges
GET    /api/graph/node/{id}            — node + direct edges
GET    /api/graph/node/{id}/neighborhood  — multi-hop neighbourhood
POST   /api/graph/edges                — manually add an edge
DELETE /api/graph/edges/{edge_id}      — remove an edge
POST   /api/graph/rebuild              — rebuild semantic-similarity edges
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.deps import require_gateway_token
from app.knowledge.graph import (
    GraphEdge,
    GraphStats,
    KnowledgeGraph,
    get_graph_store,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/graph",
    tags=["graph"],
    dependencies=[Depends(require_gateway_token)],
)

# TD-108: Prevent concurrent graph rebuild operations
_rebuild_lock = asyncio.Lock()


# ── Request models ────────────────────────────────────────────────────────────


class AddEdgeRequest(BaseModel):
    source_id: str
    source_type: str
    target_id: str
    target_type: str
    edge_type: str
    weight: float = 1.0
    label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)  # TD-130: no mutable default


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=dict)
async def get_full_graph(
    source_type: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    edge_type: str | None = Query(default=None),
    min_weight: float = Query(default=0.0),
    since: str | None = Query(default=None),
    limit: int = Query(default=500, le=2000),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Return a list of edges forming the knowledge graph, with optional filters."""
    gs = get_graph_store()
    edges = await gs.list_edges(
        source_type=source_type,
        target_type=target_type,
        edge_type=edge_type,
        min_weight=min_weight,
        since=since,
        limit=limit,
        offset=offset,
    )

    # Summarise distinct nodes from edge endpoints
    node_ids: set[str] = set()
    for e in edges:
        node_ids.add(e.source_id)
        node_ids.add(e.target_id)

    return {
        "total_nodes": len(node_ids),
        "total_edges": len(edges),
        "edges": [_edge_dict(e) for e in edges],
    }


@router.get("/stats", response_model=dict)
async def get_graph_stats() -> dict:
    """Return aggregate knowledge-graph statistics."""
    gs = get_graph_store()
    stats = await gs.get_stats()
    return stats.model_dump()


@router.get("/orphans", response_model=dict)
async def get_orphans(
    limit: int = Query(default=100, le=500),
) -> dict:
    """Return a list of memory/entity IDs that appear in no graph edges (TD-100).

    Uses SQL subqueries instead of loading all edges into Python.
    """
    gs = get_graph_store()

    orphans: list[str] = []

    # Memory orphans via SQL — no Python-side set operations (TD-100)
    try:
        async with gs._db.execute(
            """
            SELECT m.id
            FROM memory_extracts m
            WHERE m.status = 'active'
              AND m.id NOT IN (
                  SELECT source_id FROM graph_edges
                  UNION
                  SELECT target_id FROM graph_edges
              )
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
        orphans.extend(r[0] for r in rows)
    except Exception:
        pass

    # Entity orphans if limit not reached
    remaining = limit - len(orphans)
    if remaining > 0:
        try:
            async with gs._db.execute(
                """
                SELECT e.id
                FROM entities e
                WHERE e.status = 'active'
                  AND e.id NOT IN (
                      SELECT source_id FROM graph_edges
                      UNION
                      SELECT target_id FROM graph_edges
                  )
                LIMIT ?
                """,
                (remaining,),
            ) as cur:
                rows = await cur.fetchall()
            orphans.extend(r[0] for r in rows if r[0] not in orphans)
        except Exception:
            pass

    return {"orphan_ids": orphans[:limit], "count": len(orphans[:limit])}


@router.get("/node/{node_id}", response_model=dict)
async def get_node(
    node_id: str,
    edge_type: str | None = Query(default=None),
    min_weight: float = Query(default=0.0),
) -> dict:
    """Return a node's direct neighbours (1-hop)."""
    gs = get_graph_store()
    edge_types = [edge_type] if edge_type else None
    edges = await gs.get_neighbors(
        node_id,
        edge_types=edge_types,
        min_weight=min_weight,
        limit=200,
    )
    neighbour_ids = {e.target_id if e.source_id == node_id else e.source_id for e in edges}
    return {
        "node_id": node_id,
        "degree": len(edges),
        "neighbours": list(neighbour_ids),
        "edges": [_edge_dict(e) for e in edges],
    }


@router.get("/node/{node_id}/neighborhood", response_model=dict)
async def get_neighborhood(
    node_id: str,
    depth: int = Query(default=2, ge=1, le=5),
    edge_type: str | None = Query(default=None),
    min_weight: float = Query(default=0.0),
    max_nodes: int = Query(default=200, le=500),
) -> dict:
    """Return the multi-hop neighbourhood (BFS) around a node."""
    gs = get_graph_store()
    edge_types = [edge_type] if edge_type else None
    edges = await gs.get_neighborhood(
        node_id,
        depth=depth,
        edge_types=edge_types,
        min_weight=min_weight,
        max_nodes=max_nodes,
    )
    node_ids: set[str] = {node_id}
    for e in edges:
        node_ids.add(e.source_id)
        node_ids.add(e.target_id)

    return {
        "center": node_id,
        "depth": depth,
        "total_nodes": len(node_ids),
        "total_edges": len(edges),
        "node_ids": list(node_ids),
        "edges": [_edge_dict(e) for e in edges],
    }


@router.post("/edges", response_model=dict, status_code=201)
async def add_edge(body: AddEdgeRequest) -> dict:
    """Manually add an edge to the knowledge graph."""
    gs = get_graph_store()
    edge = await gs.add_edge(
        source_id=body.source_id,
        source_type=body.source_type,
        target_id=body.target_id,
        target_type=body.target_type,
        edge_type=body.edge_type,
        weight=body.weight,
        label=body.label,
        metadata=body.metadata,
    )
    return _edge_dict(edge)


@router.delete("/edges/{edge_id}", status_code=204)
async def delete_edge(edge_id: int) -> None:
    """Remove an edge by ID."""
    gs = get_graph_store()
    await gs.delete_edge(edge_id)


@router.post("/rebuild", response_model=dict)
async def rebuild_graph(
    threshold: float = Query(default=0.82, ge=0.0, le=1.0),
) -> dict:
    """Rebuild semantic-similarity edges in the knowledge graph.

    This is a potentially expensive operation.  Results are upserted — existing
    edges are overwritten with updated similarity weights.  Only one rebuild may
    run at a time; concurrent requests receive HTTP 429.
    """
    # TD-108: Guard against concurrent rebuilds
    if _rebuild_lock.locked():
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="Rebuild already in progress")
    async with _rebuild_lock:
        gs = get_graph_store()
        count = await gs.rebuild_semantic_edges(threshold=threshold)
    return {"edges_upserted": count, "threshold": threshold}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _edge_dict(edge: GraphEdge) -> dict[str, Any]:
    return {
        "id": edge.id,
        "source_id": edge.source_id,
        "source_type": edge.source_type,
        "target_id": edge.target_id,
        "target_type": edge.target_type,
        "edge_type": edge.edge_type,
        "weight": edge.weight,
        "label": edge.label,
        "metadata": edge.metadata,
        "created_at": edge.created_at,
    }
