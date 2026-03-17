"""FastAPI application factory for Tequila v2 (§13, §15).

``create_app()`` is the single entry point for constructing the FastAPI
instance.  It:

1. Records the startup timestamp.
2. Creates a lifespan that wires DB startup/shutdown, Alembic migrations,
   config hydration, gateway initialisation, and structured logging.
3. Registers all API routers.
4. Registers domain exception handlers.
5. Configures CORS for local development (frontend on port 5173 / 5174).
6. Mounts the compiled frontend static files (when present).

**Do not add route logic here.** Route functions belong in ``app/api/routers/``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.constants import APP_NAME, APP_VERSION
from app.exceptions import TequilaError

logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan context manager — startup then shutdown (§15)."""
    # ── STARTUP ───────────────────────────────────────────────────────────────

    # 1. Structured logging (configure before anything else so startup logs land)
    from app.config import get_settings
    from app.audit.logger import setup_logging

    settings = get_settings()
    log_level = "DEBUG" if settings.debug else "INFO"
    setup_logging(level=log_level, output="both")

    logger.info(
        "Tequila starting",
        extra={"version": APP_VERSION, "debug": settings.debug},
    )

    # 2. Record startup time for uptime reporting.
    from app.api.routers.system import record_startup_time
    record_startup_time()

    # 3. Create required data directories.
    from app.paths import ensure_dirs, db_path, alembic_dir
    ensure_dirs()
    db = db_path()
    logger.info("Filesystem paths ready", extra={"db_path": str(db)})

    # 4. Open database connection (WAL mode).
    from app.db import connection as db_conn
    try:
        await db_conn.startup(db)
    except Exception as exc:
        logger.critical(
            "Failed to open database — cannot start",
            extra={"db_path": str(db), "error": str(exc)},
        )
        raise RuntimeError(f"Database open failed: {exc}") from exc
    logger.info("Database connection open.")

    # 5. Run Alembic migrations.
    try:
        _run_migrations(alembic_dir())
    except Exception as exc:
        logger.critical("Alembic migration failed — cannot start", extra={"error": str(exc)})
        await db_conn.shutdown()
        raise

    # 6. Hydrate ConfigStore.
    from app.config import ConfigStore
    from app.api.deps import set_config_store
    config_store = ConfigStore(db_conn.get_app_db())
    await config_store.hydrate()
    set_config_store(config_store)
    logger.info("ConfigStore hydrated.")

    # 6b. Initialise credential encryption (Sprint 12).
    # TD-194: Derive key from env var instead of storing in plaintext DB.
    import os
    from app.auth.encryption import init_encryption, generate_key
    _enc_key = os.environ.get("TEQUILA_SECRET_KEY")
    if not _enc_key:
        # Fallback: check config store (legacy)
        _enc_key = config_store.get("auth.encryption_key", None)
    if not _enc_key:
        _enc_key = generate_key()
        logger.warning(
            "No TEQUILA_SECRET_KEY env var set. Generated ephemeral key. "
            "Set TEQUILA_SECRET_KEY for persistent credential encryption."
        )
    init_encryption(_enc_key)
    logger.info("Credential encryption ready.")

    # 7. Initialise GatewayRouter.
    from app.gateway.router import init_router
    init_router()
    logger.info("GatewayRouter ready.")

    # 8. Initialise SessionStore and MessageStore.
    from app.sessions.store import init_session_store, idle_detection_task
    from app.sessions.messages import init_message_store
    session_store = init_session_store(db_conn.get_app_db())
    init_message_store(db_conn.get_app_db())
    logger.info("SessionStore and MessageStore ready.")

    # 8b. Initialise AgentStore (Sprint 04).
    from app.agent.store import init_agent_store
    init_agent_store(db_conn.get_app_db())
    logger.info("AgentStore ready.")

    # 8c. Register LLM providers in ProviderRegistry (Sprint 04).
    from app.providers.registry import get_registry
    from app.providers.anthropic import AnthropicProvider
    from app.providers.openai import OpenAIProvider
    from app.providers.ollama import OllamaProvider

    registry = get_registry()
    for _provider_cls in (AnthropicProvider, OpenAIProvider, OllamaProvider):
        try:
            registry.register(_provider_cls())
        except Exception as _exc:
            logger.warning(
                "Skipping provider '%s' — could not initialise: %s",
                getattr(_provider_cls, "provider_id", _provider_cls.__name__),
                _exc,
            )
    provider_health = await registry.health_check_all()
    logger.info("ProviderRegistry ready", extra={"providers": provider_health})

    # 8d. Initialise TurnLoop and register on gateway (Sprint 05).
    from app.gateway.router import get_router
    from app.agent.turn_loop import init_turn_loop
    init_turn_loop(get_router())
    logger.info("TurnLoop initialised.")

    # 8e. Initialise WebCache (Sprint 06).
    from app.db.web_cache import init_web_cache
    init_web_cache(db_conn.get_app_db())
    logger.info("WebCache initialised.")

    # 8g. Initialise WorkflowStore (Sprint 08).
    from app.workflows.store import init_workflow_store
    init_workflow_store(db_conn.get_app_db())
    logger.info("WorkflowStore initialised.")

    # 8h. Initialise VaultStore (Sprint 09).
    from app.knowledge.vault import init_vault_store
    init_vault_store(db_conn.get_app_db())
    logger.info("VaultStore initialised.")

    # 8i. Initialise EmbeddingStore (Sprint 09).
    from app.knowledge.embeddings import init_embedding_store
    init_embedding_store(db_conn.get_app_db())
    logger.info("EmbeddingStore initialised.")

    # 8j. Initialise MemoryStore (Sprint 09).
    from app.memory.store import init_memory_store
    init_memory_store(db_conn.get_app_db())
    logger.info("MemoryStore initialised.")

    # 8k. Initialise EntityStore (Sprint 09).
    from app.memory.entity_store import init_entity_store
    init_entity_store(db_conn.get_app_db())
    logger.info("EntityStore initialised.")

    # 8l. Initialise KnowledgeSourceRegistry (Sprint 10).
    from app.knowledge.sources.registry import init_knowledge_source_registry
    kb_registry = init_knowledge_source_registry(db_conn.get_app_db())
    await kb_registry.start()
    logger.info("KnowledgeSourceRegistry initialised.")

    # 8m. Initialise ExtractionPipeline (Sprint 10).
    from app.memory.extraction import init_extraction_pipeline
    init_extraction_pipeline()
    logger.info("ExtractionPipeline initialised.")

    # 8n. Initialise RecallPipeline (Sprint 10).
    from app.memory.recall import init_recall_pipeline
    init_recall_pipeline()
    logger.info("RecallPipeline initialised.")

    # 8o. Initialise MemoryAuditLog (Sprint 11).
    from app.memory.audit import init_memory_audit
    init_memory_audit(db_conn.get_app_db())
    logger.info("MemoryAuditLog initialised.")

    # 8p. Initialise GraphStore (Sprint 11).
    from app.knowledge.graph import init_graph_store
    init_graph_store(db_conn.get_app_db())
    logger.info("GraphStore initialised.")

    # 8q. Initialise MemoryLifecycleManager (Sprint 11).
    from app.memory.lifecycle import init_lifecycle_manager
    from app.memory.store import get_memory_store as _get_mem
    from app.memory.entity_store import get_entity_store as _get_ent
    try:
        from app.memory.audit import get_memory_audit as _get_audit
        _audit_ref = _get_audit()
    except RuntimeError:
        _audit_ref = None
    init_lifecycle_manager(
        memory_store=_get_mem(),
        entity_store=_get_ent(),
        audit_log=_audit_ref,
    )
    logger.info("MemoryLifecycleManager initialised.")

    # 8f. Register all built-in tools (Sprint 06).
    from app.tools.builtin import register_all_builtin_tools
    register_all_builtin_tools()
    logger.info("Built-in tools registered.")

    # 8r. Initialise PluginRegistry (Sprint 12).
    from app.plugins.registry import init_plugin_registry
    _plugin_registry = await init_plugin_registry(db_conn.get_app_db())
    await _plugin_registry.start(gateway=get_router())
    logger.info("PluginRegistry started.")

    # 8s. Initialise Scheduler (Sprint 13, §20.8).
    from app.scheduler.engine import init_scheduler
    _scheduler = await init_scheduler(db_conn.get_app_db())
    await _scheduler.start()
    logger.info("Scheduler started.")

    # 8t. Auto-discover custom plugins from data/plugins/ (Sprint 13, D6).
    from app.plugins.discovery import discover_plugins, start_watcher
    for _cls in discover_plugins():
        try:
            _plugin_registry.register_class(_cls)
        except Exception as _e:  # noqa: BLE001
            logger.warning("Could not register discovered plugin %r: %s", _cls, _e)
    await start_watcher(_plugin_registry)
    logger.info("Plugin discovery watcher started.")

    # 8u. Initialise SkillStore (Sprint 14a).
    from app.agent.skills import init_skill_store
    skill_store = init_skill_store(db_conn.get_app_db())
    await skill_store.seed_builtins()
    logger.info("SkillStore initialised and built-ins seeded.")

    # 8v. Initialise SoulEditor (Sprint 14a).
    from app.agent.soul_editor import init_soul_editor
    init_soul_editor(db_conn.get_app_db())
    logger.info("SoulEditor initialised.")

    # 8w. Initialise NotificationStore (Sprint 14b D1).
    from app.notifications import init_notification_store
    _notif_store = init_notification_store(db_conn.get_app_db())
    await _notif_store.seed_default_preferences()
    logger.info("NotificationStore initialised and preferences seeded.")

    # 8x. Initialise BudgetTracker (Sprint 14b D3).
    from app.budget import init_budget_tracker
    from app.gateway.events import ET as _ET
    _budget_tracker = init_budget_tracker(db_conn.get_app_db())
    await _budget_tracker.seed_default_pricing()
    get_router().on(_ET.BUDGET_TURN_COST, _budget_tracker.handle_turn_cost)
    logger.info("BudgetTracker initialised and subscribed to BUDGET_TURN_COST.")

    # 8y. Initialise AuditSinkManager (Sprint 14b D2).
    from app.audit.sinks import init_audit_sink_manager
    _sink_mgr = init_audit_sink_manager(db_conn.get_app_db())
    await _sink_mgr.seed_default_sinks()
    await _sink_mgr.apply_retention()
    logger.info("AuditSinkManager initialised and retention applied.")

    # 8z. Initialise AppLockManager (Sprint 14b D4).
    from app.auth.app_lock import init_app_lock
    _app_lock = init_app_lock(db_conn.get_app_db())
    await _app_lock.start_idle_watcher()
    logger.info("AppLockManager initialised with idle watcher.")

    # 8z1. Initialise NotificationDispatcher (Sprint 14b D1).
    from app.notifications import init_notification_dispatcher, get_notification_dispatcher as _get_nd
    init_notification_dispatcher(db_conn.get_app_db(), get_router())
    _budget_tracker.wire_notifier(_get_nd())
    logger.info("NotificationDispatcher initialised and wired to BudgetTracker.")

    # 8z2. Initialise BackupManager (Sprint 14b D5).
    from app.backup import init_backup_manager
    init_backup_manager(db_conn.get_app_db())
    logger.info("BackupManager initialised.")

    # 9. Start background idle-detection task (§3.7).
    _idle_task = asyncio.create_task(idle_detection_task())

    # 10. Log startup summary (§15.2 D5).
    setup_complete = config_store.get("setup.complete", False)
    provider = config_store.get("setup.provider", "")
    logger.info(
        "Tequila startup complete — accepting connections",
        extra={
            "version": APP_VERSION,
            "db_path": str(db),
            "setup_complete": setup_complete,
            "provider": provider or "(none — first run)",
            "host": settings.host,
            "port": settings.port,
        },
    )

    # ── YIELD (app serves requests) ───────────────────────────────────────────
    yield

    # ── SHUTDOWN ──────────────────────────────────────────────────────────────
    logger.info("Tequila shutting down...")

    _idle_task.cancel()
    try:
        await _idle_task
    except asyncio.CancelledError:
        pass

    # Stop discovery watcher (Sprint 13).
    try:
        from app.plugins.discovery import stop_watcher as _stop_disc
        await _stop_disc()
    except Exception:  # noqa: BLE001
        pass

    # Stop AppLock idle watcher (Sprint 14b).
    try:
        from app.auth.app_lock import get_app_lock as _get_lock
        await _get_lock().stop_idle_watcher()
    except RuntimeError:
        pass

    # Stop scheduler (Sprint 13).
    try:
        from app.scheduler.engine import get_scheduler as _get_sched
        await _get_sched().stop()
    except RuntimeError:
        pass

    # Stop plugin registry (Sprint 12).
    try:
        from app.plugins.registry import get_plugin_registry as _get_pr
        await _get_pr().stop()
    except RuntimeError:
        pass

    from app.gateway.router import get_router
    try:
        get_router().stop()
    except RuntimeError:
        pass  # Router may not have started if startup failed mid-way.

    await db_conn.shutdown()
    logger.info("Tequila stopped.")


def _run_migrations(alembic_dir: Path) -> None:
    """Run ``alembic upgrade head`` synchronously at startup (§14.3)."""
    try:
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            cwd=alembic_dir.parent,
        )
        if result.returncode != 0:
            logger.error(
                "Alembic migration failed",
                extra={"stderr": result.stderr, "stdout": result.stdout},
            )
            raise RuntimeError(f"Database migration failed:\n{result.stderr}")
        logger.info("Alembic migrations applied.", extra={"output": result.stdout.strip()})
    except FileNotFoundError:
        logger.error("Alembic not found — skipping migrations (dev mode without venv?).")


# ── Exception handlers ────────────────────────────────────────────────────────


async def _tequila_exception_handler(request: Request, exc: TequilaError) -> JSONResponse:
    """Convert ``TequilaError`` subclasses to structured JSON HTTP responses."""
    return JSONResponse(
        status_code=exc.http_status,
        content={"error": exc.__class__.__name__, "message": exc.message},
    )


# ── App factory ───────────────────────────────────────────────────────────────


def create_app() -> FastAPI:
    """Create and fully-configure the FastAPI application.

    Call once at process startup (from ``main.py``).
    """
    app = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        lifespan=_lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    _default_origins = "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174"
    _cors_origins_raw = os.environ.get("TEQUILA_CORS_ORIGINS", _default_origins)
    _cors_origins: list[str] = []
    import re as _re
    for _origin in _cors_origins_raw.split(","):
        _origin = _origin.strip()
        if not _origin:
            continue
        # TD-215: Reject wildcard and non-URL origins
        if _origin == "*":
            logger.warning("CORS: rejecting wildcard origin '*' — use explicit origins")
            continue
        if not _re.match(r"^https?://", _origin):
            logger.warning("CORS: rejecting malformed origin %r", _origin)
            continue
        _cors_origins.append(_origin)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception handlers ────────────────────────────────────────────────────
    app.add_exception_handler(TequilaError, _tequila_exception_handler)  # type: ignore[arg-type]

    # ── Routers ───────────────────────────────────────────────────────────────
    from app.api.routers import system, logs, sessions, messages, setup, agents, providers
    from app.api.routers import vault, memory, entities
    from app.api.routers import knowledge_sources, graph
    from app.api.routers import skills as skills_router, tool_groups as tool_groups_router
    from app.api.routers import soul_editor as soul_editor_router
    from app.api.routers import notifications as notifications_router
    from app.api.routers import budget as budget_router
    from app.api.routers import audit as audit_router
    from app.api.routers import app_lock as app_lock_router
    from app.api.routers import backup as backup_router
    from app.api import ws
    from app.workflows import api as workflows_api
    from app.auth import api as auth_api
    from app.plugins import api as plugins_api
    from app.scheduler import api as scheduler_api
    from app.api.routers import web_policy

    app.include_router(system.router)
    app.include_router(logs.router)
    app.include_router(sessions.router)
    app.include_router(messages.router)
    app.include_router(setup.router)
    app.include_router(agents.router)
    app.include_router(providers.router)
    app.include_router(workflows_api.router)
    app.include_router(vault.router)
    app.include_router(memory.router)
    app.include_router(memory.events_router)
    app.include_router(entities.router)
    app.include_router(knowledge_sources.router)
    app.include_router(graph.router)
    app.include_router(auth_api.router)
    app.include_router(plugins_api.router)
    app.include_router(scheduler_api.router)
    app.include_router(web_policy.router)
    app.include_router(skills_router.router)
    app.include_router(tool_groups_router.router)
    app.include_router(soul_editor_router.router)
    app.include_router(notifications_router.router)
    app.include_router(budget_router.router)
    app.include_router(audit_router.router)
    app.include_router(app_lock_router.router)
    app.include_router(backup_router.router)
    app.include_router(ws.router)

    # ── Static frontend (placeholder) ─────────────────────────────────────────
    from app.paths import frontend_dir
    frontend = frontend_dir()
    if frontend.exists() and (frontend / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(frontend), html=True), name="frontend")
        logger.debug("Frontend static files mounted.", extra={"path": str(frontend)})

    return app
