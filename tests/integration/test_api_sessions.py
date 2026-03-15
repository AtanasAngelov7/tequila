"""Integration tests for the Sessions REST API (Sprint 02, D1)."""
from __future__ import annotations

import pytest


# ── Create ────────────────────────────────────────────────────────────────────


async def test_create_session(test_app):
    resp = await test_app.post("/api/sessions", json={"title": "My Session"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "My Session"
    assert data["status"] == "active"
    assert "session_id" in data
    assert "session_key" in data


async def test_create_session_minimal(test_app):
    resp = await test_app.post("/api/sessions", json={})
    assert resp.status_code == 201
    assert resp.json()["kind"] == "user"


async def test_create_session_custom_kind(test_app):
    resp = await test_app.post(
        "/api/sessions",
        json={"kind": "agent", "session_key": "agent:int-test", "agent_id": "int-agent"},
    )
    assert resp.status_code == 201
    assert resp.json()["kind"] == "agent"


# ── List ──────────────────────────────────────────────────────────────────────


async def test_list_sessions_empty(test_app):
    resp = await test_app.get("/api/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert "sessions" in body
    assert isinstance(body["sessions"], list)
    assert "total" in body


async def test_list_sessions_populated(test_app):
    await test_app.post("/api/sessions", json={"title": "S-A", "session_key": "user:la"})
    await test_app.post("/api/sessions", json={"title": "S-B", "session_key": "user:lb"})
    resp = await test_app.get("/api/sessions")
    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    titles = [s["title"] for s in sessions]
    assert "S-A" in titles
    assert "S-B" in titles


async def test_list_sessions_filter_status(test_app):
    cr = await test_app.post("/api/sessions", json={"session_key": "user:filt-arch"})
    sid = cr.json()["session_id"]
    await test_app.post(f"/api/sessions/{sid}/archive")
    resp = await test_app.get("/api/sessions?status=archived")
    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    assert any(s["session_id"] == sid for s in sessions)


async def test_list_sessions_pagination(test_app):
    for i in range(4):
        await test_app.post("/api/sessions", json={"session_key": f"user:page{i}"})
    page1 = (await test_app.get("/api/sessions?limit=2&offset=0")).json()["sessions"]
    page2 = (await test_app.get("/api/sessions?limit=2&offset=2")).json()["sessions"]
    ids1 = {s["session_id"] for s in page1}
    ids2 = {s["session_id"] for s in page2}
    assert len(page1) == 2
    assert ids1.isdisjoint(ids2)


# ── Get ───────────────────────────────────────────────────────────────────────


async def test_get_session(test_app):
    cr = await test_app.post("/api/sessions", json={"title": "Gettable"})
    sid = cr.json()["session_id"]
    resp = await test_app.get(f"/api/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Gettable"


async def test_get_session_not_found(test_app):
    resp = await test_app.get("/api/sessions/no-such-id")
    assert resp.status_code == 404


# ── Update ────────────────────────────────────────────────────────────────────


async def test_update_session_title(test_app):
    cr = await test_app.post("/api/sessions", json={"title": "Before"})
    sid = cr.json()["session_id"]
    resp = await test_app.patch(f"/api/sessions/{sid}", json={"title": "After"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "After"


async def test_update_session_metadata(test_app):
    cr = await test_app.post("/api/sessions", json={})
    sid = cr.json()["session_id"]
    resp = await test_app.patch(f"/api/sessions/{sid}", json={"metadata": {"k": "v"}})
    assert resp.status_code == 200
    assert resp.json()["metadata"] == {"k": "v"}


async def test_update_session_not_found(test_app):
    resp = await test_app.patch("/api/sessions/no-such-id", json={"title": "X"})
    assert resp.status_code == 404


# ── Archive / Unarchive ───────────────────────────────────────────────────────


async def test_archive_session(test_app):
    cr = await test_app.post("/api/sessions", json={"session_key": "user:arch"})
    sid = cr.json()["session_id"]
    resp = await test_app.post(f"/api/sessions/{sid}/archive")
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"


async def test_unarchive_session(test_app):
    cr = await test_app.post("/api/sessions", json={"session_key": "user:unarch"})
    sid = cr.json()["session_id"]
    await test_app.post(f"/api/sessions/{sid}/archive")
    resp = await test_app.post(f"/api/sessions/{sid}/unarchive")
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


async def test_archive_not_found(test_app):
    resp = await test_app.post("/api/sessions/bad-id/archive")
    assert resp.status_code == 404


# ── Delete ────────────────────────────────────────────────────────────────────


async def test_delete_session(test_app):
    cr = await test_app.post("/api/sessions", json={"session_key": "user:del-int"})
    sid = cr.json()["session_id"]
    resp = await test_app.delete(f"/api/sessions/{sid}")
    assert resp.status_code == 204
    get_resp = await test_app.get(f"/api/sessions/{sid}")
    assert get_resp.status_code == 404


async def test_delete_not_found(test_app):
    resp = await test_app.delete("/api/sessions/no-such-id")
    assert resp.status_code == 404


# ── Messages sub-resource ─────────────────────────────────────────────────────


async def test_create_and_list_messages(test_app):
    cr = await test_app.post("/api/sessions", json={"session_key": "user:msg-test"})
    sid = cr.json()["session_id"]

    post_resp = await test_app.post(
        f"/api/sessions/{sid}/messages",
        json={"role": "user", "content": "Hello world"},
    )
    assert post_resp.status_code == 201
    msg = post_resp.json()
    assert msg["content"] == "Hello world"
    assert msg["role"] == "user"
    assert msg["session_id"] == sid

    list_resp = await test_app.get(f"/api/sessions/{sid}/messages")
    assert list_resp.status_code == 200
    messages = list_resp.json()["messages"]
    assert len(messages) >= 1
    assert messages[0]["content"] == "Hello world"


async def test_message_increments_count(test_app):
    cr = await test_app.post("/api/sessions", json={"session_key": "user:count-test"})
    sid = cr.json()["session_id"]
    await test_app.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "Msg 1"})
    await test_app.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "Msg 2"})
    resp = await test_app.get(f"/api/sessions/{sid}")
    assert resp.json()["message_count"] == 2


async def test_messages_for_missing_session(test_app):
    resp = await test_app.get("/api/sessions/no-such-id/messages")
    assert resp.status_code == 404


# ── Search (Sprint 03, D4) ────────────────────────────────────────────────────


async def test_search_by_title(test_app):
    await test_app.post("/api/sessions", json={"title": "Budget Planning 2025"})
    await test_app.post("/api/sessions", json={"title": "Marketing Roadmap"})
    resp = await test_app.get("/api/sessions?q=budget&status=all")
    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    assert all("budget" in s["title"].lower() for s in sessions)
    assert len(sessions) >= 1


async def test_search_no_match(test_app):
    await test_app.post("/api/sessions", json={"title": "Alpha Session"})
    resp = await test_app.get("/api/sessions?q=zzznomatch&status=all")
    assert resp.status_code == 200
    assert resp.json()["sessions"] == []


async def test_search_empty_q_returns_all(test_app):
    await test_app.post("/api/sessions", json={"title": "S1"})
    await test_app.post("/api/sessions", json={"title": "S2"})
    resp = await test_app.get("/api/sessions?q=&status=all")
    assert resp.status_code == 200
    assert len(resp.json()["sessions"]) >= 2


async def test_search_is_case_insensitive(test_app):
    await test_app.post("/api/sessions", json={"title": "My Important Topic"})
    resp = await test_app.get("/api/sessions?q=important&status=all")
    assert resp.status_code == 200
    titles = [s["title"] for s in resp.json()["sessions"]]
    assert any("important" in t.lower() for t in titles)


# ── Sort (Sprint 03, D4) ──────────────────────────────────────────────────────


async def test_sort_by_title_asc(test_app):
    await test_app.post("/api/sessions", json={"title": "Zebra Session"})
    await test_app.post("/api/sessions", json={"title": "Apple Session"})
    await test_app.post("/api/sessions", json={"title": "Mango Session"})
    resp = await test_app.get("/api/sessions?sort=title&order=asc&status=all")
    assert resp.status_code == 200
    titles = [s["title"] for s in resp.json()["sessions"]]
    assert titles == sorted(titles, key=str.lower)


async def test_sort_by_title_desc(test_app):
    await test_app.post("/api/sessions", json={"title": "Ace First"})
    await test_app.post("/api/sessions", json={"title": "Zulu Last"})
    resp = await test_app.get("/api/sessions?sort=title&order=desc&status=all")
    assert resp.status_code == 200
    titles = [s["title"] for s in resp.json()["sessions"]]
    assert titles == sorted(titles, key=str.lower, reverse=True)


async def test_sort_by_message_count_desc(test_app):
    cr1 = await test_app.post("/api/sessions", json={"title": "Few Messages"})
    cr2 = await test_app.post("/api/sessions", json={"title": "Many Messages"})
    sid1 = cr1.json()["session_id"]
    sid2 = cr2.json()["session_id"]
    # sid1 gets 1 message, sid2 gets 3
    await test_app.post(f"/api/sessions/{sid1}/messages", json={"role": "user", "content": "one"})
    for i in range(3):
        await test_app.post(f"/api/sessions/{sid2}/messages", json={"role": "user", "content": f"msg {i}"})
    resp = await test_app.get("/api/sessions?sort=message_count&order=desc&status=all")
    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    counts = [s["message_count"] for s in sessions]
    assert counts == sorted(counts, reverse=True)


async def test_sort_invalid_falls_back(test_app):
    """Invalid sort param should still return 200 (safe whitelist handles it)."""
    resp = await test_app.get("/api/sessions?sort=DROP_TABLE&order=asc&status=all")
    assert resp.status_code == 200


# ── Default title (Sprint 03, D3) ─────────────────────────────────────────────


async def test_create_session_no_title_defaults(test_app):
    """Creating a session without title should auto-assign 'New Session'."""
    resp = await test_app.post("/api/sessions", json={})
    assert resp.status_code == 201
    assert resp.json()["title"] == "New Session"


async def test_create_session_channel_title(test_app):
    """Channel kind gets a default title including the sender."""
    resp = await test_app.post(
        "/api/sessions",
        json={"kind": "channel", "metadata": {"sender": "alice"}, "agent_id": "agent:test"},
    )
    assert resp.status_code == 201
    title = resp.json()["title"]
    # Title is "{channel.capitalize()}: {sender}" — channel defaults to "webchat"
    assert "alice" in title
    assert title.endswith(": alice")


async def test_create_session_agent_title(test_app):
    """Agent kind gets a default title with the agent_id."""
    resp = await test_app.post(
        "/api/sessions",
        json={"kind": "agent", "agent_id": "agent:helper"},
    )
    assert resp.status_code == 201
    assert "agent:helper" in resp.json()["title"].lower()
