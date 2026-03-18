"""Core agent turn loop — 7-step cycle (§4.3, Sprint 05).

Flow
----
1. Route ``inbound.message`` → ``TurnLoop.handle_inbound()``
2. Load session + agent config, persist user message.
3. Assemble prompt from active message chain via ``assemble_prompt()``.
4. Stream completion from provider.
5. Forward stream events as ``agent.run.stream`` gateway events (→ WebSocket → frontend).
6. Detect tool calls from stream → policy check → approval gate → execute.
   Loop back to step 3 with tool results injected.  Max rounds: ``policy.max_tool_rounds``.
7. Persist final assistant message.  Emit ``agent.run.complete``.
   Post-turn stubs: extraction check, budget tracker, audit event.

Event payload contract
----------------------
The ``inbound.message`` event's ``payload`` dict must contain:

``session_id``   — session identifier (required)
``content``      — message text (required)
``user_name``    — display name for prompt assembly (optional)
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from app.agent.context import get_or_create_budget
from app.agent.models import AgentConfig
from app.agent.prompt_assembly import AssemblyContext, assemble_prompt
from app.agent.store import AgentStore, get_agent_store
from app.constants import DEFAULT_MODEL
from app.exceptions import NotFoundError
from app.gateway.events import ET, EventSource, GatewayEvent, StreamPayload
from app.gateway.router import GatewayRouter, get_router
from app.providers.base import Message as ProviderMessage
from app.providers.base import ToolDef, ToolResult
from app.providers.circuit_breaker import CircuitOpenError, get_circuit_breaker
from app.providers.registry import get_registry as get_provider_registry
from app.sessions.messages import MessageStore, get_message_store
from app.sessions.models import Session
from app.sessions.store import SessionStore, get_session_store
from app.tools.executor import ToolExecutor, get_tool_executor
from app.tools.registry import ToolRegistry, get_tool_registry

logger = logging.getLogger(__name__)

_SYSTEM_SOURCE = EventSource(kind="system", id="turn_loop")


class TurnLoop:
    """Wires together prompt assembly, provider streaming, and tool execution.

    Instantiate once at startup and register ``handle_inbound`` on the router::

        loop = TurnLoop(router=get_router())
        router.on(ET.INBOUND_MESSAGE, loop.handle_inbound)
    """

    def __init__(
        self,
        router: GatewayRouter | None = None,
        agent_store: AgentStore | None = None,
        session_store: SessionStore | None = None,
        message_store: MessageStore | None = None,
        tool_executor: ToolExecutor | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self._router = router or get_router()
        self._agent_store = agent_store or get_agent_store()
        self._session_store = session_store or get_session_store()
        self._message_store = message_store or get_message_store()
        self._executor = tool_executor or get_tool_executor()
        self._registry = tool_registry or get_tool_registry()
        # TD-201: Per-session lock to prevent parallel turns corrupting state
        # TD-283: Use OrderedDict with max size to prevent unbounded growth
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._max_session_locks = 1000

    def _get_session_lock(self, session_key: str) -> asyncio.Lock:
        """Return the lock for *session_key*, evicting oldest if at capacity.

        TD-343: Only unlocked entries are evicted to avoid discarding a lock
        that is currently held by another coroutine (which would allow two
        concurrent turns on the same session).
        """
        if session_key in self._session_locks:
            # Move to end (most recently used)
            lock = self._session_locks.pop(session_key)
            self._session_locks[session_key] = lock
            return lock
        if len(self._session_locks) >= self._max_session_locks:
            # Evict oldest *unlocked* entry to avoid racing with held locks
            for key in list(self._session_locks):
                if not self._session_locks[key].locked():
                    del self._session_locks[key]
                    break
            else:
                # All locks are held — log and continue without eviction
                logger.warning(
                    "TurnLoop: session lock table at capacity (%d), all held",
                    self._max_session_locks,
                )
        lock = asyncio.Lock()
        self._session_locks[session_key] = lock
        return lock

    # ── Gateway handler ───────────────────────────────────────────────────────

    async def handle_inbound(self, event: GatewayEvent) -> None:
        """Entry point called by the gateway router for ``inbound.message``."""
        payload = event.payload
        session_id: str = payload.get("session_id", "")
        content: str = payload.get("content", "")
        user_name: str = payload.get("user_name", "")

        if not session_id:
            logger.error("handle_inbound: missing session_id in event payload")
            return
        if not content:
            logger.warning("handle_inbound: empty content — skipping turn")
            return

        await self._run_full_turn(
            session_key=event.session_key,
            session_id=session_id,
            user_content=content,
            user_name=user_name,
        )

    # ── Public entry point (for API / branching) ──────────────────────────────

    async def run_turn_from_api(
        self,
        *,
        session_id: str,
        session_key: str,
        user_content: str,
        user_name: str = "",
    ) -> None:
        """Start a turn from the API layer (e.g. POST /messages or /regenerate)."""
        await self._run_full_turn(
            session_key=session_key,
            session_id=session_id,
            user_content=user_content,
            user_name=user_name,
        )

    # ── Core execution ────────────────────────────────────────────────────────

    async def _run_full_turn(
        self,
        *,
        session_key: str,
        session_id: str,
        user_content: str,
        user_name: str = "",
    ) -> None:
        """Execute one full turn: user message → assistant response."""
        # TD-201: Acquire per-session lock to prevent parallel turns
        # TD-283: Use LRU-evicting helper instead of raw dict access
        async with self._get_session_lock(session_key):
            # TD-206: Track active turns for accurate counting
            from app.sessions.store import mark_turn_active, mark_turn_inactive
            mark_turn_active(session_key)
            try:
                await self._run_full_turn_inner(
                    session_key=session_key,
                    session_id=session_id,
                    user_content=user_content,
                    user_name=user_name,
                )
            finally:
                mark_turn_inactive(session_key)

    async def _run_full_turn_inner(
        self,
        *,
        session_key: str,
        session_id: str,
        user_content: str,
        user_name: str = "",
    ) -> None:
        """Inner implementation of a full turn (wrapped by _run_full_turn)."""
        # ── Step 1: Load session + agent config ───────────────────────────────
        try:
            session = await self._session_store.get_by_id(session_id)
        except NotFoundError:
            logger.error("TurnLoop: session %r not found", session_id)
            return

        try:
            agent_config = await self._agent_store.get_by_id(session.agent_id)
        except NotFoundError:
            logger.info("Agent %r not found for session %s, using default config", session.agent_id, session_id)
            from app.agent.models import AgentConfig, SoulConfig
            agent_config = AgentConfig(
                agent_id=session.agent_id,
                name="assistant",
                soul=SoulConfig(persona="a helpful assistant"),
            )
        except Exception:
            logger.warning("Unexpected error loading agent %r, using default config", session.agent_id, exc_info=True)
            from app.agent.models import AgentConfig, SoulConfig
            agent_config = AgentConfig(
                agent_id=session.agent_id,
                name="assistant",
                soul=SoulConfig(persona="a helpful assistant"),
            )

        # Resolve provider from qualified model ID (e.g. "anthropic:claude-sonnet-4-5")
        qualified_model = getattr(agent_config, "default_model", "") or DEFAULT_MODEL
        try:
            provider, model = get_provider_registry().get_provider_for_model(qualified_model)
        except Exception:
            await self._emit_error(session_key, f"Provider not available for model {qualified_model!r}")
            return

        # ── Step 2: Persist user message ──────────────────────────────────────
        try:
            user_msg = await self._message_store.insert(
                session_id=session_id,
                role="user",
                content=user_content,
                provenance="user_input",
                active=True,
            )
        except Exception as exc:
            logger.error("Failed to persist user message: %s", exc)
            await self._emit_error(session_key, "Failed to persist user message")
            return

        # Emit run start
        await self._emit(session_key, ET.AGENT_RUN_START, {
            "session_id": session_id,
            "user_message_id": user_msg.id,
        })

        # ── Main tool loop ─────────────────────────────────────────────────────
        policy = session.policy
        max_rounds = getattr(policy, "max_tool_rounds", 25)
        tool_round = 0
        final_text = ""
        final_tool_calls: list[dict[str, Any]] = []
        in_tokens = 0
        out_tokens = 0

        # Build tool defs from registry
        all_tool_defs = self._get_tool_defs()

        try:
            while tool_round <= max_rounds:
                # ── Step 3: Assemble prompt ────────────────────────────────────
                messages = await self._assemble(
                    session_id=session_id,
                    agent_config=agent_config,
                    user_name=user_name,
                    tool_defs=all_tool_defs,
                )

                # ── Step 3b: Context compression (Sprint 07) ─────────────────────
                budget = get_or_create_budget(session_id, qualified_model)
                if budget.needs_compression(messages):
                    logger.info(
                        "TurnLoop: context at %.0f%% — compressing (session=%s)",
                        budget.usage_ratio(messages) * 100,
                        session_id,
                    )
                    messages = await budget.auto_compress(
                        messages, provider=provider, model=model
                    )

                # ── Step 4 + 5: Stream from provider + forward events ───────────
                cb = get_circuit_breaker(getattr(provider, 'provider_id', 'unknown'))
                try:
                    text_acc, tool_calls_raw, i_tok, o_tok = await self._stream_and_forward(
                        provider=provider,
                        messages=messages,
                        model=model,
                        tool_defs=all_tool_defs,
                        session_key=session_key,
                        policy=policy,
                    )
                    await cb.record_success()
                except CircuitOpenError as exc:
                    await self._emit_error(
                        session_key,
                        f"Provider circuit is OPEN — {exc}. Please try again later.",
                    )
                    return
                except Exception:
                    await cb.record_failure()
                    raise
                in_tokens += i_tok
                out_tokens += o_tok

                if not tool_calls_raw:
                    # No tool calls → final response
                    final_text = text_acc
                    break

                # ── Step 6: Execute tool calls ─────────────────────────────────
                tool_round += 1
                if tool_round > max_rounds:
                    logger.warning(
                        "Max tool rounds (%d) reached for session %s", max_rounds, session_id
                    )
                    final_text = text_acc or "[max tool rounds reached]"
                    break

                tool_results = await self._executor.execute_many(
                    tool_calls_raw,
                    policy=policy,
                    session_key=session_key,
                )

                # Persist assistant message with tool calls
                await self._message_store.insert(
                    session_id=session_id,
                    role="assistant",
                    content=text_acc,
                    tool_calls=[{
                        "tool_call_id": tc["tool_call_id"],
                        "tool_name": tc["tool_name"],
                        "arguments": tc.get("arguments", {}),
                        "approval_status": "auto_approved",
                    } for tc in tool_calls_raw],
                    provenance="assistant_response",
                    active=True,
                    model=model,
                    input_tokens=i_tok,
                    output_tokens=o_tok,
                )
                final_tool_calls.extend(tool_calls_raw)

                # Persist tool_result messages
                for result in tool_results:
                    result_text = (
                        result.result
                        if isinstance(result.result, str)
                        else json.dumps(result.result)
                    )
                    await self._message_store.insert(
                        session_id=session_id,
                        role="tool_result",
                        content=result_text,
                        tool_call_id=result.tool_call_id,
                        provenance="tool_result",
                        active=True,
                    )

                    # Forward tool result stream event
                    await self._emit_stream(session_key, StreamPayload(
                        kind="tool_result",
                        tool_call_id=result.tool_call_id,
                        tool_result={
                            "success": result.success,
                            "result": result.result,
                            "error": result.error,
                            "execution_time_ms": result.execution_time_ms,
                        },
                    ))

        except Exception as exc:
            logger.exception("TurnLoop error in session %s", session_id)
            await self._emit_error(session_key, str(exc))
            self._executor.clear_turn_state(session_key)
            return

        # ── Step 7: Persist final assistant message ────────────────────────────
        final_msg = await self._message_store.insert(
            session_id=session_id,
            role="assistant",
            content=final_text,
            provenance="assistant_response",
            active=True,
            model=model,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
        )

        # Emit run complete
        await self._emit(session_key, ET.AGENT_RUN_COMPLETE, {
            "session_id": session_id,
            "message_id": final_msg.id,
            "content": final_text,
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
            "tool_rounds": tool_round,
        })

        # ── Post-turn stubs ────────────────────────────────────────────────────
        await self._post_turn_hooks(session_id, session_key, final_msg.id, in_tokens, out_tokens)

        # Clear per-turn approval state
        self._executor.clear_turn_state(session_key)

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _assemble(
        self,
        *,
        session_id: str,
        agent_config: AgentConfig,
        user_name: str = "",
        tool_defs: list[ToolDef] | None = None,
    ) -> list[ProviderMessage]:
        """Assemble the full prompt for this turn."""
        # Get active chain (all messages, newest last)
        active_chain = await self._message_store.get_active_chain(session_id)

        if not active_chain:
            return []

        # Split history from current user message
        history_rows: list[dict[str, Any]] = []
        current_content = ""

        if active_chain:
            # TD-276: Detect tool continuation — last message may be a tool_result,
            # not a user message. Only treat final message as user input if role=user.
            last = active_chain[-1]
            is_tool_continuation = last.role in ("tool_result", "tool")

            if is_tool_continuation:
                # All messages go into history; user_message is empty for continuation
                current_content = ""
                history_rows = [
                    {
                        "role": m.role if m.role != "tool_result" else "tool",
                        "content": m.content,
                        "tool_call_id": m.tool_call_id,
                        "tool_calls": [tc.model_dump() for tc in m.tool_calls] if m.tool_calls else None,
                    }
                    for m in active_chain
                ]
            else:
                current_content = last.content
                history_rows = [
                    {
                        "role": m.role if m.role != "tool_result" else "tool",
                        "content": m.content,
                        "tool_call_id": m.tool_call_id,
                        "tool_calls": [tc.model_dump() for tc in m.tool_calls] if m.tool_calls else None,
                    }
                    for m in active_chain[:-1]
                ]

        ctx = AssemblyContext(
            agent_config=agent_config,
            user_message=current_content,
            session_history=history_rows,
            user_name=user_name,
            tools=tool_defs or [],
        )

        # ── Sprint 10: Recall pipeline ────────────────────────────────────────
        agent_id_str = str(agent_config.agent_id) if agent_config.agent_id else None
        try:
            from app.memory.recall import get_recall_pipeline
            recall = get_recall_pipeline()
            ctx.memory_always, _always_memories = await recall.load_always_recall(
                session_id=session_id,
                agent_id=agent_id_str,
            )
            ctx.memory_recall, ctx.knowledge_context = await recall.recall_for_turn(
                user_message=current_content,
                session_id=session_id,
                agent_id=agent_id_str,
                always_recall_content=ctx.memory_always,
                always_memories=_always_memories,
            )
            # TD-348: Capture recalled IDs synchronously (no await between here and
            # create_task) so concurrent sessions cannot overwrite the instance attr.
            _prefetch_ids = list(getattr(recall, "_last_recalled_ids", None) or [])
            # TD-218: Track fire-and-forget tasks with exception logging
            task = asyncio.create_task(
                recall.prefetch_background(
                    user_message=current_content,
                    session_id=session_id,
                    agent_id=agent_id_str,
                    recalled_ids=_prefetch_ids,
                )
            )
            task.add_done_callback(lambda t: t.exception() and logger.warning("Recall prefetch error: %s", t.exception()))
        except RuntimeError:
            pass  # RecallPipeline not yet initialised (tests / first startup)
        except Exception as exc:
            logger.debug("Recall pipeline error (graceful degradation): %s", exc)

        return await assemble_prompt(ctx)

    async def _stream_and_forward(
        self,
        *,
        provider: Any,
        messages: list[ProviderMessage],
        model: str,
        tool_defs: list[ToolDef] | None,
        session_key: str,
        policy: Any,
    ) -> tuple[str, list[dict[str, Any]], int, int]:
        """Stream a completion, forwarding events via gateway.

        Returns ``(text, tool_calls, input_tokens, output_tokens)``.
        ``tool_calls`` is a list of dicts with keys:
        ``tool_call_id``, ``tool_name``, ``arguments``.
        """
        text_parts: list[str] = []
        # tool_call_id → {name, args_delta, args}
        active_tool_calls: dict[str, dict[str, Any]] = {}
        completed_tool_calls: list[dict[str, Any]] = []
        in_tokens = 0
        out_tokens = 0

        # TD-366: stream_completion is an async generator — do NOT await it.
        stream = provider.stream_completion(
            messages=messages,
            model=model,
            tools=tool_defs or [],
        )

        async for event in stream:
            kind = event.kind

            if kind == "text_delta" and event.text:
                text_parts.append(event.text)
                await self._emit_stream(session_key, StreamPayload(
                    kind="text_delta",
                    text=event.text,
                ))

            elif kind == "tool_call_start":
                tc_id = event.tool_call_id or str(uuid.uuid4())
                active_tool_calls[tc_id] = {
                    "tool_call_id": tc_id,
                    "tool_name": event.tool_name or "",
                    "args_buffer": "",
                    "args": {},
                }
                await self._emit_stream(session_key, StreamPayload(
                    kind="tool_call_start",
                    tool_call_id=tc_id,
                    tool_name=event.tool_name,
                ))

            elif kind == "tool_call_delta":
                tc_id = event.tool_call_id or ""
                if tc_id in active_tool_calls and event.tool_args_delta:
                    active_tool_calls[tc_id]["args_buffer"] += event.tool_args_delta
                    await self._emit_stream(session_key, StreamPayload(
                        kind="tool_call_input_delta",
                        tool_call_id=tc_id,
                        tool_input={"delta": event.tool_args_delta},
                    ))

            elif kind == "tool_call_end":
                tc_id = event.tool_call_id or ""
                if tc_id in active_tool_calls:
                    entry = active_tool_calls.pop(tc_id)
                    args = event.tool_args or {}
                    if not args and entry["args_buffer"]:
                        try:
                            args = json.loads(entry["args_buffer"])
                        except json.JSONDecodeError:
                            args = {}
                    completed_tool_calls.append({
                        "tool_call_id": tc_id,
                        "tool_name": entry["tool_name"] or event.tool_name or "",
                        "arguments": args,
                    })

            elif kind == "usage":
                in_tokens = event.input_tokens or in_tokens
                out_tokens = event.output_tokens or out_tokens

            elif kind == "thinking" and event.text:
                await self._emit_stream(session_key, StreamPayload(
                    kind="thinking",
                    text=event.text,
                ))

            elif kind == "error":
                logger.warning(
                    "Provider stream error: %s", event.error_message
                )
                await self._emit_stream(session_key, StreamPayload(
                    kind="error",
                    error_message=event.error_message or "Unknown provider error",
                ))

            elif kind == "done":
                break

        return "".join(text_parts), completed_tool_calls, in_tokens, out_tokens

    def _get_tool_defs(self) -> list[ToolDef]:
        """Convert registered tools to provider ToolDef objects."""
        defs: list[ToolDef] = []
        for td in self._registry.list():
            defs.append(ToolDef(
                name=td.name,
                description=td.description,
                parameters=td.parameters,
                safety=td.safety,
            ))
        return defs

    async def _emit(self, session_key: str, event_type: str, payload: dict[str, Any]) -> None:
        """Emit a gateway event."""
        event = GatewayEvent(
            event_type=event_type,
            source=_SYSTEM_SOURCE,
            session_key=session_key,
            payload=payload,
        )
        await self._router.emit(event)

    async def _emit_stream(self, session_key: str, stream_payload: StreamPayload) -> None:
        """Emit an agent.run.stream event."""
        await self._emit(session_key, ET.AGENT_RUN_STREAM, stream_payload.model_dump())

    async def _emit_error(self, session_key: str, message: str) -> None:
        """Emit an agent.run.error event."""
        await self._emit(session_key, ET.AGENT_RUN_ERROR, {"error": message})

    async def _post_turn_hooks(
        self,
        session_id: str,
        session_key: str,
        message_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Run post-turn hooks — extraction trigger, budget, audit."""
        # § Sprint 10: Trigger extraction pipeline if interval reached
        try:
            from app.memory.extraction import get_extraction_pipeline
            pipeline = get_extraction_pipeline()
            if pipeline.config.enabled:
                # Count messages in session to determine trigger
                messages = await self._message_store.get_active_chain(session_id)
                msg_count = len(messages)
                if msg_count > 0 and msg_count % pipeline.config.trigger_interval_messages == 0:
                    # TD-218: Track extraction task with exception logging
                    ext_task = asyncio.create_task(
                        self._run_extraction(session_id, messages)
                    )
                    ext_task.add_done_callback(lambda t: t.exception() and logger.warning("Extraction task error: %s", t.exception()))
        except RuntimeError:
            pass  # ExtractionPipeline not yet initialised
        except Exception as exc:
            logger.debug("Post-turn extraction check failed: %s", exc)

        # § budget tracking
        await self._emit(session_key, ET.BUDGET_TURN_COST, {
            "session_id": session_id,
            "message_id": message_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        })

    async def _run_extraction(self, session_id: str, messages: list) -> None:
        """Run extraction pipeline in the background (Sprint 10 §5.5)."""
        try:
            from app.memory.extraction import get_extraction_pipeline
            pipeline = get_extraction_pipeline()
            msg_dicts = [
                {"role": m.role, "content": m.content}
                for m in messages
                if m.role in ("user", "assistant")
            ]
            result = await pipeline.run(session_id=session_id, messages=msg_dicts)
            logger.debug(
                "Extraction complete for session %s: created=%d merged=%d skipped=%d",
                session_id,
                result.created,
                result.merged,
                result.skipped,
            )
        except Exception as exc:
            logger.debug("Background extraction failed for session %s: %s", session_id, exc)


# ── Singleton ─────────────────────────────────────────────────────────────────

_turn_loop: TurnLoop | None = None


def get_turn_loop() -> TurnLoop:
    """Return the process-wide ``TurnLoop`` singleton."""
    global _turn_loop
    if _turn_loop is None:
        _turn_loop = TurnLoop()
    return _turn_loop


def init_turn_loop(router: GatewayRouter) -> TurnLoop:
    """Create and wire the TurnLoop.  Call once in FastAPI lifespan startup."""
    global _turn_loop
    _turn_loop = TurnLoop(router=router)
    router.on(ET.INBOUND_MESSAGE, _turn_loop.handle_inbound)
    logger.info("TurnLoop initialised and registered on INBOUND_MESSAGE")
    return _turn_loop
