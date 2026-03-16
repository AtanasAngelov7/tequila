"""TD-S1 Security Hardening — New tests for TD-43, TD-44, TD-45, TD-46, TD-55,
TD-56, TD-66, TD-91, TD-108.
"""
from __future__ import annotations

import asyncio
import json

import pytest


# ── TD-56: backend field validated as Literal ─────────────────────────────────


def test_register_request_rejects_invalid_backend():
    """RegisterSourceRequest rejects backend values not in the allowed Literal."""
    from pydantic import ValidationError
    from app.api.routers.knowledge_sources import RegisterSourceRequest

    with pytest.raises(ValidationError):
        RegisterSourceRequest(name="x", backend="elasticsearch")


def test_register_request_accepts_valid_backends():
    """RegisterSourceRequest accepts all four valid backends."""
    from app.api.routers.knowledge_sources import RegisterSourceRequest

    for backend in ("chroma", "pgvector", "faiss", "http"):
        req = RegisterSourceRequest(name="x", backend=backend, connection={})
        assert req.backend == backend


# ── TD-55: per-backend connection config schemas ──────────────────────────────


def test_pgvector_connection_rejects_sql_injection_table():
    """PgVectorConnectionConfig rejects table names containing SQL metacharacters."""
    from pydantic import ValidationError
    from app.api.routers.knowledge_sources import PgVectorConnectionConfig

    with pytest.raises(ValidationError):
        PgVectorConnectionConfig(table="documents; DROP TABLE users--")


def test_pgvector_connection_accepts_valid_identifier():
    """PgVectorConnectionConfig accepts a valid table name."""
    from app.api.routers.knowledge_sources import PgVectorConnectionConfig

    cfg = PgVectorConnectionConfig(table="my_documents")
    assert cfg.table == "my_documents"


def test_http_connection_accepts_valid_url():
    """HttpConnectionConfig accepts a standard https URL."""
    from app.api.routers.knowledge_sources import HttpConnectionConfig

    cfg = HttpConnectionConfig(url="https://api.example.com/search")
    assert str(cfg.url).startswith("https://")


def test_validate_connection_pgvector_invalid_table():
    """_validate_connection raises ValueError for invalid pgvector table name."""
    from app.api.routers.knowledge_sources import _validate_connection

    with pytest.raises(ValueError, match="connection config"):
        _validate_connection("pgvector", {"table": "bad table name!"})


def test_validate_connection_unknown_backend_permissive():
    """_validate_connection allows unknown backends (no model to validate against)."""
    from app.api.routers.knowledge_sources import _validate_connection

    # Should not raise for unknown backend
    _validate_connection("custom_backend", {"url": "http://example.com"})


# ── TD-43: SQL identifier validation in pgvector adapter ─────────────────────


def test_pgvector_validate_ident_rejects_sql_injection():
    """_validate_ident raises ValueError for dangerous SQL identifiers."""
    from app.knowledge.sources.adapters.pgvector import _validate_ident

    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        _validate_ident("documents; DROP TABLE users--", "table")


def test_pgvector_validate_ident_rejects_spaces():
    """_validate_ident raises ValueError for identifiers with spaces."""
    from app.knowledge.sources.adapters.pgvector import _validate_ident

    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        _validate_ident("my table", "table")


def test_pgvector_validate_ident_accepts_valid():
    """_validate_ident accepts valid SQL identifiers."""
    from app.knowledge.sources.adapters.pgvector import _validate_ident

    assert _validate_ident("my_documents", "table") == "my_documents"
    assert _validate_ident("col_1", "column") == "col_1"
    assert _validate_ident("_private", "column") == "_private"


def test_pgvector_validate_ident_rejects_digit_start():
    """_validate_ident rejects identifiers that start with a digit."""
    from app.knowledge.sources.adapters.pgvector import _validate_ident

    with pytest.raises(ValueError):
        _validate_ident("1bad", "table")


# ── TD-44: SSRF protection in HTTP adapter ────────────────────────────────────


@pytest.mark.asyncio
async def test_http_adapter_rejects_private_ip(monkeypatch):
    """HTTPAdapter._validate_url rejects URLs resolving to private IPs."""
    import socket
    from app.knowledge.sources.adapters.http import _validate_url

    # Patch gethostbyname to simulate a private IP response
    monkeypatch.setattr(socket, "gethostbyname", lambda _h: "192.168.1.1")

    with pytest.raises(ValueError, match="blocked network"):
        await _validate_url("http://internal.corp/api")


@pytest.mark.asyncio
async def test_http_adapter_rejects_loopback(monkeypatch):
    """HTTPAdapter._validate_url rejects loopback addresses."""
    import socket
    from app.knowledge.sources.adapters.http import _validate_url

    monkeypatch.setattr(socket, "gethostbyname", lambda _h: "127.0.0.1")

    with pytest.raises(ValueError, match="blocked network"):
        await _validate_url("http://localhost/api")


@pytest.mark.asyncio
async def test_http_adapter_rejects_bad_scheme(monkeypatch):
    """HTTPAdapter._validate_url rejects non-http/https schemes."""
    from app.knowledge.sources.adapters.http import _validate_url

    with pytest.raises(ValueError, match="scheme"):
        await _validate_url("ftp://example.com/data")


@pytest.mark.asyncio
async def test_http_adapter_search_returns_empty_for_private_ip(monkeypatch):
    """HTTPAdapter.search returns [] (not an exception) when SSRF check fails."""
    import socket
    from app.knowledge.sources.adapters.http import HTTPAdapter
    from app.knowledge.sources.models import KnowledgeSource, QueryMode

    monkeypatch.setattr(socket, "gethostbyname", lambda _h: "10.0.0.1")

    src = KnowledgeSource(
        source_id="ks-ssrf", name="SSRF Test", backend="http", query_mode=QueryMode.text,
        connection={"url": "http://internal.local/search"},
    )
    adapter = HTTPAdapter(src)
    chunks = await adapter.search("test query")
    assert chunks == []


# ── TD-45: Path traversal protection in FAISS adapter ────────────────────────


def test_faiss_validate_path_rejects_traversal():
    """_validate_path raises ValueError for paths outside the data directory."""
    from app.knowledge.sources.adapters.faiss import _validate_path

    with pytest.raises(ValueError, match="outside the allowed"):
        _validate_path("../../etc/passwd", "index_path")


def test_faiss_validate_path_rejects_absolute_system_path():
    """_validate_path raises ValueError for absolute paths outside data/."""
    import sys
    from app.knowledge.sources.adapters.faiss import _validate_path

    system_path = "C:\\Windows\\System32\\drivers\\etc\\hosts" if sys.platform == "win32" else "/etc/passwd"
    with pytest.raises(ValueError, match="outside the allowed"):
        _validate_path(system_path, "index_path")


def test_faiss_validate_path_accepts_data_subpath():
    """_validate_path accepts paths inside the data/ directory."""
    from app.knowledge.sources.adapters.faiss import _validate_path, _DATA_DIR
    import tempfile
    import os

    # Create a real temp file inside the data dir to test with
    data_dir = _DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)

    # Construct a valid sub-path (don't need the file to exist for path check)
    valid_path = str(data_dir / "faiss" / "my_index.faiss")
    result = _validate_path(valid_path, "index_path")
    assert result.is_relative_to(data_dir)


# ── TD-66: Session tool policy checks ────────────────────────────────────────


@pytest.fixture
async def policy_stores(migrated_db):
    """Initialise stores for policy tests."""
    from app.sessions.store import init_session_store
    from app.sessions.messages import init_message_store

    init_session_store(migrated_db)
    init_message_store(migrated_db)
    return migrated_db


@pytest.mark.asyncio
async def test_sessions_send_denied_when_policy_blocks(policy_stores):
    """sessions_send returns error JSON when calling session forbids inter-session ops."""
    from app.sessions.store import get_session_store
    from app.tools.builtin.sessions import sessions_send

    ss = get_session_store()
    # Create a session with can_send_inter_session=False
    await ss.create(
        session_key="agent:restricted:sub:abc",
        kind="agent",
        agent_id="restricted_bot",
        policy={"can_send_inter_session": False},
    )

    result = json.loads(await sessions_send(
        session_key="user:other",
        message="hello",
        calling_session_key="agent:restricted:sub:abc",
    ))
    assert "error" in result
    assert "denied" in result["error"].lower()


@pytest.mark.asyncio
async def test_sessions_list_denied_when_policy_blocks(policy_stores):
    """sessions_list returns error JSON when calling session forbids inter-session ops."""
    from app.sessions.store import get_session_store
    from app.tools.builtin.sessions import sessions_list

    ss = get_session_store()
    await ss.create(
        session_key="agent:locked:sub:xyz",
        kind="agent",
        agent_id="locked_bot",
        policy={"can_send_inter_session": False},
    )

    result = json.loads(await sessions_list(calling_session_key="agent:locked:sub:xyz"))
    assert "error" in result


@pytest.mark.asyncio
async def test_sessions_list_allowed_without_calling_key(policy_stores):
    """sessions_list still works when no calling_session_key is provided (backward compat)."""
    from app.tools.builtin.sessions import sessions_list

    result = json.loads(await sessions_list())
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_sessions_history_denied_when_policy_blocks(policy_stores):
    """sessions_history returns error JSON when calling session forbids inter-session ops."""
    from app.sessions.store import get_session_store
    from app.tools.builtin.sessions import sessions_history

    ss = get_session_store()
    await ss.create(
        session_key="agent:hist_locked:sub:abc",
        kind="agent",
        agent_id="hist_locked_bot",
        policy={"can_send_inter_session": False},
    )

    result = json.loads(await sessions_history(
        session_key="user:target",
        calling_session_key="agent:hist_locked:sub:abc",
    ))
    assert "error" in result


# ── TD-108: Concurrency guard on graph rebuild ────────────────────────────────


@pytest.mark.asyncio
async def test_graph_rebuild_lock_variable_exists():
    """_rebuild_lock is defined as an asyncio.Lock on the graph router module."""
    from app.api.routers.graph import _rebuild_lock

    assert isinstance(_rebuild_lock, asyncio.Lock)


@pytest.mark.asyncio
async def test_graph_rebuild_returns_429_when_lock_held():
    """rebuild_graph raises HTTP 429 when a rebuild is already in progress."""
    from fastapi import HTTPException
    from app.api.routers import graph as graph_module
    from app.api.routers.graph import rebuild_graph

    # Acquire the lock to simulate an in-progress rebuild
    async with graph_module._rebuild_lock:
        with pytest.raises(HTTPException) as exc_info:
            await rebuild_graph(threshold=0.82)
        assert exc_info.value.status_code == 429
        assert "in progress" in exc_info.value.detail.lower()
