"""Integration test fixtures for Sprint 08 (§3.3, §20.7)."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def reset_sub_agent_active():
    """Clear the in-memory sub-agent concurrency tracker between tests.

    Workflow e2e tests and multi-agent tests both trigger ``spawn_sub_agent``
    which registers sessions in the module-level ``_active`` dict.  Without
    this cleanup the concurrency limit can be hit by a later test.
    """
    from app.agent import sub_agent

    sub_agent._active.clear()
    yield
    sub_agent._active.clear()
