"""Profile-scoped PWA cron delivery (Anthony-local, ported from the v0.21 fleet runtime)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from cron import scheduler, scheduler_delivery, scheduler_preflight
from cron import scheduler_pwa_delivery as pwa


def test_pwa_tokens_are_self_scoped_and_composable(monkeypatch):
    monkeypatch.setattr(
        scheduler_delivery,
        "_resolve_origin",
        lambda _job: {"platform": "telegram", "chat_id": "123", "thread_id": None},
    )
    targets = scheduler._resolve_delivery_targets({"id": "job-1", "deliver": "origin,pwa:self"})
    assert [(t["platform"], t["chat_id"]) for t in targets] == [("telegram", "123"), ("pwa", "self")]
    assert scheduler._resolve_delivery_targets({"id": "job-1", "deliver": "pwa"}) == [
        {"platform": "pwa", "chat_id": "self", "thread_id": None, "_resolved_from": "explicit"}
    ]
    assert pwa.is_pwa_delivery_token("pwa") is True
    assert pwa.is_pwa_delivery_token("PWA:self") is True
    assert pwa.is_pwa_delivery_token("pwa:kelly") is False


def test_pwa_tokens_bypass_gateway_preflight(monkeypatch):
    def fail_if_gateway_config_loads():
        raise AssertionError("PWA delivery must not require gateway credentials")

    monkeypatch.setattr("gateway.config.load_gateway_config", fail_if_gateway_config_loads)
    assert scheduler_preflight._preflight_check_delivery({"deliver": "pwa:self"}) is None
    assert scheduler_preflight._preflight_check_delivery({"deliver": "pwa"}) is None
    reason = scheduler_preflight._preflight_check_delivery({"deliver": "pwa:kelly"})
    assert reason is not None and "not a known cron delivery target" in reason


class _Inbox:
    def __init__(self, reply=None):
        received = self.received = {}
        reply = reply if reply is not None else {"accepted": True, "duplicate": False}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                received["path"] = self.path
                received["authorization"] = self.headers.get("Authorization")
                received["payload"] = json.loads(self.rfile.read(length))
                body = json.dumps(reply).encode()
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_exc):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"


def _configure(monkeypatch, url, key="pwa-cron-test-key-with-more-than-32-characters"):
    monkeypatch.setattr(
        scheduler, "load_config", lambda: {"cron": {"pwa_delivery": {"enabled": True, "url": url}}}
    )
    monkeypatch.setattr(pwa, "get_env_value", lambda name: key if name == "AGENT_PWA_CRON_INGEST_KEY" else "")
    return key


def test_pwa_delivery_posts_acknowledged_cron_result(monkeypatch):
    with _Inbox() as inbox:
        key = _configure(monkeypatch, inbox.url)
        error = pwa.deliver_to_pwa(
            {"id": "job-123", "name": "Back-upcontrole", "execution_id": "execution-456"},
            "Back-up gereed.",
        )
    assert error is None
    assert inbox.received["path"] == "/api/automation/deliver"
    assert inbox.received["authorization"] == f"Bearer {key}"
    assert inbox.received["payload"] == {
        "jobId": "job-123",
        "executionId": "execution-456",
        "jobName": "Back-upcontrole",
        "content": "Back-up gereed.",
    }


def test_pwa_delivery_through_deliver_result(monkeypatch):
    with _Inbox() as inbox:
        _configure(monkeypatch, inbox.url)
        error = scheduler._deliver_result(
            {"id": "job-9", "name": "Schijfbewaking", "deliver": "pwa", "execution_id": "ex-9"},
            "Schijf ok.",
        )
    assert error is None
    assert inbox.received["payload"]["executionId"] == "ex-9"
    assert inbox.received["payload"]["content"] == "Schijf ok."


def test_pwa_delivery_requires_acknowledgement(monkeypatch):
    with _Inbox(reply={"accepted": False}) as inbox:
        _configure(monkeypatch, inbox.url)
        error = pwa.deliver_to_pwa({"id": "j", "execution_id": "e"}, "x")
    assert error and "acknowledge" in error


def test_pwa_delivery_refuses_non_loopback_url(monkeypatch):
    _configure(monkeypatch, "https://example.com:443")
    error = pwa.deliver_to_pwa({"id": "job", "name": "Job", "execution_id": "run"}, "melding")
    assert "loopback" in error.lower()


def test_pwa_delivery_refuses_short_key(monkeypatch):
    _configure(monkeypatch, "http://127.0.0.1:9", key="short")
    error = pwa.deliver_to_pwa({"id": "job", "execution_id": "run"}, "melding")
    assert "credential" in error.lower()


def test_pwa_delivery_disabled_by_default(monkeypatch):
    monkeypatch.setattr(scheduler, "load_config", lambda: {})
    assert "disabled" in pwa.deliver_to_pwa({"id": "job"}, "melding")
