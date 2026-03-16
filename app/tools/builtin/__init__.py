"""Built-in tool implementations for Sprint 06 (§16, §17).

Importing this package's submodules triggers their module-level ``@tool``
decorator calls, registering all built-in tools into the global registry.

Call ``register_all_builtin_tools()`` once at application startup to ensure
all tools are available before the first request.
"""
from __future__ import annotations


def register_all_builtin_tools() -> None:
    """Import all built-in tool modules, triggering their @tool registrations.

    Safe to call multiple times (idempotent — overwriting is logged but harmless).
    """
    from app.tools.builtin import filesystem  # noqa: F401
    from app.tools.builtin import code_exec  # noqa: F401
    from app.tools.builtin import web_search  # noqa: F401
    from app.tools.builtin import web_fetch  # noqa: F401
    from app.tools.builtin import vision  # noqa: F401
    from app.tools.builtin import sessions  # noqa: F401  # Sprint 08
    from app.tools.builtin import knowledge  # noqa: F401  # Sprint 10
