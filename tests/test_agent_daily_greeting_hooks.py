"""Daily-greeting hooks on v0.22 delivery paths (Anthony-local; port of 6ba2a5b9bf).

E2E against a temp HERMES_HOME: the real config loader must surface ``daily_greeting``, chat finals
and cron deliveries share one once-per-day state, and the gateway hook never raises.
"""

from types import SimpleNamespace

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


def test_real_config_loader_surfaces_daily_greeting(monkeypatch, tmp_path):
    _write_config(_home(monkeypatch, tmp_path))
    from hermes_cli.config import load_config_readonly
    assert load_config_readonly()["daily_greeting"]["enabled"] is True


def test_gateway_final_greets_once_then_cron_does_not_repeat(monkeypatch, tmp_path):
    home = _home(monkeypatch, tmp_path)
    _write_config(home)
    adapter = SimpleNamespace(platform=SimpleNamespace(value="Telegram"))
    source = SimpleNamespace(chat_id="123", thread_id=None)

    first = base._daily_greeting_final(adapter, source, "Status: gereed")
    assert first.endswith("\n\nStatus: gereed")
    assert greeting._GREETING_RE.match(first)
    assert base._daily_greeting_final(adapter, source, "Tweede") == "Tweede"

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
    adapter = SimpleNamespace(platform="telegram")
    source = SimpleNamespace(chat_id="1", thread_id=None)
    assert base._daily_greeting_final(adapter, source, "Tekst") == "Tekst"
    _write_config(home, enabled=False)
    assert base._daily_greeting_final(adapter, source, "Tekst") == "Tekst"
    assert greeting.greet_cron_delivery("telegram", "1", None, "Tekst", None) == "Tekst"


def test_gateway_hook_never_raises(monkeypatch, tmp_path):
    _write_config(_home(monkeypatch, tmp_path))
    def boom(*a, **k):
        raise RuntimeError("state disk full")
    monkeypatch.setattr(greeting, "maybe_prepend_daily_greeting", boom)
    assert base._daily_greeting_final(SimpleNamespace(platform="telegram"),
                                      SimpleNamespace(chat_id="1"), "Tekst") == "Tekst"
