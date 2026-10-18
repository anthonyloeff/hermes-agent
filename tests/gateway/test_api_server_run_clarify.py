"""``/v1/runs`` clarify interactions (Anthony-local; port of 6eb2880555 to v0.22.2)."""

import json
import threading
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from tests.waiting import async_wait_until
from tools import clarify_gateway as clarify_mod
from toolsets import TOOLSETS

AUTH = {"Authorization": "Bearer sk-secret"}


def test_api_server_toolset_exposes_runs_clarify():
    assert "clarify" in TOOLSETS["hermes-api-server"]["tools"]


@pytest.fixture
def adapter():
    return APIServerAdapter(PlatformConfig(enabled=True, extra={"key": "sk-secret"}))


def _app(adapter):
    app = web.Application()
    app["api_server_adapter"] = adapter
    app.router.add_post("/v1/runs", adapter._handle_runs)
    app.router.add_get("/v1/runs/{run_id}", adapter._handle_get_run)
    app.router.add_post("/v1/runs/{run_id}/clarify", adapter._handle_run_clarify)
    return app


def test_runs_routes_include_clarify(adapter):
    from gateway.platforms import api_server_runs
    paths = {(m, p) for m, p, _ in api_server_runs._http_routes(adapter)}
    assert ("POST", "/v1/runs/{run_id}/clarify") in paths


def _clarify_events(adapter, run_id):
    stream = adapter._run_streams.get(run_id)
    if stream is None:
        return []
    return [e for _, e in stream.backlog if e and e.get("event") == "clarify.request"]


def _mock_agent(run_fn):
    agent = MagicMock()
    agent.session_prompt_tokens = agent.session_completion_tokens = agent.session_total_tokens = 0
    agent.run_conversation.side_effect = lambda **kw: run_fn(agent, **kw)
    return agent


async def _status(cli, run_id):
    return await (await cli.get(f"/v1/runs/{run_id}", headers=AUTH)).json()


@pytest.mark.asyncio
async def test_two_question_clarify_resumes_same_run(adapter):
    result = {}

    def run(agent, **_kw):
        reply = agent.clarify_callback([
            {"qid": "q0", "question": "Welke route?", "choices": ["Veilig (Recommended)", "Snel"],
             "multi_select": False},
            {"qid": "q1", "question": "Welke dagen?", "choices": ["ma", "di", "wo"], "multi_select": True},
        ])
        result["reply"] = reply
        return {"final_response": json.dumps(reply["answers"])}

    async with TestClient(TestServer(_app(adapter))) as cli:
        with patch.object(adapter, "_create_agent", return_value=_mock_agent(run)):
            started = await cli.post("/v1/runs", json={"input": "kies", "session_id": "s-clarify"},
                                     headers=AUTH)
            assert started.status == 202
            run_id = (await started.json())["run_id"]

            events = await async_wait_until(lambda: _clarify_events(adapter, run_id), what="q0")
            first = events[0]
            assert first["question"] == "Welke route?"
            assert first["choices"] == ["Veilig (Recommended)", "Snel"]
            assert first["multi_select"] is False
            assert (await _status(cli, run_id))["status"] == "waiting_for_clarify"

            # A wrong id is refused and leaves the prompt pending.
            bad = await cli.post(f"/v1/runs/{run_id}/clarify",
                                 json={"clarify_id": "nope", "response": "x"}, headers=AUTH)
            assert bad.status == 409

            ok = await cli.post(f"/v1/runs/{run_id}/clarify",
                                json={"clarify_id": first["clarify_id"], "response": "Veilig"}, headers=AUTH)
            assert ok.status == 200 and (await ok.json())["resolved"] is True

            events = await async_wait_until(
                lambda: (lambda e: e if len(e) >= 2 else None)(_clarify_events(adapter, run_id)), what="q1")
            second = events[1]
            assert second["multi_select"] is True
            ok = await cli.post(f"/v1/runs/{run_id}/clarify",
                                json={"clarify_id": second["clarify_id"], "response": ["ma", "wo"]},
                                headers=AUTH)
            assert ok.status == 200

            await async_wait_until(
                lambda: adapter._run_statuses.get(run_id, {}).get("status") == "completed", what="completed")
            assert (await _status(cli, run_id))["status"] == "completed"

    assert result["reply"]["outcome"] == "submitted"
    assert result["reply"]["answers"]["q0"] == "Veilig"
    assert json.loads(result["reply"]["answers"]["q1"]) == ["ma", "wo"]
    assert run_id not in adapter._run_clarify_ids
    assert clarify_mod.has_pending(run_id) is False


@pytest.mark.asyncio
async def test_clarify_is_isolated_per_run(adapter):
    """A clarify id from run A cannot be answered through run B."""
    gate = threading.Event()

    def run(agent, **_kw):
        reply = agent.clarify_callback([{"qid": "q0", "question": "?", "choices": None,
                                         "multi_select": False}])
        gate.set()
        return {"final_response": str(reply["outcome"])}

    async with TestClient(TestServer(_app(adapter))) as cli:
        with patch.object(adapter, "_create_agent", side_effect=lambda **kw: _mock_agent(run)):
            a = (await (await cli.post("/v1/runs", json={"input": "a"}, headers=AUTH)).json())["run_id"]
            b = (await (await cli.post("/v1/runs", json={"input": "b"}, headers=AUTH)).json())["run_id"]
            ev_a = (await async_wait_until(lambda: _clarify_events(adapter, a), what="a"))[0]
            ev_b = (await async_wait_until(lambda: _clarify_events(adapter, b), what="b"))[0]
            cross = await cli.post(f"/v1/runs/{b}/clarify",
                                   json={"clarify_id": ev_a["clarify_id"], "response": "x"}, headers=AUTH)
            assert cross.status == 409
            for run_id, ev in ((a, ev_a), (b, ev_b)):
                r = await cli.post(f"/v1/runs/{run_id}/clarify",
                                   json={"clarify_id": ev["clarify_id"], "response": "ok"}, headers=AUTH)
                assert r.status == 200


@pytest.mark.asyncio
async def test_clarify_requires_api_key(adapter):
    async with TestClient(TestServer(_app(adapter))) as cli:
        r = await cli.post("/v1/runs/whatever/clarify", json={"clarify_id": "x", "response": "y"})
        assert r.status == 401


def test_retire_cancels_blocked_waiter(adapter):
    from gateway.platforms import api_server_run_clarify as rc
    from gateway.platforms import api_server_runs

    run_id = "run-retire"
    adapter._run_statuses[run_id] = {"status": "running"}
    callback = rc.make_clarify_callback(adapter, run_id, lambda _event: None)
    out = {}
    t = threading.Thread(target=lambda: out.update(
        reply=callback([{"qid": "q0", "question": "?", "choices": None, "multi_select": False}])))
    t.start()
    from tests.waiting import wait_until
    wait_until(lambda: adapter._run_clarify_ids.get(run_id), what="pending registered")
    api_server_runs._retire_live_run(adapter, run_id)
    t.join(timeout=5)
    assert not t.is_alive()
    assert out["reply"]["outcome"] == "cancelled"
