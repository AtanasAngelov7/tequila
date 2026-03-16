"""Knowledge graph — edge store and graph query engine (§5.11, Sprint 11).

The knowledge graph connects all knowledge artifacts:
- Nodes: notes, memories, entities, agents, sessions, files, tags — resolved
  dynamically from their respective source tables at query time.
- Edges: stored in ``graph_edges`` table.

Key responsibilities:
1. ``GraphStore`` — persistent edge CRUD + graph queries.
2. ``rebuild_semantic_edges`` — periodic similarity-based edge builder.
3. ``add_*`` helpers called by other pipelines (extraction, consolidation, vault).

Singletons:
- ``init_graph_store(db) → GraphStore``
- ``get_graph_store() → GraphStore``
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

import aiosqlite
from pydantic import BaseModel, Field

from app.db.connection import write_transaction
from app.db.schema import row_to_dict

logger = logging.getLogger(__name__)

# ── Node type + edge type constants ──────────────────────────────────────────

NODE_TYPES = frozenset({
    "note", "memory", "entity", "agent", "session", "file", "tag",
})

EDGE_TYPES = frozenset({
    "wiki_link",
    "extracted_from",
    "references",
    "semantic_similar",
    "tagged_with",
    "authored_by",
    "mentioned_in",
    "promotes_to",
    "linked_to",
    "entity_relationship",
    "merged_from",
    "derived_from",
})


# ── Data models ───────────────────────────────────────────────────────────────


class GraphNode(BaseModel):
    """A node in the knowledge graph, resolved from its source table (§5.11)."""

    id: str
    """The source-table primary key."""

    node_type: str
    """e.g. ``'note'``, ``'memory'``, ``'entity'``."""

    label: str
    """Human-readable display name."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Type-specific fields (e.g. ``memory_type``, ``entity_type``)."""

    created_at: str = ""
    """ISO timestamp string when the node was created."""

    updated_at: str | None = None
    """ISO timestamp string when the node was last modified."""


class GraphEdge(BaseModel):
    """A typed directed edge in the knowledge graph (§5.11)."""

    id: int | None = None
    """AUTOINCREMENT primary key; ``None`` before insertion."""

    source_id: str
    """Source node ID."""

    source_type: str
    """Source node type."""

    target_id: str
    """Target node ID."""

    target_type: str
    """Target node type."""

    edge_type: str
    """Relation type (see ``EDGE_TYPES``)."""

    weight: float = 1.0
    """Relation strength / similarity score."""

    label: str | None = None
    """Optional display label (e.g. ``'works_at'`` for entity relationships)."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Additional context (similarity scores, extraction session, etc.)."""

    created_at: str = ""
    """ISO creation timestamp."""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "GraphEdge":
        """Deserialise a DB row into a ``GraphEdge``."""
        meta_raw = row.get("metadata", "{}")
        try:
            meta = json.loads(meta_raw) if meta_raw else {}
        except (ValueError, TypeError):
            meta = {}
        return cls(
            id=row.get("id"),
            source_id=row["source_id"],
            source_type=row["source_type"],
            target_id=row["target_id"],
            target_type=row["target_type"],
            edge_type=row["edge_type"],
            weight=float(row.get("weight", 1.0)),
            label=row.get("label"),
            metadata=meta,
            created_at=row.get("created_at", ""),
        )


class GraphStats(BaseModel):
    """Aggregate statistics about the knowledge graph (§5.11)."""

    total_nodes: int = 0
    """Total distinct node IDs appearing in at least one edge."""

    total_edges: int = 0
    """Total edges (may include both directions)."""

    node_counts: dict[str, int] = Field(default_factory=dict)
    """Edge counts by node type (approximate — based on endpoint types)."""

    edge_counts: dict[str, int] = Field(default_factory=dict)
    """Edge counts per edge type."""

    orphan_count: int = 0
    """Estimate of nodes with zero edges (computed externally)."""

    most_connected: list[str] = Field(default_factory=list)
    """Top-10 node IDs by number of incident edges."""


class KnowledgeGraph(BaseModel):
    """Container for a graph query result: nodes + edges + stats (§5.11)."""

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    stats: GraphStats = Field(default_factory=GraphStats)


# ── GraphStore ────────────────────────────────────────────────────────────────


class GraphStore:
    """Persistent edge store and graph query engine (§5.11).

    Nodes are *not* stored here — they are resolved from their source tables
    at query time via ``_resolve_node()``.
    """

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # ── Edge CRUD ─────────────────────────────────────────────────────────────

    async def add_edge(
        self,
        *,
        source_id: str,
        source_type: str,
        target_id: str,
        target_type: str,
        edge_type: str,
        weight: float = 1.0,
        label: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> GraphEdge:
        """Insert or replace an edge (UNIQUE constraint on source/target/edge_type)."""
        now = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(metadata or {})

        async with write_transaction(self._db):
            await self._db.execute(
                """
                INSERT INTO graph_edges
                    (source_id, source_type, target_id, target_type,
                     edge_type, weight, label, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, target_id, edge_type)
                DO UPDATE SET
                    weight = excluded.weight,
                    label = excluded.label,
                    metadata = excluded.metadata
                """,
                (
                    source_id, source_type, target_id, target_type,
                    edge_type, weight, label, meta_json, now,
                ),
            )
        # Fetch the inserted/updated row
        edge = await self.get_edge(source_id=source_id, target_id=target_id, edge_type=edge_type)
        return edge

    async def get_edge(
        self,
        *,
        source_id: str,
        target_id: str,
        edge_type: str,
    ) -> GraphEdge:
        """Retrieve a specific edge by unique composite key."""
        async with self._db.execute(
            "SELECT * FROM graph_edges WHERE source_id=? AND target_id=? AND edge_type=?",
            (source_id, target_id, edge_type),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            from app.exceptions import NotFoundError
            raise NotFoundError(f"Edge not found: {source_id!r}→{target_id!r} [{edge_type}]")
        return GraphEdge.from_row(row_to_dict(row))

    async def delete_edge(self, edge_id: int) -> None:
        """Delete an edge by its AUTOINCREMENT id."""
        async with write_transaction(self._db):
            await self._db.execute(
                "DELETE FROM graph_edges WHERE id = ?", (edge_id,)
            )

    async def delete_edges_for_node(self, node_id: str) -> int:
        """Remove all edges where *node_id* appears as source or target.

        Returns the number of deleted edges.
        """
        async with write_transaction(self._db):
            await self._db.execute(
                "DELETE FROM graph_edges WHERE source_id = ? OR target_id = ?",
                (node_id, node_id),
            )
            async with self._db.execute("SELECT changes()") as cur:
                row = await cur.fetchone()
        return row[0] if row else 0

    # ── Graph queries ─────────────────────────────────────────────────────────

    async def get_neighbors(
        self,
        node_id: str,
        *,
        edge_types: list[str] | None = None,
        direction: str = "both",   # "out" | "in" | "both"
        min_weight: float = 0.0,
        limit: int = 200,
    ) -> list[GraphEdge]:
        """Return edges directly attached to *node_id* (1-hop neighbourhood)."""
        clauses: list[str] = ["weight >= ?"]
        params: list[Any] = [min_weight]

        if direction == "out":
            clauses.append("source_id = ?")
            params.append(node_id)
        elif direction == "in":
            clauses.append("target_id = ?")
            params.append(node_id)
        else:
            clauses.append("(source_id = ? OR target_id = ?)")
            params += [node_id, node_id]

        if edge_types:
            placeholders = ",".join("?" * len(edge_types))
            clauses.append(f"edge_type IN ({placeholders})")
            params.extend(edge_types)

        where = " AND ".join(clauses)
        params.append(limit)

        async with self._db.execute(
            f"SELECT * FROM graph_edges WHERE {where} ORDER BY weight DESC LIMIT ?",
            params,
        ) as cur:
            rows = await cur.fetchall()
        return [GraphEdge.from_row(row_to_dict(r)) for r in rows]

    async def get_neighborhood(
        self,
        center_id: str,
        depth: int = 2,
        *,
        edge_types: list[str] | None = None,
        min_weight: float = 0.0,
        max_nodes: int = 200,
    ) -> list[GraphEdge]:
        """Return all edges within *depth* hops of *center_id* (BFS).

        Returns up to ``max_nodes`` unique node IDs' incident edges.
        """
        visited: set[str] = {center_id}
        frontier: set[str] = {center_id}
        all_edges: dict[int, GraphEdge] = {}

        for _ in range(depth):
            if not frontier or len(visited) >= max_nodes:
                break
            # Collect all direct edges for the frontier
            tasks = [
                self.get_neighbors(
                    nid,
                    edge_types=edge_types,
                    min_weight=min_weight,
                    limit=50,
                )
                for nid in list(frontier)
            ]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            next_frontier: set[str] = set()
            for result in batch_results:
                if isinstance(result, BaseException):
                    continue
                for edge in result:
                    if edge.id is not None:
                        all_edges[edge.id] = edge
                    for nid in (edge.source_id, edge.target_id):
                        if nid not in visited and len(visited) < max_nodes:
                            visited.add(nid)
                            next_frontier.add(nid)
            frontier = next_frontier

        return list(all_edges.values())

    async def list_edges(
        self,
        *,
        source_type: str | None = None,
        target_type: str | None = None,
        edge_type: str | None = None,
        min_weight: float = 0.0,
        since: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[GraphEdge]:
        """List edges with optional filters."""
        clauses: list[str] = ["weight >= ?"]
        params: list[Any] = [min_weight]

        if source_type:
            clauses.append("source_type = ?")
            params.append(source_type)
        if target_type:
            clauses.append("target_type = ?")
            params.append(target_type)
        if edge_type:
            clauses.append("edge_type = ?")
            params.append(edge_type)
        if since:
            clauses.append("created_at >= ?")
            params.append(since)

        where = " AND ".join(clauses)
        params += [limit, offset]

        async with self._db.execute(
            f"SELECT * FROM graph_edges WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        ) as cur:
            rows = await cur.fetchall()
        return [GraphEdge.from_row(row_to_dict(r)) for r in rows]

    async def get_stats(self) -> GraphStats:
        """Compute graph statistics from the edges table."""
        async with self._db.execute("SELECT COUNT(*) FROM graph_edges") as cur:
            total_edges = (await cur.fetchone())[0]  # type: ignore[index]

        async with self._db.execute(
            "SELECT edge_type, COUNT(*) FROM graph_edges GROUP BY edge_type"
        ) as cur:
            rows = await cur.fetchall()
        edge_counts = {r[0]: r[1] for r in rows}

        # Approximate total unique nodes from source+target
        async with self._db.execute(
            "SELECT COUNT(*) FROM (SELECT source_id AS nid FROM graph_edges UNION SELECT target_id AS nid FROM graph_edges)"
        ) as cur:
            total_nodes = (await cur.fetchone())[0]

        # Most connected nodes (by degree)
        async with self._db.execute(
            """
            SELECT nid, COUNT(*) AS degree
            FROM (
                SELECT source_id AS nid FROM graph_edges
                UNION ALL
                SELECT target_id AS nid FROM graph_edges
            )
            GROUP BY nid
            ORDER BY degree DESC
            LIMIT 10
            """
        ) as cur:
            mc_rows = await cur.fetchall()
        most_connected = [r[0] for r in mc_rows]

        return GraphStats(
            total_nodes=total_nodes,
            total_edges=total_edges,
            edge_counts=edge_counts,
            most_connected=most_connected,
        )

    # ── Semantic similarity edge builder ─────────────────────────────────────

    async def rebuild_semantic_edges(
        self,
        *,
        threshold: float = 0.82,
        batch_size: int = 50,
        node_types: list[str] | None = None,
    ) -> int:
        """Compute pairwise embedding similarity and upsert ``semantic_similar`` edges.

        Only processes nodes whose embeddings are indexed in ``EmbeddingStore``.
        Returns the number of edges created/updated.
        """
        try:
            from app.knowledge.embeddings import get_embedding_store
            emb_store = get_embedding_store()
        except RuntimeError:
            logger.warning("GraphStore: EmbeddingStore not available, skipping semantic edge build.")
            return 0

        target_types = node_types or ["memory", "entity", "note"]
        created = 0

        for source_type in target_types:
            try:
                async with self._db.execute(
                    "SELECT source_id FROM embeddings WHERE source_type = ?",
                    (source_type,),
                ) as cur:
                    rows = await cur.fetchall()
                node_ids = [row_to_dict(r)["source_id"] for r in rows]
            except Exception as exc:  # noqa: BLE001
                logger.warning("GraphStore: failed to fetch %s embedding IDs: %s", source_type, exc)
                continue

            # Collect edges to insert, then batch-insert per §20.5 (TD-107)
            edges_to_insert: list[tuple] = []

            for i in range(0, len(node_ids), batch_size):
                batch = node_ids[i : i + batch_size]
                for nid in batch:
                    try:
                        results = await emb_store.search(
                            nid,
                            source_types=[source_type],
                            limit=10,
                            threshold=threshold,
                        )
                        for hit in results:
                            if hit.source_id == nid:
                                continue
                            edges_to_insert.append((
                                nid, source_type, hit.source_id, source_type,
                                "semantic_similar", hit.similarity,
                                json.dumps({"similarity": hit.similarity}),
                            ))
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("Semantic edge skip %s: %s", nid, exc)

            # Batch upsert collected edges in groups of 500 (TD-107)
            BATCH_INSERT = 500
            now = datetime.now(timezone.utc).isoformat()
            for i in range(0, len(edges_to_insert), BATCH_INSERT):
                chunk = edges_to_insert[i : i + BATCH_INSERT]
                try:
                    async with write_transaction(self._db):
                        await self._db.executemany(
                            """
                            INSERT INTO graph_edges
                                (source_id, source_type, target_id, target_type,
                                 edge_type, weight, metadata, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(source_id, target_id, edge_type)
                            DO UPDATE SET
                                weight   = excluded.weight,
                                metadata = excluded.metadata
                            """,
                            [(*e, now) for e in chunk],
                        )
                    created += len(chunk)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("GraphStore: batch edge insert failed: %s", exc)

        logger.info("GraphStore: rebuilt semantic edges, %d upserted.", created)
        return created

    # ── Shortest path ─────────────────────────────────────────────────────────

    async def shortest_path(
        self,
        from_id: str,
        to_id: str,
        max_depth: int = 6,
    ) -> list[str]:
        """BFS shortest path between two node IDs.

        Returns the list of node IDs from *from_id* to *to_id* (inclusive),
        or an empty list if no path is found within *max_depth*.
        """
        if from_id == to_id:
            return [from_id]

        visited: set[str] = {from_id}
        queue: deque[list[str]] = deque([[from_id]])  # O(1) popleft (TD-128)

        for _ in range(max_depth):
            if not queue:
                break
            path = queue.popleft()  # O(1) — was queue.pop(0) which is O(n)
            current = path[-1]
            edges = await self.get_neighbors(current, limit=100)
            for edge in edges:
                neighbor = edge.target_id if edge.source_id == current else edge.source_id
                if neighbor == to_id:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])

        return []  # no path found


# ── Module-level singleton ────────────────────────────────────────────────────

_graph_store: GraphStore | None = None


def init_graph_store(db: aiosqlite.Connection) -> GraphStore:
    """Initialise and register the global GraphStore singleton."""
    global _graph_store  # noqa: PLW0603
    _graph_store = GraphStore(db)
    logger.info("GraphStore initialised.")
    return _graph_store


def get_graph_store() -> GraphStore:
    """Return the global GraphStore singleton.

    Raises ``RuntimeError`` if not yet initialised.
    """
    if _graph_store is None:
        raise RuntimeError("GraphStore not initialised.  Check app lifespan.")
    return _graph_store
