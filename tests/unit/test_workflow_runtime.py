"""Sprint 08 — Unit tests for workflow runtime (§10.1, §10.2)."""
from __future__ import annotations

import asyncio
import pytest
import unittest.mock as mock


@pytest.fixture
async def workflow_store(migrated_db):
    """Initialise WorkflowStore against the test DB."""
    from app.workflows.store import init_workflow_store, get_workflow_store

    init_workflow_store(migrated_db)
    return get_workflow_store()


@pytest.fixture
def sample_step():
    from app.workflows.models import WorkflowStep
    return WorkflowStep(id="s1", agent_id="bot", prompt_template="Do: {context}")


@pytest.fixture
async def pipeline_workflow(workflow_store, sample_step):
    from app.workflows.models import WorkflowStep
    step2 = WorkflowStep(id="s2", agent_id="bot", prompt_template="Refine: {context}")
    return await workflow_store.create_workflow(
        name="Test Pipeline",
        mode="pipeline",
        steps=[sample_step, step2],
    )


@pytest.fixture
async def parallel_workflow(workflow_store, sample_step):
    from app.workflows.models import WorkflowStep
    step2 = WorkflowStep(id="s2b", agent_id="bot", prompt_template="Task B")
    return await workflow_store.create_workflow(
        name="Test Parallel",
        mode="parallel",
        steps=[sample_step, step2],
    )


# ── _run_step (unit) ──────────────────────────────────────────────────────────


async def test_run_step_substitutes_context():
    """_run_step substitutes {context} in the prompt template."""
    from app.workflows.runtime import _run_step
    from app.workflows.models import WorkflowStep

    step = WorkflowStep(id="s", agent_id="bot", prompt_template="Summary: {context}")
    captured_prompt = []

    async def fake_spawn(*, agent_id, initial_message=None, **kwargs):
        captured_prompt.append(initial_message)
        return "agent:bot:sub:test99"

    async def fake_list_by_session(sk, **kwargs):
        from app.sessions.models import Message
        from datetime import datetime, timezone
        return [Message(
            id="m1", session_id=sk, role="assistant", content="done",
            created_at=datetime.now(timezone.utc),
        )]

    # TD-47: _run_step now calls get_session_store().get_by_key(sub_key) first
    class FakeSession:
        session_id = "uuid-test-99"  # fake UUID returned from get_by_key

    fake_session_store = mock.MagicMock()
    fake_session_store.get_by_key = mock.AsyncMock(return_value=FakeSession())

    class FakeRouter:
        def on(self, event_type, handler):
            # immediately fire done — simulates instant agent completion
            asyncio.get_event_loop().call_soon(lambda: asyncio.create_task(
                _trigger(handler, sk="agent:bot:sub:test99")
            ))

        def off(self, *a, **kw):
            pass

    async def _trigger(handler, sk):
        from app.gateway.events import ET, EventSource, GatewayEvent
        evt = GatewayEvent(
            event_type=ET.AGENT_RUN_COMPLETE,
            source=EventSource(kind="system", id="test"),
            session_key=sk,
            payload={},
        )
        await handler(evt)

    with (
        mock.patch("app.workflows.runtime.spawn_sub_agent", fake_spawn),
        mock.patch("app.workflows.runtime.get_router", return_value=FakeRouter()),
        mock.patch(
            "app.workflows.runtime.get_session_store",
            return_value=fake_session_store,
        ),
        mock.patch(
            "app.workflows.runtime.get_message_store",
            return_value=mock.MagicMock(list_by_session=fake_list_by_session),
        ),
    ):
        result = await _run_step(step, context="previous result", parent_session_key=None)

    assert "Summary: previous result" in (captured_prompt[0] or "")
    assert result == "done"


# ── Pipeline ──────────────────────────────────────────────────────────────────


async def test_pipeline_completes_sequentially(workflow_store, pipeline_workflow):
    """Pipeline run should complete with results for both steps."""
    from app.workflows.models import WorkflowRun
    from app.workflows.runtime import run_pipeline

    run = await workflow_store.create_run(pipeline_workflow.id)

    step_call_order = []

    async def fake_step_with_retry(step, context="", parent_session_key=None):
        step_call_order.append(step.id)
        return f"result_of_{step.id}"

    with mock.patch("app.workflows.runtime._run_step_with_retry", fake_step_with_retry):
        completed_run = await run_pipeline(pipeline_workflow, run)

    assert completed_run.status == "completed"
    assert step_call_order == ["s1", "s2"]
    assert "s1" in completed_run.step_results
    assert "s2" in completed_run.step_results
    assert completed_run.step_results["s1"] == "result_of_s1"


async def test_pipeline_passes_context_between_steps(workflow_store, pipeline_workflow):
    """Pipeline passes each step's output to the next step as context."""
    from app.workflows.runtime import run_pipeline

    received_contexts = []

    async def fake_step_with_retry(step, context="", parent_session_key=None):
        received_contexts.append(context)
        return f"output_of_{step.id}"

    run = await workflow_store.create_run(pipeline_workflow.id)
    with mock.patch("app.workflows.runtime._run_step_with_retry", fake_step_with_retry):
        await run_pipeline(pipeline_workflow, run)

    # First step receives empty context, second receives first's output
    assert received_contexts[0] == ""
    assert received_contexts[1] == "output_of_s1"


async def test_pipeline_fails_on_step_error(workflow_store, pipeline_workflow):
    """When a step raises, the pipeline run transitions to failed."""
    from app.workflows.runtime import run_pipeline

    async def fake_step_with_retry(step, context="", parent_session_key=None):
        if step.id == "s1":
            raise RuntimeError("something went wrong")
        return "ok"

    run = await workflow_store.create_run(pipeline_workflow.id)
    with mock.patch("app.workflows.runtime._run_step_with_retry", fake_step_with_retry):
        completed_run = await run_pipeline(pipeline_workflow, run)

    assert completed_run.status == "failed"
    assert "something went wrong" in (completed_run.error or "")


# ── Parallel ──────────────────────────────────────────────────────────────────


async def test_parallel_completes_all_steps(workflow_store, parallel_workflow):
    """Parallel run executes all steps and collects their results."""
    from app.workflows.runtime import run_parallel

    async def fake_step_with_retry(step, context="", parent_session_key=None):
        return f"result_of_{step.id}"

    run = await workflow_store.create_run(parallel_workflow.id)
    with mock.patch("app.workflows.runtime._run_step_with_retry", fake_step_with_retry):
        completed_run = await run_parallel(parallel_workflow, run)

    assert completed_run.status == "completed"
    assert "s1" in completed_run.step_results
    assert "s2b" in completed_run.step_results


async def test_parallel_fails_when_any_step_errors(workflow_store, parallel_workflow):
    """Parallel run transitions to failed if any step raises."""
    from app.workflows.runtime import run_parallel

    async def fake_step_with_retry(step, context="", parent_session_key=None):
        if step.id == "s1":
            raise RuntimeError("step s1 failed")
        return "ok"

    run = await workflow_store.create_run(parallel_workflow.id)
    with mock.patch("app.workflows.runtime._run_step_with_retry", fake_step_with_retry):
        completed_run = await run_parallel(parallel_workflow, run)

    assert completed_run.status == "failed"
    assert "s1" in (completed_run.error or "")


# ── execute_workflow dispatch ─────────────────────────────────────────────────


async def test_execute_workflow_dispatches_pipeline(workflow_store, pipeline_workflow):
    from app.workflows.runtime import execute_workflow

    async def fake_pipeline(wf, run, **kwargs):
        from app.workflows.store import get_workflow_store
        return await get_workflow_store().update_run_status(run.id, status="completed")

    run = await workflow_store.create_run(pipeline_workflow.id)
    with mock.patch("app.workflows.runtime.run_pipeline", fake_pipeline):
        result = await execute_workflow(pipeline_workflow, run)

    assert result.status == "completed"


async def test_execute_workflow_dispatches_parallel(workflow_store, parallel_workflow):
    from app.workflows.runtime import execute_workflow

    async def fake_parallel(wf, run, **kwargs):
        from app.workflows.store import get_workflow_store
        return await get_workflow_store().update_run_status(run.id, status="completed")

    run = await workflow_store.create_run(parallel_workflow.id)
    with mock.patch("app.workflows.runtime.run_parallel", fake_parallel):
        result = await execute_workflow(parallel_workflow, run)

    assert result.status == "completed"
