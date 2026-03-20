"""Sprint 14b — Unit tests for session transcript export (§13.4)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

import pytest

from app.sessions.export import ExportOptions, SessionExporter


# ── Mock factories ────────────────────────────────────────────────────────────


def _make_mock_message(role="user", content="Hello", i=0):
    msg = MagicMock()
    msg.id = f"msg-{i}"
    msg.role = role
    msg.content = content
    msg.tool_calls = None
    msg.tool_call_id = None
    msg.model = "claude-sonnet-4-6"
    msg.input_tokens = 100
    msg.output_tokens = 50
    ts = datetime(2024, 1, 15, 10, i % 60, 0, tzinfo=timezone.utc)
    msg.created_at = ts
    return msg


def _make_mock_session(title="Test Session"):
    session = MagicMock()
    session.session_id = "sess-export-001"
    session.session_key = "test-key"
    session.agent_id = "main"
    session.title = title
    session.created_at = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    return session


def _make_exporter(messages=None, session_title="Test"):
    if messages is None:
        messages = [
            _make_mock_message("user", "Hi there", 0),
            _make_mock_message("assistant", "Hello! How can I help?", 1),
        ]
    session = _make_mock_session(session_title)
    ss = MagicMock()
    ss.get = AsyncMock(return_value=session)
    ms = MagicMock()
    ms.list_by_session = AsyncMock(return_value=messages)
    return SessionExporter(ss, ms)


# ── Markdown export ───────────────────────────────────────────────────────────


async def test_export_markdown_contains_title():
    exporter = _make_exporter(session_title="My Chat")
    md = await exporter.export_markdown("sess-001", ExportOptions())
    assert "My Chat" in md


async def test_export_markdown_contains_role_headers():
    exporter = _make_exporter()
    md = await exporter.export_markdown("sess-001", ExportOptions())
    assert "User" in md
    assert "Assistant" in md


async def test_export_markdown_excludes_system_by_default():
    msgs = [
        _make_mock_message("system", "You are helpful.", 0),
        _make_mock_message("user", "Hi", 1),
    ]
    exporter = _make_exporter(messages=msgs)
    opts = ExportOptions(include_system_messages=False)
    md = await exporter.export_markdown("sess-001", opts)
    assert "You are helpful." not in md


async def test_export_markdown_includes_system_when_flag_set():
    msgs = [
        _make_mock_message("system", "You are a helpful assistant.", 0),
        _make_mock_message("user", "Hi", 1),
    ]
    exporter = _make_exporter(messages=msgs)
    opts = ExportOptions(include_system_messages=True)
    md = await exporter.export_markdown("sess-001", opts)
    assert "You are a helpful assistant." in md


async def test_export_markdown_excludes_tool_by_default():
    msgs = [
        _make_mock_message("tool", "Tool result data", 0),
        _make_mock_message("user", "What time is it?", 1),
    ]
    exporter = _make_exporter(messages=msgs)
    opts = ExportOptions(include_tool_calls=False)
    md = await exporter.export_markdown("sess-001", opts)
    assert "Tool result data" not in md


async def test_export_markdown_includes_costs_when_flag():
    exporter = _make_exporter()
    opts = ExportOptions(include_costs=True)
    md = await exporter.export_markdown("sess-001", opts)
    assert "Tokens" in md


# ── JSON export ───────────────────────────────────────────────────────────────


async def test_export_json_structure():
    exporter = _make_exporter()
    data = await exporter.export_json("sess-001", ExportOptions())
    assert "session_key" in data
    assert "messages" in data
    assert isinstance(data["messages"], list)


async def test_export_json_message_count():
    exporter = _make_exporter()
    data = await exporter.export_json("sess-001", ExportOptions())
    assert data["message_count"] == len(data["messages"])


async def test_export_json_excludes_system():
    msgs = [
        _make_mock_message("system", "System prompt", 0),
        _make_mock_message("user", "Hello", 1),
    ]
    exporter = _make_exporter(messages=msgs)
    data = await exporter.export_json("sess-001", ExportOptions(include_system_messages=False))
    roles = [m["role"] for m in data["messages"]]
    assert "system" not in roles


async def test_export_json_includes_costs_when_flag():
    exporter = _make_exporter()
    data = await exporter.export_json("sess-001", ExportOptions(include_costs=True))
    assert "model" in data["messages"][0]
    assert "input_tokens" in data["messages"][0]


async def test_export_json_omits_costs_by_default():
    exporter = _make_exporter()
    data = await exporter.export_json("sess-001", ExportOptions(include_costs=False))
    assert "model" not in data["messages"][0]


# ── PDF export ────────────────────────────────────────────────────────────────


async def test_export_pdf_returns_bytes():
    exporter = _make_exporter()
    pdf_bytes = await exporter.export_pdf("sess-001", ExportOptions())
    assert isinstance(pdf_bytes, bytes)
    # PDF magic bytes start with %PDF
    assert pdf_bytes[:4] == b"%PDF"


async def test_export_pdf_non_empty():
    exporter = _make_exporter()
    pdf_bytes = await exporter.export_pdf("sess-001", ExportOptions())
    assert len(pdf_bytes) > 100


# ── ExportOptions defaults ────────────────────────────────────────────────────


def test_export_options_defaults():
    opts = ExportOptions()
    assert not opts.include_tool_calls
    assert not opts.include_system_messages
    assert not opts.include_costs
