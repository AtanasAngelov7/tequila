"""Integration tests for the WebSocket endpoint (Sprint 02, D3–D5).

Uses Starlette's synchronous TestClient which internally runs the ASGI app
in a background thread — compatible with FastAPI WebSocket testing.
"""
from __future__ import annotations

import json
import os

import pytest
from starlette.testclient import TestClient


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def ws_client(tmp_path):
    """Synchronous TestClient with full app lifespan (DB, sessions, WS)."""
    from app.db.connection import _write_locks

    os.environ["TEQUILA_DATA_DIR"] = str(tmp_path)
    _write_locks.clear()

    from app.api.app import create_app

    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client

    os.environ.pop("TEQUILA_DATA_DIR", None)
    _write_locks.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _connect(ws):
    """Send connection handshake and return the 'connected' event payload."""
    ws.send_json({"id": "c1", "method": "connect", "params": {"last_seq": 0}})
    # First response: {id, ok, payload: {connected: True}}
    resp = ws.receive_json()
    assert resp["ok"] is True
    # Second push: {event: "connected", ...}
    event = ws.receive_json()
    assert event["event"] == "connected"
    return event


# ── Connect handshake ─────────────────────────────────────────────────────────


def test_ws_connect_handshake(ws_client):
    with ws_client.websocket_connect("/api/ws") as ws:
        event = _connect(ws)
        assert "next_seq" in event["payload"]


def test_ws_connect_sets_connected(ws_client):
    with ws_client.websocket_connect("/api/ws") as ws:
        ws.send_json({"id": "c1", "method": "connect", "params": {"last_seq": 0}})
        resp = ws.receive_json()
        assert resp["ok"] is True
        assert resp["payload"]["connected"] is True


def test_ws_unknown_method_before_connect_rejected(ws_client):
    with ws_client.websocket_connect("/api/ws") as ws:
        ws.send_json({"id": "x1", "method": "session.create", "params": {}})
        resp = ws.receive_json()
        assert resp["ok"] is False
        assert "connect" in resp["error"].lower()


def test_ws_invalid_json(ws_client):
    with ws_client.websocket_connect("/api/ws") as ws:
        ws.send_text("not json!!!")
        resp = ws.receive_json()
        assert resp["ok"] is False
        assert "JSON" in resp["error"] or "json" in resp["error"].lower()


# ── session.create ────────────────────────────────────────────────────────────


def test_ws_session_create(ws_client):
    with ws_client.websocket_connect("/api/ws") as ws:
        _connect(ws)
        ws.send_json({
            "id": "s1",
            "method": "session.create",
            "params": {"title": "WS Session"},
        })
        resp = ws.receive_json()
        assert resp["id"] == "s1"
        assert resp["ok"] is True
        assert "session_id" in resp["payload"]

        # Expect push event session.created
        push = ws.receive_json()
        assert push["event"] == "session.created"
        assert push["payload"]["session_id"] == resp["payload"]["session_id"]


# ── session.resume ────────────────────────────────────────────────────────────


def test_ws_session_resume(ws_client):
    with ws_client.websocket_connect("/api/ws") as ws:
        _connect(ws)
        # Create a session first
        ws.send_json({"id": "s1", "method": "session.create", "params": {}})
        create_resp = ws.receive_json()
        ws.receive_json()  # discard session.created push
        session_key = create_resp["payload"]["session_key"]

        # Resume by key
        ws.send_json({
            "id": "r1",
            "method": "session.resume",
            "params": {"session_key": session_key},
        })
        resp = ws.receive_json()
        assert resp["id"] == "r1"
        assert resp["ok"] is True
        assert resp["payload"]["session_key"] == session_key


def test_ws_session_resume_not_found(ws_client):
    with ws_client.websocket_connect("/api/ws") as ws:
        _connect(ws)
        ws.send_json({
            "id": "r1",
            "method": "session.resume",
            "params": {"session_key": "user:no-such-key"},
        })
        resp = ws.receive_json()
        assert resp["ok"] is False
        assert "not found" in resp["error"].lower()


# ── message.send ──────────────────────────────────────────────────────────────


def test_ws_message_send(ws_client):
    with ws_client.websocket_connect("/api/ws") as ws:
        _connect(ws)
        ws.send_json({"id": "s1", "method": "session.create", "params": {}})
        ws.receive_json()  # session.create response
        ws.receive_json()  # session.created push

        ws.send_json({
            "id": "m1",
            "method": "message.send",
            "params": {"role": "user", "content": "Hello, bot!"},
        })
        resp = ws.receive_json()
        assert resp["id"] == "m1"
        assert resp["ok"] is True
        assert resp["payload"]["content"] == "Hello, bot!"
        assert resp["payload"]["role"] == "user"

        # Push event message.created
        push = ws.receive_json()
        assert push["event"] == "message.created"
        assert push["payload"]["content"] == "Hello, bot!"


def test_ws_message_send_without_session(ws_client):
    with ws_client.websocket_connect("/api/ws") as ws:
        _connect(ws)
        ws.send_json({
            "id": "m1",
            "method": "message.send",
            "params": {"role": "user", "content": "No session"},
        })
        resp = ws.receive_json()
        assert resp["ok"] is False
        assert "session" in resp["error"].lower()


# ── Reconnection replay ───────────────────────────────────────────────────────


def test_ws_reconnect_replay(ws_client):
    """Events pushed during first connection are replayed on reconnect."""
    from app.api.ws import WS_EVENT_BUFFER

    initial_seq = WS_EVENT_BUFFER.next_seq

    # First connection — push one message
    with ws_client.websocket_connect("/api/ws") as ws:
        _connect(ws)
        ws.send_json({"id": "s1", "method": "session.create", "params": {}})
        ws.receive_json()  # response
        ws.receive_json()  # session.created push (seq=N)

        ws.send_json({"id": "m1", "method": "message.send", "params": {"role": "user", "content": "Replay msg"}})
        ws.receive_json()  # message.send response
        push = ws.receive_json()  # message.created push
        seq_after_msg = push["seq"]

    # Second connection — replay from before the message
    with ws_client.websocket_connect("/api/ws") as ws:
        ws.send_json({"id": "c2", "method": "connect", "params": {"last_seq": initial_seq}})
        # Drain frames: may get replayed events + response + connected event
        frames = []
        for _ in range(10):
            try:
                frames.append(ws.receive_json())
            except Exception:
                break
        events_received = [f for f in frames if "event" in f]
        assert any(
            f.get("payload", {}).get("content") == "Replay msg"
            for f in events_received
        ), f"Expected replayed message in frames, got: {frames}"


# ── Unknown method ────────────────────────────────────────────────────────────


def test_ws_unknown_method(ws_client):
    with ws_client.websocket_connect("/api/ws") as ws:
        _connect(ws)
        ws.send_json({"id": "u1", "method": "bogus.method", "params": {}})
        resp = ws.receive_json()
        assert resp["ok"] is False
        assert "Unknown method" in resp["error"]
