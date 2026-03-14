"""Tequila v2 — application entry point (§28.1, §15).

Run the server:

    python main.py                    # dev mode, auto-reload
    python main.py --port 9000        # custom port

Or via uvicorn directly (no reload):

    .venv\\Scripts\\python.exe -m uvicorn app.api.app:create_app --factory
"""
from __future__ import annotations

import sys


def main() -> None:
    """Parse CLI args and start the uvicorn server."""
    import argparse

    parser = argparse.ArgumentParser(description="Tequila v2 server")
    parser.add_argument("--host", default=None, help="Bind host (overrides TEQUILA_HOST)")
    parser.add_argument("--port", type=int, default=None, help="Bind port (overrides TEQUILA_PORT)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev mode)")
    args = parser.parse_args()

    # Build settings so we can fall back to env defaults.
    from app.config import get_settings

    settings = get_settings()
    host = args.host or settings.host
    port = args.port or settings.port
    reload = args.reload or settings.debug

    import uvicorn

    uvicorn.run(
        "app.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        log_config=None,  # We configure logging ourselves inside the lifespan.
    )


if __name__ == "__main__":
    main()
