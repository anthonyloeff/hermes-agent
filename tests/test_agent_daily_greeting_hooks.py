"""Daily-greeting hooks on v0.22 delivery paths (Anthony-local; port of 6ba2a5b9bf).

E2E against a temp HERMES_HOME: the real config loader must surface ``daily_greeting``, chat finals
and cron deliveries share one once-per-day state, and the gateway hook never raises nor consumes
the delivery-adapter routing lookup that ``send_final_ledgered`` owns.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import agent_daily_greeting as greeting
from gateway.platforms import base


def _write_config(home, enabled=True):
    (home / "config.yaml").write_text(
        "daily_greeting:\n"
        f"  enabled: {'true' if enabled else 'false'}\n"
        "  recipient_name: Anthony\n"
        "  timezone: Europe/Amsterdam\n"
        "  scope: profile\n", encoding="utf-8")


def _home(monkeypatch, tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


def _source(chat_id="123", platform=SimpleNamespace(value="Telegram")):
    return SimpleNamespace(chat_id=chat_id, thread_id=None, platform=platform)


def test_real_config_loader_surfaces_daily_greeting(monkeypatch, tmp_path):
    _write_config(_home(monkeypatch, tmp_path))
    from hermes_cli.config import load_config_readonly
    assert load_config_readonly()["daily_greeting"]["enabled"] is True


def test_gateway_final_greets_once_then_cron_does_not_repeat(monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path)
    _write_config(home)
    first = base._daily_greeting_final(_source(), "Status: gereed")
    assert first.endswith("\n\nStatus: gereed")
    assert greeting._GREETING_RE.match(first)
    assert base._daily_greeting_final(_source(), "Tweede") == "Tweede"

    from hermes_cli.config import load_config_readonly
    assert greeting.greet_cron_delivery("pwa", "x", None, "Cron", load_config_readonly()) == "Cron"
    assert (home / "state" / "daily_greeting_state.json").exists()


def test_cron_delivery_greets_first_contact(monkeypatch, tmp_path):
    _write_config(_home(monkeypatch, tmp_path))
    from hermes_cli.config import load_config_readonly
    out = greeting.greet_cron_delivery("telegram", "1", "4", "Briefing", load_config_readonly())
    assert greeting._GREETING_RE.match(out) and out.endswith("Briefing")


def test_disabled_or_missing_config_is_passthrough(monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path)
    assert base._daily_greeting_final(_source(platform="telegram"), "Tekst") == "Tekst"
    _write_config(home, enabled=False)
    assert base._daily_greeting_final(_source(platform="telegram"), "Tekst") == "Tekst"
    assert greeting.greet_cron_delivery("telegram", "1", None, "Tekst", None) == "Tekst"


def test_gateway_hook_never_raises(monkeypatch, tmp_path):
    _write_config(_home(monkeypatch, tmp_path))
    def boom(*a, **k):
        raise RuntimeError("state disk full")
    monkeypatch.setattr(greeting, "maybe_prepend_daily_greeting", boom)
    assert base._daily_greeting_final(_source(platform="telegram"), "Tekst") == "Tekst"


def test_hook_does_not_touch_delivery_routing(monkeypatch, tmp_path):
    """Regression: an extra ``_final_delivery_adapter`` call broke reconnect detection in
    ``send_final_ledgered`` (tests/gateway/test_delivery_ledger_producer.py)."""
    _write_config(_home(monkeypatch, tmp_path))
    source = _source()
    source.platform = MagicMock(value="telegram")
    base._daily_greeting_final(source, "Tekst")
    assert not source.platform.method_calls
