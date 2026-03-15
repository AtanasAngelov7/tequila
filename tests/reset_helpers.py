"""Test-only helpers for resetting singleton / registry state between tests.

These functions are intentionally kept *outside* the production source tree so
that production modules do not ship test-only code.  Import from this module in
conftest fixtures or test set-up functions.
"""
from __future__ import annotations


def reset_tool_executor() -> None:
    """Reset the ToolExecutor singleton so tests start with a clean instance."""
    import app.tools.executor as _mod

    _mod._executor = None


def reset_circuit_registry() -> None:
    """Clear the circuit-breaker registry so tests start with no open circuits."""
    import app.providers.circuit_breaker as _mod

    _mod._circuit_registry.clear()
