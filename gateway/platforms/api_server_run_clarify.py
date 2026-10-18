"""``/v1/runs`` clarify interactions (Anthony-local, ported from the v0.21 fleet runtime).

The clarify tool asks 1-5 questions per call. A Runs client sees one ``clarify.request`` SSE event
per question (``clarify_id``, ``question``, ``choices``, ``multi_select``) and answers it with
``POST /v1/runs/{run_id}/clarify`` ``{"clarify_id", "response"}``. Pending ids are tracked per
run: conversation session ids are not authorization namespaces, so concurrent runs stay isolated.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import suppress
from typing import Any, Callable

from aiohttp import web

logger = logging.getLogger("gateway.platforms.api_server")

_MAX_CHOICES = 4
_TIMEOUT_NOTICE = "The user did not provide a response within the time limit."


def initialize(self) -> None:
    self._run_clarify_ids = {}


def forget(self, run_id: str) -> None:
    """Cancel blocked waiters for *run_id* and drop its pending ids (idempotent)."""
    with suppress(Exception):
        from tools import clarify_gateway as clarify_mod
        clarify_mod.clear_session(run_id)
    getattr(self, "_run_clarify_ids", {}).pop(run_id, None)


def _resolve_timeout() -> int:
    from tools import clarify_gateway as clarify_mod
    try:
        from gateway.run import _load_gateway_config
        return clarify_mod.resolve_clarify_timeout(_load_gateway_config())
    except Exception:
        return clarify_mod.get_clarify_timeout()


def make_clarify_callback(self, run_id: str, put_event: Callable[[dict], None]) -> Callable:
    """Agent-thread clarify callback: ``callback(questions) -> {"answers", "outcome", "notice"?}``."""
    from tools import clarify_gateway as clarify_mod

    pending = self._run_clarify_ids.setdefault(run_id, set())

    def _ask(entry: dict[str, Any]) -> tuple[Any, bool]:
        clarify_id = uuid.uuid4().hex[:16]
        question = str(entry.get("question") or "")[:4000]
        choices = [str(c)[:500] for c in (entry.get("choices") or [])][:_MAX_CHOICES]
        multi = bool(entry.get("multi_select")) and bool(choices)
        registered = clarify_mod.register(clarify_id=clarify_id, session_key=run_id, question=question,
                                          choices=choices or None, multi_select=multi)
        pending.add(clarify_id)
        self._set_run_status(run_id, "waiting_for_clarify", last_event="clarify.request",
                             clarify_id=clarify_id)
        try:
            put_event({"event": "clarify.request", "run_id": run_id, "clarify_id": clarify_id,
                       "timestamp": time.time(), "question": question, "choices": choices,
                       "multi_select": multi})
        except Exception:
            clarify_mod.resolve_gateway_clarify(clarify_id, clarify_mod.CANCELLED)
            pending.discard(clarify_id)
            return None, False
        try:
            response = clarify_mod.wait_for_response(clarify_id, _resolve_timeout())
            # A stop/retire between register and wait already popped the entry: the waiter
            # sees "unknown id" (None), but the entry itself carries the CANCELLED verdict.
            if response is None and registered.event.is_set():
                response = registered.response
        finally:
            pending.discard(clarify_id)
            if self._run_statuses.get(run_id, {}).get("status") == "waiting_for_clarify":
                self._set_run_status(run_id, "running", last_event="clarify.resolved", clarify_id=None)
        return response, response is not None

    def _callback(questions) -> dict:
        answers: dict[str, Any] = {}
        reply: dict[str, Any] = {"answers": answers, "outcome": "submitted"}
        for entry in questions or []:
            raw, answered = _ask(entry)
            if raw == clarify_mod.CANCELLED:
                reply["outcome"] = "cancelled"
                break
            if not answered:
                reply.update(outcome="timed_out", notice=_TIMEOUT_NOTICE)
                break
            answers[entry["qid"]] = None if raw in (clarify_mod.SKIPPED, "") else raw
        return reply

    return _callback


def _coerce_response(raw: Any) -> tuple[str | None, str | None]:
    if isinstance(raw, list):
        if len(raw) > _MAX_CHOICES or not all(isinstance(item, str) for item in raw):
            return None, "Clarify response list must contain at most four strings"
        return json.dumps([i.strip()[:1000] for i in raw if i.strip()], ensure_ascii=False), None
    if isinstance(raw, str):
        return raw.strip()[:8000], None
    return None, "Clarify response must be text or a list of strings"


async def handle_run_clarify(self, request: web.Request, *, _api_server) -> web.Response:
    """POST /v1/runs/{run_id}/clarify: resolve one pending clarify prompt of an owned run."""
    from gateway.platforms import api_server_runs as _runs

    _openai_error = _api_server._openai_error
    # API key only (permission=None), as in v0.21: room grants never answer clarify prompts.
    run_id, _, _, _, err = _runs._load_owned_run(
        self, request, _api_server=_api_server, permission=None, active_fallback=False)
    if err is not None:
        return err
    try:
        body = await request.json()
    except Exception:
        return web.json_response(_openai_error("Invalid JSON"), status=400)
    if not isinstance(body, dict):
        return web.json_response(_openai_error("Invalid JSON"), status=400)
    clarify_id = str(body.get("clarify_id", "")).strip()
    if not clarify_id or clarify_id not in (self._run_clarify_ids.get(run_id) or set()):
        return web.json_response(
            _openai_error("Run has no matching pending clarify prompt", code="clarify_not_pending"),
            status=409)
    value, problem = _coerce_response(body.get("response", ""))
    if problem:
        return web.json_response(_openai_error(problem), status=400)
    from tools.clarify_gateway import resolve_gateway_clarify
    if not resolve_gateway_clarify(clarify_id, value or ""):
        return web.json_response(
            _openai_error("Clarify prompt was already resolved or expired", code="clarify_not_pending"),
            status=409)
    self._set_run_status(run_id, "running", last_event="clarify.resolved", clarify_id=None)
    return web.json_response(
        {"object": "hermes.run.clarify", "run_id": run_id, "clarify_id": clarify_id, "resolved": True})
