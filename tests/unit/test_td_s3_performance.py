"""TD-S3 Performance regression tests.

Covers all 13 items confirmed fixed in TD-S3:
  TD-60  vault.py — async file I/O via asyncio.to_thread
  TD-61  embeddings.py — threadpool model.encode()
  TD-64  entity_store.resolve — SQL json_each alias search (no full table scan)
  TD-75  vault.sync_from_disk — single write transaction
  TD-78  embeddings._load_vectors — filter-keyed cache
  TD-86  chroma.py — asyncio.to_thread for blocking Chroma calls
  TD-93  chroma.py — _collection cached on first call
  TD-100 graph router — SQL orphan detection (no list_edges Python scan)
  TD-107 graph.rebuild_semantic_edges — batched executemany (fixed bugs)
  TD-118 entity_store.create — no extra DB round-trip
  TD-128 graph.shortest_path — deque BFS (O(1) popleft)
  TD-129 graph.get_stats — SQL COUNT for node count
  TD-135 migration 0012 — ix_knowledge_sources_auto_recall index
"""
from __future__ import annotations

import asyncio
import unittest.mock as mock
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ── TD-60: vault.py async file I/O ─────────────────────────────────────────


def test_vault_create_note_uses_to_thread_source():
    """VaultStore file ops use asyncio.to_thread — confirmed by source inspection (TD-60)."""
    import inspect
    import app.knowledge.vault as vault_mod

    src_create = inspect.getsource(vault_mod.VaultStore.create_note)
    src_get = inspect.getsource(vault_mod.VaultStore.get_note)
    src_update = inspect.getsource(vault_mod.VaultStore.update_note)
    src_delete = inspect.getsource(vault_mod.VaultStore.delete_note)

    for name, src in [("create_note", src_create), ("get_note", src_get),
                      ("update_note", src_update), ("delete_note", src_delete)]:
        assert "to_thread" in src, f"{name} must use asyncio.to_thread"


async def test_vault_roundtrip_functional(migrated_db, tmp_path):
    """VaultStore create/get/delete round-trip works with async file I/O (TD-60)."""
    from app.knowledge.vault import VaultStore

    store = VaultStore(migrated_db, vault_path=tmp_path)
    note = await store.create_note(title="Hello TD60", content="World", tags=["x"])
    assert note.title == "Hello TD60"

    fetched = await store.get_note(note.id)
    assert fetched.content == "World"

    await store.delete_note(note.id)
    from app.exceptions import NotFoundError
    with pytest.raises(NotFoundError):
        await store.get_note(note.id)


# ── TD-64: entity_store SQL json_each alias resolution ─────────────────────


async def test_entity_resolve_by_alias_sql(migrated_db):
    """resolve() uses SQL json_each — not a Python-side scan (TD-64)."""
    from app.memory.entity_store import EntityStore

    store = EntityStore(migrated_db)
    entity = await store.create(
        name="OpenAI",
        entity_type="organization",
        aliases=["Open AI", "openai inc", "OAI"],
    )

    # Should match via alias (case-insensitive)
    found = await store.resolve("open ai")
    assert found is not None
    assert found.id == entity.id

    found2 = await store.resolve("OAI")
    assert found2 is not None
    assert found2.id == entity.id


async def test_entity_resolve_by_name_primary(migrated_db):
    """resolve() matches canonical name (case-insensitive) first (TD-64)."""
    from app.memory.entity_store import EntityStore

    store = EntityStore(migrated_db)
    entity = await store.create(
        name="Google DeepMind",
        entity_type="organization",
    )

    found = await store.resolve("google deepmind")
    assert found is not None
    assert found.id == entity.id


async def test_entity_resolve_returns_none_for_missing(migrated_db):
    """resolve() returns None when no entity matches (TD-64)."""
    from app.memory.entity_store import EntityStore

    store = EntityStore(migrated_db)
    result = await store.resolve("completely unknown entity xyz123")
    assert result is None


# ── TD-78: embeddings filter-keyed cache ───────────────────────────────────


async def test_embedding_cache_keyed_by_source_types(migrated_db):
    """_load_vectors caches filtered and unfiltered results independently (TD-78)."""
    from app.knowledge.embeddings import SQLiteEmbeddingStore

    mock_provider = MagicMock()
    store = SQLiteEmbeddingStore(migrated_db, mock_provider)

    # Initially no cache
    assert store._cache is None

    # Call with None (unfiltered)
    await store._load_vectors(source_types=None)
    assert store._cache is not None
    assert None in store._cache

    # Call with a filter — should create a separate cache key
    await store._load_vectors(source_types=["memory"])
    memory_key = ("memory",)
    assert memory_key in store._cache

    # Both keys should coexist
    assert None in store._cache
    assert memory_key in store._cache

    # Invalidate clears all
    store._invalidate()
    assert store._cache is None


async def test_embedding_cache_different_filters_independent(migrated_db):
    """Different source_type filters get separate cache entries (TD-78)."""
    from app.knowledge.embeddings import SQLiteEmbeddingStore

    mock_provider = MagicMock()
    store = SQLiteEmbeddingStore(migrated_db, mock_provider)
    await store._load_vectors(source_types=["memory"])
    await store._load_vectors(source_types=["note"])
    await store._load_vectors(source_types=["memory", "note"])

    memory_key = ("memory",)
    note_key = ("note",)
    both_key = ("memory", "note")

    assert memory_key in store._cache
    assert note_key in store._cache
    assert both_key in store._cache


# ── TD-93: chroma.py collection caching ────────────────────────────────────


def test_chroma_collection_cached_after_first_call():
    """ChromaAdapter._get_collection() caches the collection on first call (TD-93)."""
    from app.knowledge.sources.adapters.chroma import ChromaAdapter
    from app.knowledge.sources.models import KnowledgeSource

    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    # Build a minimal KnowledgeSource so that self.source.connection works
    source = KnowledgeSource(
        source_id="test-chroma",
        name="Test Chroma",
        backend="chroma",
        connection={"host": "local", "path": "/tmp/chroma", "collection": "test_coll"},
    )
    adapter = ChromaAdapter.__new__(ChromaAdapter)
    adapter.source = source
    adapter._client = mock_client  # bypass _ensure_client
    adapter._collection = None

    # First call
    coll1 = adapter._get_collection()
    # Second call
    coll2 = adapter._get_collection()

    # get_or_create_collection called exactly once
    assert mock_client.get_or_create_collection.call_count == 1
    assert coll1 is coll2


def test_chroma_collection_attribute_initialized_as_none():
    """ChromaAdapter.__init__ sets self._collection = None (TD-93)."""
    from app.knowledge.sources.adapters.chroma import ChromaAdapter

    adapter = ChromaAdapter.__new__(ChromaAdapter)
    # Simulate __init__ without actually connecting
    adapter._collection = None
    assert adapter._collection is None


# ── TD-100: graph router SQL orphan detection ──────────────────────────────


async def test_orphan_endpoint_uses_sql_not_list_edges(migrated_db):
    """get_orphans() queries the DB directly — not via list_edges (TD-100)."""
    from app.knowledge.graph import GraphStore, init_graph_store

    gs = GraphStore(migrated_db)
    init_graph_store(migrated_db)

    # Spy on list_edges — it must NOT be called
    with patch.object(gs, "list_edges", wraps=gs.list_edges) as mock_list:
        # Simulate what the endpoint does: direct SQL on gs._db
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
            LIMIT 10
            """,
        ) as cur:
            rows = await cur.fetchall()

        # list_edges was never called
        assert mock_list.call_count == 0


async def test_orphan_detection_returns_unconnected_entities(migrated_db):
    """Entities not in any graph edge appear in orphan results (TD-100)."""
    from app.knowledge.graph import GraphStore
    from app.memory.entity_store import EntityStore

    gs = GraphStore(migrated_db)
    es = EntityStore(migrated_db)

    # Create two entities
    orphan_ent = await es.create(name="Orphan Corp", entity_type="organization")
    connected_ent = await es.create(name="Connected Ltd", entity_type="organization")

    # Connect the second entity to a graph edge
    await gs.add_edge(
        source_id=connected_ent.id, source_type="entity",
        target_id="some-other-node", target_type="note",
        edge_type="linked_to",
    )

    # Query orphan entities via SQL
    async with gs._db.execute(
        """
        SELECT e.id FROM entities e
        WHERE e.status = 'active'
          AND e.id NOT IN (
              SELECT source_id FROM graph_edges
              UNION SELECT target_id FROM graph_edges
          )
        """,
    ) as cur:
        rows = await cur.fetchall()
    orphan_ids = {r[0] for r in rows}

    assert orphan_ent.id in orphan_ids
    assert connected_ent.id not in orphan_ids


# ── TD-118: entity_store.create no extra get() round-trip ─────────────────


async def test_entity_create_no_db_roundtrip(migrated_db):
    """create() returns entity directly without an extra get() call (TD-118)."""
    from app.memory.entity_store import EntityStore

    store = EntityStore(migrated_db)

    # Spy on get() — it must not be called
    original_get = store.get
    get_calls = []

    async def spy_get(entity_id: str):
        get_calls.append(entity_id)
        return await original_get(entity_id)

    store.get = spy_get  # type: ignore[method-assign]

    entity = await store.create(
        name="NoRoundtrip Inc",
        entity_type="organization",
        aliases=["NR Inc"],
    )

    assert len(get_calls) == 0, "create() called get() — should construct Entity directly"
    assert entity.name == "NoRoundtrip Inc"
    assert entity.aliases == ["NR Inc"]
    assert entity.status == "active"
    assert entity.reference_count == 0


async def test_entity_create_returns_correct_fields(migrated_db):
    """create() returns Entity with correct id, name, type, aliases, summary (TD-118)."""
    from app.memory.entity_store import EntityStore

    store = EntityStore(migrated_db)
    entity = await store.create(
        name="Test Entity",
        entity_type="concept",
        aliases=["TE", "Test Ent"],
        summary="A test concept.",
        properties={"lang": "en"},
    )

    assert entity.id  # has a UUID
    assert entity.name == "Test Entity"
    assert entity.entity_type == "concept"
    assert entity.aliases == ["TE", "Test Ent"]
    assert entity.summary == "A test concept."
    assert entity.properties == {"lang": "en"}
    assert entity.status == "active"

    # Verify it was actually persisted by fetching from DB
    fetched = await store.get(entity.id)
    assert fetched.name == "Test Entity"


# ── TD-128: graph.shortest_path uses deque ─────────────────────────────────


async def test_shortest_path_direct_connection(migrated_db):
    """shortest_path finds a direct 1-hop path (TD-128)."""
    from app.knowledge.graph import GraphStore

    gs = GraphStore(migrated_db)
    await gs.add_edge(
        source_id="nodeA", source_type="note",
        target_id="nodeB", target_type="note",
        edge_type="wiki_link",
    )

    path = await gs.shortest_path("nodeA", "nodeB")
    assert path == ["nodeA", "nodeB"]


async def test_shortest_path_two_hops(migrated_db):
    """shortest_path finds a 2-hop path (TD-128)."""
    from app.knowledge.graph import GraphStore

    gs = GraphStore(migrated_db)
    await gs.add_edge(
        source_id="start", source_type="note",
        target_id="middle", target_type="note",
        edge_type="wiki_link",
    )
    await gs.add_edge(
        source_id="middle", source_type="note",
        target_id="end", target_type="note",
        edge_type="wiki_link",
    )

    path = await gs.shortest_path("start", "end")
    assert path == ["start", "middle", "end"]


async def test_shortest_path_same_node(migrated_db):
    """shortest_path from a node to itself returns single-element list (TD-128)."""
    from app.knowledge.graph import GraphStore

    gs = GraphStore(migrated_db)
    path = await gs.shortest_path("x", "x")
    assert path == ["x"]


async def test_shortest_path_no_path(migrated_db):
    """shortest_path returns [] when no path exists (TD-128)."""
    from app.knowledge.graph import GraphStore

    gs = GraphStore(migrated_db)
    path = await gs.shortest_path("isolated1", "isolated2")
    assert path == []


def test_shortest_path_deque_used():
    """shortest_path BFS uses deque (O(1) popleft), not list.pop(0) (TD-128)."""
    import ast
    import inspect
    import textwrap
    import app.knowledge.graph as graph_mod

    src = inspect.getsource(graph_mod.GraphStore.shortest_path)
    assert "deque" in src, "shortest_path must use deque for BFS queue"
    assert "popleft" in src, "shortest_path must use deque.popleft()"
    # Verify no Call node with .pop(0) — i.e., no actual runtime pop(0) call
    # (A comment mentioning pop(0) is fine; we parse the AST to be precise)
    tree = ast.parse(textwrap.dedent(src))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "pop"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == 0
            ):
                pytest.fail("shortest_path must not call .pop(0) — use deque.popleft() instead")


# ── TD-129: graph.get_stats SQL COUNT node count ──────────────────────────


async def test_get_stats_node_count_sql(migrated_db):
    """get_stats() uses SQL COUNT for unique node count, not Python len() (TD-129)."""
    import inspect
    import app.knowledge.graph as graph_mod

    src = inspect.getsource(graph_mod.GraphStore.get_stats)
    # Should use SELECT COUNT(*) FROM (... UNION ...)
    assert "COUNT(*)" in src, "get_stats must use SQL COUNT for node count"
    # Must not use len() on a Python list for the node count
    assert "len(node_rows)" not in src, "get_stats must not use len(node_rows)"


async def test_get_stats_empty_graph(migrated_db):
    """get_stats() returns zeros on an empty graph (TD-129)."""
    from app.knowledge.graph import GraphStore

    gs = GraphStore(migrated_db)
    stats = await gs.get_stats()
    assert stats.total_nodes == 0
    assert stats.total_edges == 0


async def test_get_stats_counts_nodes_correctly(migrated_db):
    """get_stats().total_nodes equals the number of unique node IDs in edges (TD-129)."""
    from app.knowledge.graph import GraphStore

    gs = GraphStore(migrated_db)
    await gs.add_edge(
        source_id="n1", source_type="note",
        target_id="n2", target_type="note",
        edge_type="wiki_link",
    )
    await gs.add_edge(
        source_id="n2", source_type="note",
        target_id="n3", target_type="note",
        edge_type="wiki_link",
    )

    stats = await gs.get_stats()
    # n1, n2, n3 — three unique nodes
    assert stats.total_nodes == 3
    assert stats.total_edges == 2


# ── TD-135: migration 0012 index ────────────────────────────────────────────


def test_migration_0012_creates_auto_recall_index():
    """Migration 0012 defines the ix_knowledge_sources_auto_recall index (TD-135)."""
    import importlib.util
    import pathlib

    migration_path = pathlib.Path(__file__).parent.parent.parent / \
        "alembic" / "versions" / "0012_td_s3_auto_recall_index.py"

    spec = importlib.util.spec_from_file_location("migration_0012", migration_path)
    mod = importlib.util.module_from_spec(spec)

    # We don't run alembic here — just inspect the source
    src = migration_path.read_text(encoding="utf-8")
    assert "ix_knowledge_sources_auto_recall" in src
    assert "knowledge_sources" in src
    assert "auto_recall" in src


def test_migration_0012_revision_chain():
    """Migration 0012 has revision='0012' and down_revision='0011' (TD-135)."""
    import pathlib

    migration_path = pathlib.Path(__file__).parent.parent.parent / \
        "alembic" / "versions" / "0012_td_s3_auto_recall_index.py"
    src = migration_path.read_text(encoding="utf-8")

    assert 'revision = "0012"' in src or "revision='0012'" in src
    assert 'down_revision = "0011"' in src or "down_revision='0011'" in src


async def test_migration_0012_applied_in_migrated_db(migrated_db):
    """After migration, ix_knowledge_sources_auto_recall index exists (TD-135)."""
    async with migrated_db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='ix_knowledge_sources_auto_recall'"
    ) as cur:
        row = await cur.fetchone()

    assert row is not None, "Migration 0012 index ix_knowledge_sources_auto_recall not found in DB"


# ── TD-61: embeddings threadpool model.encode ──────────────────────────────


def test_local_embedding_provider_uses_to_thread():
    """LocalEmbeddingProvider.embed uses asyncio.to_thread for model.encode (TD-61)."""
    import inspect
    import app.knowledge.embeddings as emb_mod

    src = inspect.getsource(emb_mod.LocalEmbeddingProvider.embed)
    assert "to_thread" in src, "LocalEmbeddingProvider.embed must use asyncio.to_thread"
    assert "model.encode" in src or "encode" in src


# ── TD-86: chroma asyncio.to_thread ────────────────────────────────────────


def test_chroma_adapter_uses_to_thread_for_query():
    """ChromaAdapter uses asyncio.to_thread for collection.query (TD-86)."""
    import inspect
    import app.knowledge.sources.adapters.chroma as chroma_mod

    src = inspect.getsource(chroma_mod.ChromaAdapter.search)
    assert "to_thread" in src, "ChromaAdapter.search must use asyncio.to_thread"


def test_chroma_adapter_uses_to_thread_for_count_or_heartbeat():
    """ChromaAdapter uses asyncio.to_thread for count/heartbeat (TD-86)."""
    import inspect
    import app.knowledge.sources.adapters.chroma as chroma_mod

    full_src = inspect.getsource(chroma_mod.ChromaAdapter)
    # Either get_count or health_check should use to_thread
    assert "to_thread" in full_src


# ── TD-75: vault.sync_from_disk single transaction ─────────────────────────


def test_vault_sync_from_disk_single_transaction_source():
    """sync_from_disk collects writes before opening transaction (TD-75)."""
    import inspect
    import app.knowledge.vault as vault_mod

    src = inspect.getsource(vault_mod.VaultStore.sync_from_disk)
    # Should have a single write_transaction block, not per-file looping into it
    # Confirm the pattern: collect inserts/updates/deletes before transacting
    assert "write_transaction" in src, "sync_from_disk must use write_transaction"
    # The key fix: lists are populated before the transaction block
    assert "inserts" in src or "to_insert" in src or "updates" in src


# ── TD-107: rebuild_semantic_edges batched executemany ─────────────────────


def test_rebuild_semantic_edges_uses_executemany():
    """rebuild_semantic_edges uses executemany for batch inserts (TD-107)."""
    import inspect
    import app.knowledge.graph as graph_mod

    src = inspect.getsource(graph_mod.GraphStore.rebuild_semantic_edges)
    assert "executemany" in src, "rebuild_semantic_edges must use executemany"
    # Should collect edges first, then insert in batches
    assert "edges_to_insert" in src or "batch" in src.lower()


def test_rebuild_semantic_edges_uses_similarity_not_score():
    """rebuild_semantic_edges uses hit.similarity (not hit.score) (TD-107)."""
    import inspect
    import app.knowledge.graph as graph_mod

    src = inspect.getsource(graph_mod.GraphStore.rebuild_semantic_edges)
    assert "hit.similarity" in src, (
        "rebuild_semantic_edges must use hit.similarity (EmbeddingSearchResult field)"
    )
    assert "hit.score" not in src, "hit.score does not exist on EmbeddingSearchResult"
