"""Sprint 11 — Unit tests for GraphStore (§5.11)."""
from __future__ import annotations

import pytest


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
async def gs(migrated_db):
    """Initialise a fresh GraphStore."""
    from app.knowledge.graph import GraphStore
    return GraphStore(migrated_db)


# ── add_edge / get_edge ───────────────────────────────────────────────────────


async def test_add_edge_returns_edge(gs):
    """add_edge() returns a GraphEdge with all fields populated."""
    edge = await gs.add_edge(
        source_id="m001",
        source_type="memory",
        target_id="e001",
        target_type="entity",
        edge_type="extracted_from",
        weight=0.9,
    )
    assert edge.id is not None
    assert edge.source_id == "m001"
    assert edge.target_id == "e001"
    assert edge.edge_type == "extracted_from"
    assert abs(edge.weight - 0.9) < 0.001


async def test_add_edge_upsert_updates_weight(gs):
    """Adding the same edge twice updates the weight (UPSERT semantics)."""
    await gs.add_edge(
        source_id="m1", source_type="memory",
        target_id="m2", target_type="memory",
        edge_type="semantic_similar", weight=0.85,
    )
    updated = await gs.add_edge(
        source_id="m1", source_type="memory",
        target_id="m2", target_type="memory",
        edge_type="semantic_similar", weight=0.95,
    )
    assert abs(updated.weight - 0.95) < 0.001


async def test_get_edge_raises_for_missing(gs):
    """get_edge() raises an error for non-existent composite key."""
    from app.exceptions import NotFoundError
    with pytest.raises((NotFoundError, Exception)):
        await gs.get_edge(source_id="x", target_id="y", edge_type="linked_to")


# ── delete_edge ───────────────────────────────────────────────────────────────


async def test_delete_edge_removes_edge(gs):
    """delete_edge() removes the edge by id."""
    edge = await gs.add_edge(
        source_id="del1", source_type="note",
        target_id="del2", target_type="note",
        edge_type="wiki_link",
    )
    await gs.delete_edge(edge.id)
    edges = await gs.get_neighbors("del1")
    assert not any(e.id == edge.id for e in edges)


async def test_delete_edges_for_node(gs):
    """delete_edges_for_node() removes all edges incident on the node."""
    await gs.add_edge(
        source_id="gone", source_type="memory",
        target_id="other1", target_type="memory",
        edge_type="linked_to",
    )
    await gs.add_edge(
        source_id="other2", source_type="memory",
        target_id="gone", target_type="memory",
        edge_type="linked_to",
    )
    count = await gs.delete_edges_for_node("gone")
    assert count >= 2
    assert await gs.get_neighbors("gone") == []


# ── get_neighbors ─────────────────────────────────────────────────────────────


async def test_get_neighbors_both_directions(gs):
    """get_neighbors() returns edges where the node is source OR target."""
    await gs.add_edge(
        source_id="hub", source_type="entity",
        target_id="spoke1", target_type="memory",
        edge_type="references",
    )
    await gs.add_edge(
        source_id="spoke2", source_type="memory",
        target_id="hub", target_type="entity",
        edge_type="mentioned_in",
    )
    edges = await gs.get_neighbors("hub")
    edge_ids = {(e.source_id, e.target_id) for e in edges}
    assert ("hub", "spoke1") in edge_ids
    assert ("spoke2", "hub") in edge_ids


async def test_get_neighbors_weight_filter(gs):
    """get_neighbors() respects min_weight filter."""
    await gs.add_edge(
        source_id="wf", source_type="memory",
        target_id="wt1", target_type="memory",
        edge_type="semantic_similar", weight=0.9,
    )
    await gs.add_edge(
        source_id="wf", source_type="memory",
        target_id="wt2", target_type="memory",
        edge_type="semantic_similar", weight=0.3,
    )
    edges = await gs.get_neighbors("wf", min_weight=0.8)
    assert all(e.weight >= 0.8 for e in edges)
    assert len(edges) == 1


# ── get_neighborhood ─────────────────────────────────────────────────────────


async def test_get_neighborhood_depth_1(gs):
    """1-hop neighborhood → same as get_neighbors."""
    await gs.add_edge(
        source_id="n0", source_type="memory",
        target_id="n1", target_type="memory",
        edge_type="linked_to",
    )
    await gs.add_edge(
        source_id="n1", source_type="memory",
        target_id="n2", target_type="memory",
        edge_type="linked_to",
    )
    edges_1 = await gs.get_neighborhood("n0", depth=1)
    node_ids = {e.source_id for e in edges_1} | {e.target_id for e in edges_1}
    assert "n0" in node_ids
    assert "n1" in node_ids
    # n2 should NOT appear at depth=1
    assert "n2" not in node_ids


async def test_get_neighborhood_depth_2(gs):
    """2-hop neighborhood includes 2nd-degree neighbors."""
    await gs.add_edge(
        source_id="a", source_type="memory",
        target_id="b", target_type="memory",
        edge_type="linked_to",
    )
    await gs.add_edge(
        source_id="b", source_type="memory",
        target_id="c", target_type="memory",
        edge_type="linked_to",
    )
    edges = await gs.get_neighborhood("a", depth=2)
    all_ids = {e.source_id for e in edges} | {e.target_id for e in edges}
    assert "c" in all_ids


# ── get_stats ─────────────────────────────────────────────────────────────────


async def test_get_stats_empty_graph(gs):
    """get_stats() returns zero counts on empty graph."""
    stats = await gs.get_stats()
    assert stats.total_edges == 0
    assert stats.total_nodes == 0


async def test_get_stats_after_adding_edges(gs):
    """get_stats() counts edges and unique node IDs."""
    await gs.add_edge(
        source_id="s1", source_type="memory",
        target_id="t1", target_type="entity",
        edge_type="extracted_from",
    )
    await gs.add_edge(
        source_id="s2", source_type="memory",
        target_id="t1", target_type="entity",
        edge_type="extracted_from",
    )
    stats = await gs.get_stats()
    assert stats.total_edges == 2
    assert stats.total_nodes == 3  # s1, s2, t1
    assert stats.edge_counts.get("extracted_from") == 2


# ── list_edges ────────────────────────────────────────────────────────────────


async def test_list_edges_filter_edge_type(gs):
    """list_edges(edge_type=...) filters correctly."""
    await gs.add_edge(
        source_id="le1", source_type="note",
        target_id="le2", target_type="note",
        edge_type="wiki_link",
    )
    await gs.add_edge(
        source_id="le3", source_type="memory",
        target_id="le4", target_type="memory",
        edge_type="semantic_similar", weight=0.95,
    )
    wiki = await gs.list_edges(edge_type="wiki_link")
    assert all(e.edge_type == "wiki_link" for e in wiki)


# ── Singletons ────────────────────────────────────────────────────────────────


def test_get_graph_store_raises_before_init(monkeypatch):
    """get_graph_store() raises RuntimeError if not initialised."""
    import app.knowledge.graph as mod
    monkeypatch.setattr(mod, "_graph_store", None)
    with pytest.raises(RuntimeError, match="not initialised"):
        mod.get_graph_store()


async def test_init_and_get_graph_store(migrated_db):
    """init_graph_store() followed by get_graph_store() returns the same instance."""
    from app.knowledge.graph import init_graph_store, get_graph_store, GraphStore
    inst = init_graph_store(migrated_db)
    assert isinstance(inst, GraphStore)
    assert get_graph_store() is inst
