"""``/v1/runs`` releases the per-request agent's LLM clients (Anthony-local; port of 6d91a52fc2).

Runs builds a fresh, uncached ``AIAgent`` per request. Its memory manager is parked by
``ApiServerMemorySessions`` (upstream continuity), but its LLM clients must be released when the
run ends or they leak for the gateway's life.
"""

from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from tests.waiting import async_wait_until

AUTH = {"Authorization": "Bearer sk-secret"}


@pytest.fixture
def adapter():
    return APIServerAdapter(PlatformConfig(enabled=True, extra={"key": "sk-secret"}))


def _app(adapter):
    app = web.Application()
    app["api_server_adapter"] = adapter
    app.router.add_post("/v1/runs", adapter._handle_runs)
    return app


def _agent(result):
    agent = MagicMock()
    agent.session_id = "sess-resources"
    agent._memory_manager = None
    agent.session_prompt_tokens = 0
    agent.session_completion_tokens = 0
    agent.session_total_tokens = 0
    if isinstance(result, Exception):
        agent.run_conversation.side_effect = result
    else:
        agent.run_conversation.return_value = result
    return agent


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [{"final_response": "done"}, RuntimeError("boom")])
async def test_finished_run_releases_agent_clients_but_keeps_session(adapter, result):
    agent = _agent(result)
    async with TestClient(TestServer(_app(adapter))) as cli:
        with patch.object(adapter, "_create_agent", return_value=agent):
            resp = await cli.post("/v1/runs", json={"input": "hello"}, headers=AUTH)
            assert resp.status == 202
            run_id = (await resp.json())["run_id"]
            await async_wait_until(lambda: run_id not in adapter._active_run_tasks, timeout=5)

    agent.release_clients.assert_called_once_with()
    # Session-ending teardown would kill memory continuity and session tool state.
    agent.close.assert_not_called()
    agent.shutdown_memory_provider.assert_not_called()
