import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from cron import scheduler


def test_pwa_tokens_are_self_scoped_and_composable(monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "_resolve_origin",
        lambda _job: {
            "platform": "telegram",
            "chat_id": "123",
            "thread_id": None,
        },
    )
    targets = scheduler._resolve_delivery_targets(
        {"id": "job-1", "deliver": "origin,pwa:self"}
    )
    assert [(item["platform"], item["chat_id"]) for item in targets] == [
        ("telegram", "123"),
        ("pwa", "self"),
    ]
    assert scheduler._resolve_delivery_targets(
        {"id": "job-1", "deliver": "pwa:self"}
    ) == [
        {
            "platform": "pwa",
            "chat_id": "self",
            "thread_id": None,
            "_resolved_from": "explicit",
        }
    ]
    assert scheduler.is_pwa_delivery_token("pwa") is True
    assert scheduler.is_pwa_delivery_token("pwa:self") is True
    assert scheduler.is_pwa_delivery_token("pwa:kelly") is False


def test_pwa_tokens_bypass_gateway_preflight(monkeypatch):
    def fail_if_gateway_config_loads():
        raise AssertionError("PWA delivery must not require gateway credentials")

    monkeypatch.setattr(
        "gateway.config.load_gateway_config",
        fail_if_gateway_config_loads,
    )

    assert scheduler._preflight_check_delivery(
        {"deliver": "origin,pwa:self"}
    ) is None
    assert scheduler._preflight_check_delivery(
        {"deliver": "pwa:self"}
    ) is None

    reason = scheduler._preflight_check_delivery(
        {"deliver": "pwa:kelly"}
    )
    assert reason is not None
    assert "not a known cron delivery target" in reason


def test_pwa_delivery_posts_acknowledged_redacted_cron_result(monkeypatch):
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            received["path"] = self.path
            received["authorization"] = self.headers.get("Authorization")
            received["payload"] = json.loads(self.rfile.read(length))
            body = json.dumps({"accepted": True, "duplicate": False}).encode()
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    key = "pwa-cron-test-key-with-more-than-32-characters"
    monkeypatch.setattr(
        scheduler,
        "load_config",
        lambda: {
            "cron": {
                "pwa_delivery": {
                    "enabled": True,
                    "url": f"http://127.0.0.1:{server.server_port}",
                }
            }
        },
    )
    monkeypatch.setattr(scheduler, "get_env_value", lambda name: key if name == "AGENT_PWA_CRON_INGEST_KEY" else "")
    try:
        error = scheduler._deliver_to_pwa(
            {
                "id": "job-123",
                "name": "Back-upcontrole",
                "_delivery_execution_id": "execution-456",
            },
            "Back-up gereed.",
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
    assert error is None
    assert received["path"] == "/api/automation/deliver"
    assert received["authorization"] == f"Bearer {key}"
    assert received["payload"] == {
        "jobId": "job-123",
        "executionId": "execution-456",
        "jobName": "Back-upcontrole",
        "content": "Back-up gereed.",
    }


def test_pwa_delivery_refuses_non_loopback_url(monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "load_config",
        lambda: {
            "cron": {
                "pwa_delivery": {
                    "enabled": True,
                    "url": "https://example.com:443",
                }
            }
        },
    )
    monkeypatch.setattr(scheduler, "get_env_value", lambda _name: "x" * 40)
    error = scheduler._deliver_to_pwa(
        {"id": "job", "name": "Job", "_delivery_execution_id": "run"},
        "melding",
    )
    assert "loopback" in error.lower()
