"""Privacy-projected session copies (Anthony-local; port of 93dfc7115a to v0.22.2).

E2E against a real SessionDB in a scratch state.db: the PWA imports a Telegram conversation as a
copy without ending the source and without carrying hidden context into the new surface.
"""

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from gateway.platforms.api_server_session_copy import project_conversation
from hermes_state import SessionDB

AUTH = {"Authorization": "Bearer k"}
SOURCE_ID = "telegram-source"


@pytest.fixture
def setup(tmp_path):
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={"host": "127.0.0.1", "port": 0, "key": "k"}))
    db = SessionDB(tmp_path / "state.db")
    adapter._session_db = db
    db.create_session(session_id=SOURCE_ID, source="telegram", model="test-model",
                      system_prompt="Telegram-only system prompt")
    db.set_session_title(SOURCE_ID, "Jill en Anthony")
    db.append_message(SOURCE_ID, "user", "Open /Users/macmini/prive/dossier.txt")
    db.append_message(SOURCE_ID, "assistant", "Token sk-" + "a" * 40 + " en klaar.",
                      tool_calls=[{"id": "c1", "type": "function",
                                   "function": {"name": "terminal", "arguments": "{\"cmd\": \"geheim\"}"}}],
                      reasoning="verborgen redenering")
    db.append_message(SOURCE_ID, "tool", "niet-publiek toolresultaat", tool_call_id="c1")
    db.append_message(SOURCE_ID, "assistant", "MEDIA:/tmp/geheim-rapport.pdf")
    app = web.Application()
    app["api_server_adapter"] = adapter
    app.router.add_post("/api/sessions/{session_id}/fork", adapter._handle_fork_session)
    try:
        yield adapter, db, app
    finally:
        db.close()


@pytest.mark.asyncio
async def test_conversation_copy_keeps_source_open_and_projects(setup):
    _adapter, db, app = setup
    async with TestClient(TestServer(app)) as cli:
        resp = await cli.post(f"/api/sessions/{SOURCE_ID}/fork", headers=AUTH, json={
            "id": "pwa-jill-copy", "title": "Telegram, Jill en Anthony", "preserve_source": True,
            "projection": "conversation", "copy_system_prompt": False})
        payload = await resp.json()
    assert resp.status == 201, payload
    assert payload["session"]["id"] == "pwa-jill-copy"
    source = db.get_session(SOURCE_ID)
    assert source["ended_at"] is None and source["end_reason"] is None
    copy = db.get_session("pwa-jill-copy")
    assert copy["parent_session_id"] == SOURCE_ID
    assert not copy.get("system_prompt")
    assert copy["title"] == "Telegram, Jill en Anthony"
    copied = db.get_messages("pwa-jill-copy")
    assert [m["role"] for m in copied] == ["user", "assistant"]
    blob = json.dumps(copied, ensure_ascii=False, default=str)
    for leaked in ("niet-publiek toolresultaat", "verborgen redenering", "geheim\\\"",
                   "/Users/macmini", "/tmp/geheim-rapport.pdf", "sk-" + "a" * 40,
                   "Telegram-only system prompt"):
        assert leaked not in blob, leaked
    assert not any(m.get("tool_calls") for m in copied)


@pytest.mark.asyncio
async def test_default_fork_still_branches_source(setup):
    _adapter, db, app = setup
    async with TestClient(TestServer(app)) as cli:
        resp = await cli.post(f"/api/sessions/{SOURCE_ID}/fork", headers=AUTH, json={"id": "plain-fork"})
    assert resp.status == 201
    assert db.get_session(SOURCE_ID)["end_reason"] == "branched"
    assert db.get_session("plain-fork")["system_prompt"] == "Telegram-only system prompt"
    assert len(db.get_messages("plain-fork")) == len(db.get_messages(SOURCE_ID))


@pytest.mark.asyncio
async def test_invalid_projection_is_rejected_before_any_write(setup):
    _adapter, db, app = setup
    async with TestClient(TestServer(app)) as cli:
        resp = await cli.post(f"/api/sessions/{SOURCE_ID}/fork", headers=AUTH,
                              json={"id": "x", "projection": "everything"})
    assert resp.status == 400
    assert db.get_session("x") is None
    assert db.get_session(SOURCE_ID)["ended_at"] is None


def test_projection_merges_same_role_and_keeps_alternation():
    out = project_conversation([
        {"role": "user", "content": "a"}, {"role": "user", "content": [{"type": "text", "text": "b"},
                                                                         {"type": "image_url"}]},
        {"role": "assistant", "content": ""}, {"role": "assistant", "content": "c"},
    ])
    assert [m["role"] for m in out] == ["user", "assistant"]
    assert out[0]["content"] == "a\n\nb\n[Eerdere afbeelding uit bronchat]"
