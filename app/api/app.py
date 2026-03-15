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
    registry.register(AnthropicProvider())
    registry.register(OpenAIProvider())
    registry.register(OllamaProvider())
    provider_health = await registry.health_check_all()
    logger.info("ProviderRegistry ready", extra={"providers": provider_health})

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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception handlers ────────────────────────────────────────────────────
    app.add_exception_handler(TequilaError, _tequila_exception_handler)  # type: ignore[arg-type]

    # ── Routers ───────────────────────────────────────────────────────────────
    from app.api.routers import system, logs, sessions, messages, setup, agents, providers
    from app.api import ws

    app.include_router(system.router)
    app.include_router(logs.router)
    app.include_router(sessions.router)
    app.include_router(messages.router)
    app.include_router(setup.router)
    app.include_router(agents.router)
    app.include_router(providers.router)
    app.include_router(ws.router)

    # ── Static frontend (placeholder) ─────────────────────────────────────────
    from app.paths import frontend_dir
    frontend = frontend_dir()
    if frontend.exists() and (frontend / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(frontend), html=True), name="frontend")
        logger.debug("Frontend static files mounted.", extra={"path": str(frontend)})

    return app
