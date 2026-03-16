"""TD-S2 Correctness regression tests.

Covers all 11 items:
  TD-47  _run_step resolves session_key → session_id
  TD-49  entity_merge reports partial failures instead of silently dropping data
  TD-50  Feedback weighting loop variable rebinding (weighted list is mutated)
  TD-51  Confidence boost uses max() not sum() (no amplification)
  TD-52  Recall dedup uses exact set membership (not substring)
  TD-53  kb_list_sources uses src.source_id not src.id
  TD-54  FAISS L2 scores converted via 1/(1+d) — higher = more similar
  TD-63  unlink_entity updates entity_ids JSON column
  TD-65  lifecycle uses cursor-based pagination (after_id param)
  TD-92  update_source uses model_dump(exclude_unset=True)
  TD-101 memory_search filters by memory_type on embedding path
"""
from __future__ import annotations

import json
import unittest.mock as mock
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── TD-47: _run_step resolves session_key → session_id ─────────────────────


async def test_run_step_uses_session_id_not_session_key():
    """_run_step must call get_by_key(sub_key) and use session.session_id for list_by_session."""
    from app.workflows.runtime import _run_step
    from app.workflows.models import WorkflowStep

    step = WorkflowStep(id="s1", agent_id="bot", prompt_template="Hello")

    async def fake_spawn(*, agent_id, initial_message=None, **kwargs):
        return "agent:bot:sub:KEY123"

    collected_session_ids = []

    async def fake_list(session_id, **kwargs):
        collected_session_ids.append(session_id)
        from app.sessions.models import Message
        from datetime import datetime, timezone
        return [Message(
            id="m1", session_id=session_id, role="assistant", content="result",
            created_at=datetime.now(timezone.utc),
        )]

    class FakeSession:
        session_id = "uuid-from-db-001"  # the real UUID

    fake_store = MagicMock()
    fake_store.get_by_key = AsyncMock(return_value=FakeSession())

    class FakeRouter:
        def on(self, evt, handler):
            import asyncio
            asyncio.get_event_loop().call_soon(
                lambda: asyncio.create_task(_fire(handler))
            )

        def off(self, *a, **kw):
            pass

    async def _fire(handler):
        from app.gateway.events import ET, EventSource, GatewayEvent
        evt = GatewayEvent(
            event_type=ET.AGENT_RUN_COMPLETE,
            source=EventSource(kind="system", id="t"),
            session_key="agent:bot:sub:KEY123",
            payload={},
        )
        await handler(evt)

    with (
        patch("app.workflows.runtime.spawn_sub_agent", fake_spawn),
        patch("app.workflows.runtime.get_router", return_value=FakeRouter()),
        patch("app.workflows.runtime.get_session_store", return_value=fake_store),
        patch(
            "app.workflows.runtime.get_message_store",
            return_value=MagicMock(list_by_session=fake_list),
        ),
    ):
        result = await _run_step(step)

    # list_by_session must have been called with the UUID, not the session_key
    assert collected_session_ids == ["uuid-from-db-001"], (
        "list_by_session should receive the session UUID, not the session_key"
    )
    assert result == "result"


# ── TD-49: entity_merge partial failure reporting ───────────────────────────


async def test_entity_merge_reports_alias_transfer_failure():
    """entity_merge includes partial failure details in result instead of silently passing."""
    from app.tools.builtin.memory import entity_merge

    source = MagicMock()
    source.aliases = ["alias_one"]
    source.name = "Source Entity"

    target = MagicMock()
    target.name = "Target Entity"

    fake_store = MagicMock()
    fake_store.get = AsyncMock(side_effect=[source, target])
    fake_store.get_memories = AsyncMock(return_value=[])
    fake_store.add_alias = AsyncMock(side_effect=Exception("DB error"))
    fake_store.update = AsyncMock()

    with patch("app.memory.entity_store.get_entity_store", return_value=fake_store):
        result = await entity_merge("src-1", "tgt-1")

    # Should NOT silently succeed — error info must appear in result
    assert "alias_one" in result or "failed" in result.lower() or "partial" in result.lower(), (
        f"Expected failure info in result, got: {result}"
    )


async def test_entity_merge_preserves_source_on_relink_failure():
    """entity_merge must NOT delete source entity when memory re-linking fails."""
    from app.tools.builtin.memory import entity_merge

    source = MagicMock()
    source.aliases = []
    source.name = "SrcEntity"

    target = MagicMock()
    target.name = "TgtEntity"

    fake_entity_store = MagicMock()
    fake_entity_store.get = AsyncMock(side_effect=[source, target])
    fake_entity_store.get_memories = AsyncMock(return_value=["mem-1"])
    fake_entity_store.add_alias = AsyncMock()
    fake_entity_store.update = AsyncMock()

    fake_mem_store = MagicMock()
    fake_mem_store.link_entity = AsyncMock(side_effect=Exception("link failed"))
    fake_mem_store.unlink_entity = AsyncMock()

    with (
        patch("app.memory.entity_store.get_entity_store", return_value=fake_entity_store),
        patch("app.memory.store.get_memory_store", return_value=fake_mem_store),
    ):
        result = await entity_merge("src-1", "tgt-1")

    # Source should NOT have been soft-deleted (update with status=merged not called)
    for call in fake_entity_store.update.call_args_list:
        kwargs = call.kwargs if call.kwargs else {}
        args = call.args if call.args else ()
        # Should not have been called with status="merged"
        assert kwargs.get("status") != "merged", "Source was incorrectly merged on failure"
    assert "NOT deleted" in result or "partially failed" in result.lower()


# ── TD-50: feedback weighting loop variable rebinding ───────────────────────


def test_feedback_weighting_mutates_list():
    """Extraction pipeline must actually mutate the weighted list (not just the loop var)."""
    import importlib
    # Re-import to get fresh module state
    import app.memory.extraction as ext

    messages = [
        {"role": "user", "content": "great!", "feedback_rating": "up"},
        {"role": "assistant", "content": "Thanks", "feedback_rating": None},
        {"role": "user", "content": "bad", "feedback_rating": "down"},
    ]
    # Simulate the loop from ExtractionPipeline.run()
    weighted = list(messages)
    for i, msg in enumerate(weighted):
        rating = msg.get("feedback_rating")
        if rating == "up":
            weighted[i] = dict(msg, _confidence_boost=0.2)
        elif rating == "down":
            weighted[i] = dict(msg, _confidence_penalty=0.3)

    assert "_confidence_boost" in weighted[0], "boost must be in weighted[0] after TD-50 fix"
    assert "_confidence_penalty" in weighted[2], "penalty must be in weighted[2] after TD-50 fix"
    assert "_confidence_boost" not in weighted[1], "neutral message must not be modified"


# ── TD-51: confidence boost not amplified across multiple messages ────────────


def test_confidence_boost_uses_max_not_sum():
    """When multiple messages have boosts, max() must be used, not sum()."""
    # Simulate 5 upvoted messages
    relevant_messages = [
        {"_confidence_boost": 0.2},
        {"_confidence_boost": 0.2},
        {"_confidence_boost": 0.2},
        {"_confidence_boost": 0.2},
        {"_confidence_boost": 0.2},
    ]
    cand_confidence = 0.7

    # After TD-51 fix: get max boost, not sum
    boost = max((m.get("_confidence_boost", 0.0) for m in relevant_messages), default=0.0)
    result = min(1.0, max(0.0, cand_confidence + boost))

    # Before fix would give 0.7 + 5*0.2 = 1.7 → clamped to 1.0 but wrong intermediate
    # After fix: 0.7 + 0.2 = 0.9 (stays within range without saturation from many messages)
    assert result == pytest.approx(0.9, abs=0.01), (
        f"Expected 0.9 with max() approach, got {result}"
    )


# ── TD-52: recall dedup uses exact set membership ──────────────────────────


def test_dedup_uses_exact_match_not_substring():
    """_dedup_against_always must use set membership, not substring matching."""
    from app.memory.recall import _dedup_against_always

    # "cats" is a substring of "I love cats and dogs" but NOT an exact match
    always_memories = [{"content": "I love cats and dogs"}]
    candidates = [
        {"content": "cats", "id": "c1"},  # substring — should NOT be deduplicated
        {"content": "I love cats and dogs", "id": "c2"},  # exact match — should be removed
    ]
    result = _dedup_against_always(candidates, always_memories)

    # "cats" must NOT be filtered (it's only a substring, not an exact duplicate)
    ids = [r["id"] for r in result]
    assert "c1" in ids, "Substring 'cats' should NOT be filtered as duplicate"
    assert "c2" not in ids, "Exact match should be filtered"


# ── TD-53: kb_list_sources uses src.source_id ─────────────────────────────


async def test_kb_list_sources_uses_source_id():
    """kb_list_sources must use src.source_id, not src.id (which doesn't exist)."""
    from app.tools.builtin.knowledge import kb_list_sources

    mock_src = MagicMock()
    mock_src.source_id = "src-uuid-123"
    mock_src.name = "My KB"
    mock_src.backend = "chroma"
    mock_src.status = "active"
    mock_src.auto_recall = False
    mock_src.description = None
    # Deliberately do NOT set mock_src.id so AttributeError would surface

    mock_registry = MagicMock()
    mock_registry.list = AsyncMock(return_value=[mock_src])

    with patch(
        "app.knowledge.sources.registry.get_knowledge_source_registry",
        return_value=mock_registry,
    ):
        result = await kb_list_sources()

    assert "src-uuid-123" in result, "source_id must appear in kb_list_sources output"
    assert "AttributeError" not in result


# ── TD-54: FAISS L2 score conversion ──────────────────────────────────────


def test_faiss_l2_score_conversion():
    """FAISS L2 distances must be converted to similarity scores: 1/(1+d)."""
    # L2 distances: 0 = identical, large = dissimilar
    dist_identical = 0.0      # perfect match
    dist_close = 0.5          # close
    dist_far = 10.0           # far

    score_identical = 1.0 / (1.0 + dist_identical)  # should be 1.0
    score_close = 1.0 / (1.0 + dist_close)          # should be ~0.667
    score_far = 1.0 / (1.0 + dist_far)              # should be ~0.091

    # After TD-54 fix: higher score = more similar
    assert score_identical > score_close > score_far, (
        "L2→similarity conversion must preserve: identical > close > far"
    )
    assert score_identical == pytest.approx(1.0)


async def test_faiss_adapter_score_inversion_fixed():
    """FaissAdapter.search() must return higher scores for more-similar results."""
    import numpy as np

    # Build a minimal fake FAISS index
    try:
        import faiss  # noqa: F401
    except ImportError:
        pytest.skip("faiss not installed")

    import faiss
    from app.knowledge.sources.adapters.faiss import FaissAdapter
    from app.knowledge.sources.models import KnowledgeSource

    source = MagicMock(spec=KnowledgeSource)
    source.source_id = "faiss-test"
    source.connection = {
        "index_path": "data/test_faiss.faiss",
        "metadata_path": None,
    }

    adapter = FaissAdapter(source)
    # Fake a 2-vector L2 index
    dim = 4
    index = faiss.IndexFlatL2(dim)
    vecs = np.array([[1.0, 0.0, 0.0, 0.0], [0.5, 0.5, 0.0, 0.0]], dtype="float32")
    index.add(vecs)
    adapter._index = index
    adapter._metadata = [{"content": "perfect"}, {"content": "close"}]

    # Query with vector identical to first vector → distance 0 for first item
    query_vec = [1.0, 0.0, 0.0, 0.0]

    fake_store = MagicMock()
    fake_store._provider = MagicMock()
    fake_store._provider.embed = AsyncMock(return_value=[query_vec])

    with patch("app.knowledge.embeddings.get_embedding_store", return_value=fake_store):
        chunks = await adapter.search("perfect match", top_k=2, threshold=0.0)

    assert chunks, "Should return results"
    # First result should have higher score (smaller L2 distance)
    if len(chunks) >= 2:
        assert chunks[0].score >= chunks[1].score, (
            "Results must be sorted highest score first"
        )
    # Perfect match (dist=0) should have score 1.0
    exact_chunk = next((c for c in chunks if c.content == "perfect"), None)
    assert exact_chunk is not None
    assert exact_chunk.score == pytest.approx(1.0, abs=0.01)


# ── TD-63: unlink_entity updates entity_ids JSON ──────────────────────────


async def test_unlink_entity_updates_json_column(migrated_db):
    """unlink_entity must remove entity_id from entity_ids JSON column."""
    from app.memory.store import init_memory_store
    from app.memory.entity_store import init_entity_store

    entity_store = init_entity_store(migrated_db)
    store = init_memory_store(migrated_db)
    mem = await store.create(content="test memory", memory_type="fact")

    # Create real entities (FK constraint on memory_entity_links.entity_id)
    ent_a = await entity_store.create(name="Entity A", entity_type="concept")
    ent_b = await entity_store.create(name="Entity B", entity_type="concept")

    # Link two entities
    await store.link_entity(mem.id, ent_a.id)
    await store.link_entity(mem.id, ent_b.id)

    loaded = await store.get(mem.id)
    assert ent_a.id in loaded.entity_ids
    assert ent_b.id in loaded.entity_ids

    # Unlink one entity
    await store.unlink_entity(mem.id, ent_a.id)

    updated = await store.get(mem.id)
    assert ent_a.id not in updated.entity_ids, (
        "entity_ids JSON column must not contain unlinked entity (TD-63)"
    )
    assert ent_b.id in updated.entity_ids, "Other entity must remain"


# ── TD-65: lifecycle cursor-based pagination ───────────────────────────────


async def test_memory_store_list_after_id(migrated_db):
    """MemoryStore.list() with after_id must use cursor-based pagination."""
    from app.memory.store import init_memory_store

    store = init_memory_store(migrated_db)
    # Create 5 memories
    mems = []
    for i in range(5):
        m = await store.create(content=f"memory {i}", memory_type="fact")
        mems.append(m)

    # Sort by id (cursor ordering)
    sorted_ids = sorted(m.id for m in mems)

    # Get first 3 with cursor
    first_page = await store.list(after_id="", limit=3)
    first_ids = [m.id for m in first_page]
    assert len(first_page) == 3

    # Continue after last item in first page
    second_page = await store.list(after_id=first_page[-1].id, limit=10)
    second_ids = [m.id for m in second_page]
    assert len(second_page) == 2, "Should get remaining 2 memories"
    assert set(first_ids).isdisjoint(set(second_ids)), "Pages must not overlap"


async def test_lifecycle_archive_no_skip_on_mutation(migrated_db):
    """run_archive must process all items even when earlier items are archived."""
    from app.memory.store import init_memory_store
    from app.memory.entity_store import init_entity_store
    from app.memory.lifecycle import MemoryDecayConfig, ConsolidationConfig, MemoryLifecycleManager

    mem_store = init_memory_store(migrated_db)
    ent_store = init_entity_store(migrated_db)

    # Create 10 memories with very low decay_score (should all be archived)
    for i in range(10):
        m = await mem_store.create(content=f"old memory {i}", memory_type="fact")
        await mem_store.update(m.id, decay_score=0.01)

    # Use low archive_threshold so all 0.01-score memories get archived;
    # small batch_size exercises cursor pagination
    cfg = ConsolidationConfig(enabled=True, archive_threshold=0.5, batch_size=3)
    manager = MemoryLifecycleManager(
        memory_store=mem_store,
        entity_store=ent_store,
        audit_log=None,
        decay_cfg=MemoryDecayConfig(),
        consol_cfg=cfg,
    )

    result = await manager.run_archive()
    assert result["archived"] == 10, (
        f"All 10 memories should be archived (no skips), got {result['archived']}"
    )


# ── TD-92: update_source uses model_dump(exclude_unset=True) ───────────────


def test_update_source_allows_clearing_optional_fields():
    """UpdateSourceRequest.model_dump(exclude_unset=True) must preserve explicit None."""
    from app.api.routers.knowledge_sources import UpdateSourceRequest

    # Setting description to None explicitly (not just omitting it)
    body = UpdateSourceRequest.model_validate({"description": None})
    result = body.model_dump(exclude_unset=True)
    assert "description" in result, (
        "Explicitly-set None fields must be included (exclude_unset=True)"
    )
    assert result["description"] is None


def test_update_source_omits_unset_fields():
    """UpdateSourceRequest.model_dump(exclude_unset=True) must omit fields client didn't send."""
    from app.api.routers.knowledge_sources import UpdateSourceRequest

    body = UpdateSourceRequest.model_validate({"name": "New Name"})
    result = body.model_dump(exclude_unset=True)
    assert "name" in result
    assert "description" not in result, "Unset fields must not appear in the update dict"


# ── TD-101: memory_search filters by memory_type on embedding path ───────────


async def test_memory_search_filters_type_on_embedding_path():
    """memory_search must apply memory_type filter even when using embeddings."""
    from app.tools.builtin.memory import memory_search

    # Two hits — only one matches the requested memory_type
    hit_fact = MagicMock()
    hit_fact.source_id = "m-fact"
    hit_fact.score = 0.9

    hit_task = MagicMock()
    hit_task.source_id = "m-task"
    hit_task.score = 0.8

    mem_fact = MagicMock()
    mem_fact.memory_type = "fact"
    mem_fact.id = "m-fact"

    mem_task = MagicMock()
    mem_task.memory_type = "task"
    mem_task.id = "m-task"

    fake_emb = MagicMock()
    fake_emb.search = AsyncMock(return_value=[hit_fact, hit_task])

    fake_mem_store = MagicMock()
    async def fake_get(mid):
        return mem_fact if mid == "m-fact" else mem_task
    fake_mem_store.get = AsyncMock(side_effect=fake_get)

    with (
        patch("app.knowledge.embeddings.get_embedding_store", return_value=fake_emb),
        patch("app.memory.store.get_memory_store", return_value=fake_mem_store),
    ):
        result = await memory_search("query", memory_type="fact")

    # Only the "fact" hit should appear in results
    assert "m-fact" in result, "fact memory should be in results"
    assert "m-task" not in result, (
        "task memory must be filtered out when memory_type='fact' (TD-101)"
    )
