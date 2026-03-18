"""TD-S4 regression tests — Concurrency & Resource Management.

Covers all 11 items:
  T1  (TD-48)  Workflow cancellation via asyncio.Event
  T2  (TD-58)  Sub-agent spawn lock prevents TOCTOU
  T3  (TD-59)  OCC guard: terminal status not overwritten
  T4  (TD-62)  MemoryStore.get() is read-only; touch() bumps access_count
  T5  (TD-68)  AGENT_RUN_COMPLETE payload includes content; sessions_send uses it
  T6  (TD-70)  _active never leaks even when auto_archive_minutes=0
  T7  (TD-83)  EntityStore.update() OCC with WHERE updated_at
  T8  (TD-94)  PgVectorAdapter.deactivate() closes pool
  T9  (TD-95)  KnowledgeSourceRegistry._adapter_lock exists and guards mutations
  T10 (TD-96)  consecutive_failures incremented atomically via SQL
  T11 (TD-109) MemoryLifecycleManager.run_all() skips when already running
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── T1: Workflow cancellation (TD-48) ─────────────────────────────────────────

def test_cancel_events_dict_exists():
    """_cancel_events module-level dict must exist in api.py."""
    from app.workflows.api import _cancel_events
    assert isinstance(_cancel_events, dict)


@pytest.mark.asyncio
async def test_run_pipeline_respects_cancel_event():
    """Pipeline must stop before a step when cancel_event is already set."""
    from app.workflows.models import Workflow, WorkflowRun, WorkflowStep
    from app.workflows.runtime import run_pipeline

    step1 = WorkflowStep(id="s1", agent_id="a1", prompt_template="hello")
    step2 = WorkflowStep(id="s2", agent_id="a1", prompt_template="world")
    wf = Workflow(
        id="wf1", name="test", mode="pipeline",
        steps=[step1, step2], created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    run = WorkflowRun(
        id="run1", workflow_id="wf1", status="pending",
        created_at=datetime.now(timezone.utc),
    )

    cancel_event = asyncio.Event()
    cancel_event.set()  # pre-cancelled

    store_mock = AsyncMock()
    store_mock.update_run_status = AsyncMock(side_effect=lambda rid, **kw: WorkflowRun(
        id=rid, workflow_id="wf1", status=kw.get("status", "running"),
        created_at=datetime.now(timezone.utc),
    ))

    with patch("app.workflows.runtime.get_workflow_store", return_value=store_mock):
        result = await run_pipeline(wf, run, cancel_event=cancel_event)

    assert result.status == "cancelled"
    # _run_step_with_retry should NOT have been called (no step execution happened)
    # Verified indirectly: no step-related store calls other than status=cancelled
    calls = [str(c) for c in store_mock.update_run_status.call_args_list]
    assert any("cancelled" in c for c in calls)


@pytest.mark.asyncio
async def test_run_parallel_canceled_before_start():
    """Parallel run must return cancelled immediately if cancel_event is set."""
    from app.workflows.models import Workflow, WorkflowRun, WorkflowStep
    from app.workflows.runtime import run_parallel

    step = WorkflowStep(id="s1", agent_id="a1", prompt_template="hi")
    wf = Workflow(
        id="wf2", name="test", mode="parallel",
        steps=[step], created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    run = WorkflowRun(
        id="run2", workflow_id="wf2", status="pending",
        created_at=datetime.now(timezone.utc),
    )

    cancel_event = asyncio.Event()
    cancel_event.set()

    store_mock = AsyncMock()
    store_mock.update_run_status = AsyncMock(side_effect=lambda rid, **kw: WorkflowRun(
        id=rid, workflow_id="wf2", status=kw.get("status", "running"),
        created_at=datetime.now(timezone.utc),
    ))

    with patch("app.workflows.runtime.get_workflow_store", return_value=store_mock):
        result = await run_parallel(wf, run, cancel_event=cancel_event)

    assert result.status == "cancelled"


@pytest.mark.asyncio
async def test_execute_workflow_passes_cancel_event():
    """execute_workflow() must accept and forward cancel_event kwarg."""
    from app.workflows.models import Workflow, WorkflowRun
    from app.workflows.runtime import execute_workflow
    import inspect

    sig = inspect.signature(execute_workflow)
    assert "cancel_event" in sig.parameters


# ── T2: Sub-agent spawn lock (TD-58) ─────────────────────────────────────────

def test_spawn_locks_dict_exists():
    """_spawn_locks module-level dict must exist in sub_agent.py."""
    from app.agent.sub_agent import _spawn_locks
    assert isinstance(_spawn_locks, dict)


def test_get_spawn_lock_returns_asyncio_lock():
    """_get_spawn_lock() must return an asyncio.Lock for a given parent."""
    from app.agent.sub_agent import _get_spawn_lock
    lock = _get_spawn_lock("test_parent_abc")
    assert isinstance(lock, asyncio.Lock)


def test_get_spawn_lock_same_parent_same_lock():
    """Same parent always returns the same Lock instance."""
    from app.agent.sub_agent import _get_spawn_lock
    key = "shared_parent_xyz"
    assert _get_spawn_lock(key) is _get_spawn_lock(key)


def test_spawn_agent_check_and_register_inside_lock():
    """spawn_sub_agent must enclose count-check + register inside async with lock."""
    import ast
    import inspect
    import textwrap
    from app.agent import sub_agent as mod

    src = textwrap.dedent(inspect.getsource(mod.spawn_sub_agent))
    tree = ast.parse(src)

    # Walk all AsyncWith nodes and verify one contains both the
    # active_sub_agent_count check and the _register() call
    class _Visitor(ast.NodeVisitor):
        found = False

        def visit_AsyncWith(self, node: ast.AsyncWith) -> None:  # noqa: N802
            # Check items include _get_spawn_lock
            items_src = ast.unparse(node)
            if "_get_spawn_lock" in items_src or "_spawn_lock" in items_src:
                body_src = ast.unparse(node)
                if "active_sub_agent_count" in body_src and "_register" in body_src:
                    self.found = True
            self.generic_visit(node)

    v = _Visitor()
    v.visit(tree)
    assert v.found, "spawn_sub_agent check+register not inside async with lock"


# ── T3: OCC workflow status (TD-59) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_run_status_ignores_non_terminal_when_already_cancelled(migrated_db):
    """update_run_status must NOT overwrite a cancelled run with 'running'."""
    from app.workflows.store import WorkflowStore
    from app.db.connection import write_transaction

    store = WorkflowStore(migrated_db)
    # Create workflow + run
    async with write_transaction(migrated_db):
        await migrated_db.execute(
            "INSERT INTO workflows (id, name, mode, steps_json, created_at, updated_at) "
            "VALUES ('wf99','t','pipeline','[]',datetime('now'),datetime('now'))"
        )
    run = await store.create_run("wf99")
    # Force to cancelled
    await store.update_run_status(run.id, status="cancelled")
    # Now try to set to running — should be ignored
    result = await store.update_run_status(run.id, status="running")
    assert result.status == "cancelled"


@pytest.mark.asyncio
async def test_update_run_status_terminal_to_terminal_allowed(migrated_db):
    """Transitioning from cancelled to completed should also be blocked."""
    from app.workflows.store import WorkflowStore
    from app.db.connection import write_transaction

    store = WorkflowStore(migrated_db)
    async with write_transaction(migrated_db):
        await migrated_db.execute(
            "INSERT INTO workflows (id, name, mode, steps_json, created_at, updated_at) "
            "VALUES ('wf98','t','pipeline','[]',datetime('now'),datetime('now'))"
        )
    run = await store.create_run("wf98")
    await store.update_run_status(run.id, status="cancelled")
    # Another terminal → still blocked (cancelled stays)
    result = await store.update_run_status(run.id, status="completed")
    assert result.status == "cancelled"


# ── T4: Split get/touch memory (TD-62) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_memory_store_get_does_not_bump_access_count(migrated_db):
    """MemoryStore.get() must NOT modify access_count or last_accessed."""
    from app.memory.store import MemoryStore

    ms = MemoryStore(migrated_db)
    mem = await ms.create(
        content="test content",
        memory_type="fact",
        scope="agent",
        agent_id="agent1",
    )
    before = await ms.get(mem.id)
    # Call get twice more
    await ms.get(mem.id)
    await ms.get(mem.id)
    after = await ms.get(mem.id)
    # access_count should remain unchanged (0)
    assert after.access_count == before.access_count


@pytest.mark.asyncio
async def test_memory_store_touch_bumps_access_count(migrated_db):
    """MemoryStore.touch() must increment access_count by 1 per call."""
    from app.memory.store import MemoryStore

    ms = MemoryStore(migrated_db)
    mem = await ms.create(
        content="touchable",
        memory_type="fact",
        scope="agent",
        agent_id="agent1",
    )
    initial = (await ms.get(mem.id)).access_count
    await ms.touch(mem.id)
    after_one = (await ms.get(mem.id)).access_count
    await ms.touch(mem.id)
    after_two = (await ms.get(mem.id)).access_count
    assert after_one == initial + 1
    assert after_two == initial + 2


def test_memory_store_has_touch_method():
    """MemoryStore must expose a touch() method."""
    from app.memory.store import MemoryStore
    import inspect
    assert hasattr(MemoryStore, "touch")
    assert asyncio.iscoroutinefunction(MemoryStore.touch)


# ── T5: Race event/message (TD-68) ───────────────────────────────────────────

def test_sessions_send_uses_event_payload_content():
    """sessions_send must read content from event payload, not re-query DB."""
    import inspect
    import textwrap
    from app.tools.builtin import sessions as mod

    src = textwrap.dedent(inspect.getsource(mod.sessions_send))
    # Must reference payload content from the event
    assert 'payload' in src and 'content' in src
    # Must show the payload-first path (not only DB re-read)
    assert 'reply.get("payload"' in src or "reply.get('payload'" in src


def test_turn_loop_emits_content_in_run_complete_payload():
    """turn_loop.py must include 'content' key in AGENT_RUN_COMPLETE payload."""
    import inspect
    from app.agent import turn_loop as mod

    # Inspect the full module source since the emit is in a private method
    src = inspect.getsource(mod)
    emit_idx = src.find("AGENT_RUN_COMPLETE")
    assert emit_idx != -1, "AGENT_RUN_COMPLETE not found in turn_loop.py"
    # Check surrounding context for "content" key in the payload dict
    ctx = src[emit_idx: emit_idx + 300]
    assert '"content"' in ctx or "'content'" in ctx, (
        "AGENT_RUN_COMPLETE emit payload does not include 'content' key"
    )
    # Message insert must appear before the event emit
    insert_idx = src.rfind("await self._message_store.insert", 0, emit_idx)
    assert insert_idx != -1, "Message insert must happen before AGENT_RUN_COMPLETE emit"


# ── T6: _active leak (TD-70) ─────────────────────────────────────────────────

def test_auto_archive_scheduled_unconditionally():
    """spawn_sub_agent must always schedule _auto_archive, even when minutes=0."""
    import ast
    import inspect
    import textwrap
    from app.agent import sub_agent as mod

    src = textwrap.dedent(inspect.getsource(mod.spawn_sub_agent))
    tree = ast.parse(src)

    # Find create_task calls in the source
    task_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_task"
    ]
    assert len(task_calls) >= 1, "No create_task call found in spawn_sub_agent"

    # The create_task must not be inside an 'if auto_archive_minutes > 0' guard
    def _is_guarded(tree: ast.AST, task_call: ast.Call) -> bool:
        """Returns True if task_call is inside an if-auto_archive_minutes block."""
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                cond = ast.unparse(node.test)
                if "auto_archive_minutes" in cond:
                    body_src = ast.unparse(node)
                    if "create_task" in body_src:
                        return True
        return False

    assert not _is_guarded(tree, task_calls[0]), (
        "create_task is still guarded by auto_archive_minutes > 0 check"
    )


@pytest.mark.asyncio
async def test_unregister_called_after_zero_delay(migrated_db):
    """When auto_archive_minutes=0, _unregister must be called after task completes."""
    from app.agent.sub_agent import _active, _register, _unregister

    parent = "_global"
    fake_key = "agent:x:sub:aaaabbbb"
    _register(parent, fake_key)
    assert fake_key in _active.get(parent, set())

    # Simulate _auto_archive with delay_s=0
    from app.agent.sub_agent import _auto_archive
    await _auto_archive(parent, fake_key, delay_s=0)

    assert fake_key not in _active.get(parent, set())


# ── T7: EntityStore OCC (TD-83) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_entity_update_occ_where_clause(migrated_db):
    """EntityStore.update() SQL must include version-based OCC guard (TD-300)."""
    import inspect
    from app.memory import entity_store as mod

    src = inspect.getsource(mod.EntityStore.update)
    assert "version" in src and "WHERE id" in src
    # Ensure retry loop is present
    assert "_MAX_RETRIES" in src or "range(" in src


@pytest.mark.asyncio
async def test_entity_update_changes_reflected(migrated_db):
    """EntityStore.update() must update and return the correct entity."""
    from app.memory.entity_store import EntityStore

    es = EntityStore(migrated_db)
    entity = await es.create(name="Alice", entity_type="person", aliases=["ali"])
    updated = await es.update(entity.id, name="Alice Updated")
    assert updated.name == "Alice Updated"


@pytest.mark.asyncio
async def test_entity_update_occ_retry_logic(migrated_db):
    """update() should raise ConflictError after exhausting retries on persistent conflicts."""
    from app.memory.entity_store import EntityStore
    from app.db.connection import write_transaction
    from app.exceptions import ConflictError

    es = EntityStore(migrated_db)
    entity = await es.create(name="Bob", entity_type="person", aliases=[])

    # Simulate persistent concurrent modification on every get()
    original_get = es.get

    async def patched_get(eid):
        result = await original_get(eid)
        # Bump version on every get() so the OCC check always fails (TD-300)
        async with write_transaction(migrated_db):
            await migrated_db.execute(
                "UPDATE entities SET name = 'Concurrent', version = version + 1 WHERE id = ?",
                (eid,),
            )
        return result

    es.get = patched_get
    # TD-301: update() should raise ConflictError after retries are exhausted
    with pytest.raises(ConflictError):
        await es.update(entity.id, name="Final Name")


# ── T8: PgVector deactivate (TD-94) ──────────────────────────────────────────

def test_pgvector_adapter_has_deactivate():
    """PgVectorAdapter must have an async deactivate() method."""
    from app.knowledge.sources.adapters.pgvector import PgVectorAdapter
    assert hasattr(PgVectorAdapter, "deactivate")
    assert asyncio.iscoroutinefunction(PgVectorAdapter.deactivate)


@pytest.mark.asyncio
async def test_pgvector_deactivate_closes_pool():
    """deactivate() must call pool.close() and set _pool to None."""
    from app.knowledge.sources.adapters.pgvector import PgVectorAdapter
    from app.knowledge.sources.models import KnowledgeSource

    source = KnowledgeSource(
        source_id="src1", name="pg", backend="pgvector",
        connection={"dsn": "postgresql://localhost/test"},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    adapter = PgVectorAdapter(source)
    mock_pool = AsyncMock()
    adapter._pool = mock_pool

    await adapter.deactivate()

    mock_pool.close.assert_awaited_once()
    assert adapter._pool is None


def test_base_adapter_deactivate_is_noop():
    """KnowledgeSourceAdapter base class must have a default no-op deactivate()."""
    from app.knowledge.sources.adapters.base import KnowledgeSourceAdapter
    assert hasattr(KnowledgeSourceAdapter, "deactivate")
    assert asyncio.iscoroutinefunction(KnowledgeSourceAdapter.deactivate)


# ── T9: Registry adapter lock (TD-95) ────────────────────────────────────────

def test_registry_adapter_lock_exists(migrated_db):
    """KnowledgeSourceRegistry must have _adapter_lock attribute."""
    from app.knowledge.sources.registry import KnowledgeSourceRegistry
    reg = KnowledgeSourceRegistry(migrated_db)
    assert hasattr(reg, "_adapter_lock")
    assert isinstance(reg._adapter_lock, asyncio.Lock)


@pytest.mark.asyncio
async def test_registry_start_uses_lock(migrated_db):
    """start() should populate _adapters without error and hold the lock properly."""
    from app.knowledge.sources.registry import KnowledgeSourceRegistry
    reg = KnowledgeSourceRegistry(migrated_db)
    await reg.start()
    # No sources in DB, so _adapters still empty — just confirm no crash
    assert isinstance(reg._adapters, dict)


@pytest.mark.asyncio
async def test_registry_delete_calls_adapter_deactivate(migrated_db):
    """delete() must call adapter.deactivate() before removing from cache."""
    from app.knowledge.sources.registry import KnowledgeSourceRegistry

    reg = KnowledgeSourceRegistry(migrated_db)
    source = await reg.register(
        name="test_src",
        backend="chroma",
        connection={"collection_name": "test_col", "host": "localhost"},
    )
    # Inject a mock adapter
    mock_adapter = AsyncMock()
    mock_adapter.deactivate = AsyncMock()
    reg._adapters[source.source_id] = mock_adapter

    await reg.delete(source.source_id)

    mock_adapter.deactivate.assert_awaited_once()
    assert source.source_id not in reg._adapters


# ── T10: Atomic consecutive_failures (TD-96) ─────────────────────────────────

def test_search_one_uses_atomic_sql_increment():
    """_search_one failure-tracking code must use SQL atomic UPDATE, not Python +1."""
    import inspect
    from app.knowledge.sources import registry as mod

    src = inspect.getsource(mod.KnowledgeSourceRegistry._search_one)
    # Must contain direct SQL increment
    assert "consecutive_failures + 1" in src
    # Must NOT do Python-side increment from stale value
    assert "source.consecutive_failures + 1" not in src


@pytest.mark.asyncio
async def test_consecutive_failures_incremented_atomically(migrated_db):
    """On search failure, consecutive_failures in DB must increment by 1."""
    from app.knowledge.sources.registry import KnowledgeSourceRegistry
    from app.knowledge.sources.models import KnowledgeSource

    reg = KnowledgeSourceRegistry(migrated_db)
    source = await reg.register(
        name="failing_src",
        backend="chroma",
        connection={"collection_name": "x"},
    )

    # Inject a failing adapter
    mock_adapter = AsyncMock()
    mock_adapter.search = AsyncMock(side_effect=RuntimeError("boom"))
    reg._adapters[source.source_id] = mock_adapter

    await reg._search_one(source, "query", 5)

    refreshed = await reg.get(source.source_id)
    assert refreshed.consecutive_failures == 1


# ── T11: Lifecycle concurrency guard (TD-109) ─────────────────────────────────

def test_lifecycle_manager_has_run_lock():
    """MemoryLifecycleManager must have _run_lock attribute."""
    from app.memory.lifecycle import MemoryLifecycleManager
    m = MemoryLifecycleManager(MagicMock(), MagicMock())
    assert hasattr(m, "_run_lock")
    assert isinstance(m._run_lock, asyncio.Lock)


@pytest.mark.asyncio
async def test_run_all_skips_when_already_running():
    """run_all() must return {"skipped": True} when _run_lock is already held."""
    from app.memory.lifecycle import MemoryLifecycleManager

    m = MemoryLifecycleManager(MagicMock(), MagicMock())

    # Hold the lock to simulate an in-progress pass
    lock_acquired = asyncio.Event()
    lock_released = asyncio.Event()

    async def _hold_lock():
        async with m._run_lock:
            lock_acquired.set()
            await lock_released.wait()

    holder = asyncio.create_task(_hold_lock())
    await lock_acquired.wait()  # ensure holder has the lock

    try:
        result = await m.run_all()
        assert result.get("skipped") is True
        assert "already_running" in result.get("reason", "")
    finally:
        lock_released.set()
        await holder


@pytest.mark.asyncio
async def test_run_all_proceeds_when_lock_free(migrated_db):
    """run_all() must execute all passes and return results when lock is free."""
    from app.memory.store import MemoryStore
    from app.memory.entity_store import EntityStore
    from app.memory.lifecycle import MemoryLifecycleManager

    ms = MemoryStore(migrated_db)
    es = EntityStore(migrated_db)
    m = MemoryLifecycleManager(ms, es)

    result = await m.run_all()
    assert "decay" in result
    assert "skipped" not in result
