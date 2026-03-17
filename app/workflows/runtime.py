"""Workflow execution runtime — pipeline and parallel modes (§10.1–10.2, Sprint 08).

Execution modes
---------------
**Pipeline** (``mode="pipeline"``)
    Steps run sequentially.  The output of step *N* is injected into step *N+1*
    via ``{context}`` substitution in the prompt template.  If *N* fails
    (after all retries) the run transitions to ``failed`` and remaining steps
    are skipped.

**Parallel** (``mode="parallel"``)
    All steps run concurrently via ``asyncio.gather``.  A global semaphore
    (``MAX_CONCURRENT_SUBAGENTS``) limits simultaneous active sessions.
    Results are collected when every step finishes.  If any step fails the
    run transitions to ``failed`` (other already-running steps are not
    cancelled).

Step execution
--------------
Each step spawns a sub-agent session, emits the step prompt (with optional
context substitution), then subscribes to ``agent.run.complete`` on the
gateway router and waits up to *step.timeout_s* seconds.  The last assistant
message from the step session is collected as the step result.

Retries
-------
If a step raises or the agent does not reply within the timeout the step is
retried up to *step.retry* times before being marked as failed.
"""
from __future__ import annotations

import asyncio
import logging

from app.agent.sub_agent import spawn_sub_agent
from app.constants import MAX_CONCURRENT_SUBAGENTS
from app.gateway.events import ET, GatewayEvent
from app.gateway.router import get_router
from app.sessions.messages import get_message_store
from app.sessions.store import get_session_store
from app.workflows.models import Workflow, WorkflowRun, WorkflowStep
from app.workflows.store import get_workflow_store

logger = logging.getLogger(__name__)

_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """Return (lazily creating) the process-wide concurrency semaphore."""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT_SUBAGENTS)
    return _semaphore


# ── Step execution ─────────────────────────────────────────────────────────────


async def _run_step(
    step: WorkflowStep,
    context: str = "",
    parent_session_key: str | None = None,
) -> str:
    """Execute one workflow *step* and return its text result.

    Spawns a sub-agent session for the step, emits the (optionally
    context-injected) prompt, then waits for ``agent.run.complete``.

    Raises
    ------
    RuntimeError
        When the step times out or encounters an unrecoverable error.
    """
    # Build prompt — inject {context} from previous step if present
    prompt = step.prompt_template
    if "{context}" in prompt and context:
        prompt = prompt.replace("{context}", context)
    elif "{context}" in prompt:
        prompt = prompt.replace("{context}", "(no previous context)")

    sem = _get_semaphore()
    async with sem:
        sub_key = await spawn_sub_agent(
            agent_id=step.agent_id,
            initial_message=prompt,
            policy_preset="worker",
            parent_session_key=parent_session_key,
            auto_archive_minutes=5,  # quick cleanup for workflow steps
        )

        _router = get_router()
        done = asyncio.Event()

        async def _on_complete(evt: GatewayEvent) -> None:
            if evt.session_key == sub_key:
                done.set()

        _router.on(ET.AGENT_RUN_COMPLETE, _on_complete)
        try:
            await asyncio.wait_for(done.wait(), timeout=float(step.timeout_s))
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"Step {step.id!r} timed out after {step.timeout_s}s"
            )
        finally:
            _router.off(ET.AGENT_RUN_COMPLETE, _on_complete)

        # Collect result — last assistant message in the step session
        msg_store = get_message_store()
        # TD-47: sub_key is a session_key string; list_by_session needs session_id (UUID)
        session_store = get_session_store()
        session = await session_store.get_by_key(sub_key)
        messages = await msg_store.list_by_session(session.session_id, limit=50, active_only=True)
        assistant_msgs = [m for m in messages if m.role == "assistant"]
        if assistant_msgs:
            return assistant_msgs[-1].content
        return ""


async def _run_step_with_retry(
    step: WorkflowStep,
    context: str = "",
    parent_session_key: str | None = None,
) -> str:
    """Wrap ``_run_step`` with per-step retry logic."""
    last_exc: Exception | None = None
    attempts = step.retry + 1
    for attempt in range(1, attempts + 1):
        try:
            return await _run_step(step, context, parent_session_key)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Step %r attempt %d/%d failed: %s",
                step.id, attempt, attempts, exc,
            )
    raise RuntimeError(f"Step {step.id!r} failed after {attempts} attempt(s): {last_exc}")


# ── Pipeline execution ─────────────────────────────────────────────────────────


async def run_pipeline(
    workflow: Workflow,
    run: WorkflowRun,
    *,
    parent_session_key: str | None = None,
    cancel_event: asyncio.Event | None = None,
) -> WorkflowRun:
    """Execute *workflow* in pipeline mode, updating *run* in the store.

    Steps execute sequentially.  Each step's output is passed as ``{context}``
    to the next step's prompt template.

    Returns the updated ``WorkflowRun`` (either ``completed``, ``failed``, or
    ``cancelled`` when *cancel_event* is set between steps).
    """
    store = get_workflow_store()

    run = await store.update_run_status(run.id, status="running")
    context = ""

    for step in workflow.steps:
        # Check for cancellation before executing each step (TD-48)
        if cancel_event is not None and cancel_event.is_set():
            logger.info("Pipeline run %s cancelled before step %r", run.id, step.id)
            return await store.update_run_status(run.id, status="cancelled")
        run = await store.update_run_status(run.id, status="running", current_step=step.id)
        try:
            result = await _run_step_with_retry(step, context, parent_session_key)
            context = result
            run = await store.update_run_status(
                run.id,
                status="running",
                step_results={step.id: result},
            )
            logger.info("Pipeline step %r completed (%d chars)", step.id, len(result))
        except Exception as exc:
            logger.error("Pipeline step %r failed: %s", step.id, exc)
            return await store.update_run_status(
                run.id,
                status="failed",
                error=str(exc),
                current_step=step.id,
            )

    return await store.update_run_status(run.id, status="completed", current_step=None)


# ── Parallel execution ─────────────────────────────────────────────────────────


async def run_parallel(
    workflow: Workflow,
    run: WorkflowRun,
    *,
    parent_session_key: str | None = None,
    cancel_event: asyncio.Event | None = None,
) -> WorkflowRun:
    """Execute *workflow* in parallel mode, updating *run* in the store.

    All steps launch simultaneously (bounded by ``MAX_CONCURRENT_SUBAGENTS``).
    Collected results are written when all tasks finish.

    Returns the updated ``WorkflowRun`` (either ``completed``, ``failed``, or
    ``cancelled`` when *cancel_event* is already set at start).
    """
    store = get_workflow_store()

    # Check for pre-cancellation before launching tasks (TD-48)
    if cancel_event is not None and cancel_event.is_set():
        logger.info("Parallel run %s cancelled before starting", run.id)
        return await store.update_run_status(run.id, status="cancelled")

    run = await store.update_run_status(run.id, status="running")

    async def _task(step: WorkflowStep) -> tuple[str, str | None, str | None]:
        """Return (step_id, result_or_None, error_or_None)."""
        try:
            result = await _run_step_with_retry(step, "", parent_session_key)
            logger.info("Parallel step %r completed (%d chars)", step.id, len(result))
            return step.id, result, None
        except Exception as exc:
            logger.error("Parallel step %r failed: %s", step.id, exc)
            return step.id, None, str(exc)

    tasks = [asyncio.create_task(_task(s)) for s in workflow.steps]
    outcomes: list[tuple[str, str | None, str | None]] = await asyncio.gather(*tasks)

    step_results: dict[str, str] = {}
    failed_steps: list[str] = []
    error_details: list[str] = []
    for step_id, result, error in outcomes:
        if result is not None:
            step_results[step_id] = result
        else:
            failed_steps.append(step_id)
            if error:
                error_details.append(f"{step_id}: {error}")

    if failed_steps:
        error_msg = "; ".join(error_details) if error_details else f"Steps failed: {', '.join(failed_steps)}"
        return await store.update_run_status(
            run.id,
            status="failed",
            step_results=step_results,
            error=error_msg,
        )

    return await store.update_run_status(
        run.id,
        status="completed",
        step_results=step_results,
        current_step=None,
    )


# ── Dispatch ───────────────────────────────────────────────────────────────────


async def execute_workflow(
    workflow: Workflow,
    run: WorkflowRun,
    *,
    parent_session_key: str | None = None,
    cancel_event: asyncio.Event | None = None,
) -> WorkflowRun:
    """Dispatch *workflow* to the appropriate mode handler.

    This is the single entry point used by ``/api/workflows/{id}/run``.
    """
    if workflow.mode == "pipeline":
        return await run_pipeline(
            workflow, run,
            parent_session_key=parent_session_key,
            cancel_event=cancel_event,
        )
    elif workflow.mode == "parallel":
        return await run_parallel(
            workflow, run,
            parent_session_key=parent_session_key,
            cancel_event=cancel_event,
        )
    else:
        return await get_workflow_store().update_run_status(
            run.id,
            status="failed",
            error=f"Unknown workflow mode: {workflow.mode!r}",
        )
