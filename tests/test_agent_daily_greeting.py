from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import time

import agent_daily_greeting as greeting


def _config(excluded_targets=None):
    return {
        "daily_greeting": {
            "enabled": True,
            "recipient_name": "Anthony",
            "timezone": "Europe/Amsterdam",
            "excluded_targets": excluded_targets or [],
        }
    }


def test_daily_greeting_excludes_exact_thread(monkeypatch, tmp_path):
    monkeypatch.setattr(greeting, "get_hermes_home", lambda: tmp_path)

    result = greeting.maybe_prepend_daily_greeting(
        "TEST",
        platform="telegram",
        chat_id="-1003989269873",
        thread_id="4",
        config=_config([
            {"platform": "telegram", "chat_id": "-1003989269873", "thread_id": "4"}
        ]),
    )

    assert result == "TEST"
    assert not (tmp_path / "state" / "daily_greeting_state.json").exists()


def test_daily_greeting_exclusion_does_not_affect_other_threads(monkeypatch, tmp_path):
    monkeypatch.setattr(greeting, "get_hermes_home", lambda: tmp_path)

    result = greeting.maybe_prepend_daily_greeting(
        "TEST",
        platform="telegram",
        chat_id="-1003989269873",
        thread_id="99",
        config=_config([
            {"platform": "telegram", "chat_id": "-1003989269873", "thread_id": "4"}
        ]),
    )

    assert result.endswith("\n\nTEST")
    assert result != "TEST"


def test_daily_greeting_supports_string_exclusion(monkeypatch, tmp_path):
    monkeypatch.setattr(greeting, "get_hermes_home", lambda: tmp_path)

    result = greeting.maybe_prepend_daily_greeting(
        "TEST",
        platform="telegram",
        chat_id="-1003989269873",
        thread_id="4",
        config=_config(["telegram|-1003989269873|4"]),
    )

    assert result == "TEST"


def test_profile_scope_greets_once_across_threads(monkeypatch, tmp_path):
    monkeypatch.setattr(greeting, "get_hermes_home", lambda: tmp_path)
    cfg = _config()
    cfg["daily_greeting"]["scope"] = "profile"

    first = greeting.maybe_prepend_daily_greeting(
        "FIRST",
        platform="telegram",
        chat_id="-1003989269873",
        thread_id="4",
        config=cfg,
    )
    second = greeting.maybe_prepend_daily_greeting(
        "SECOND",
        platform="telegram",
        chat_id="-1003989269873",
        thread_id="24",
        config=cfg,
    )

    assert first.endswith("\n\nFIRST")
    assert first != "FIRST"
    assert second == "SECOND"


def test_concurrent_first_contacts_emit_one_greeting(monkeypatch, tmp_path):
    monkeypatch.setattr(greeting, "get_hermes_home", lambda: tmp_path)
    original_load = greeting._load_state

    def slow_load(path):
        time.sleep(0.01)
        return original_load(path)

    monkeypatch.setattr(greeting, "_load_state", slow_load)
    cfg = _config()

    def deliver(index):
        content = f"MESSAGE-{index}"
        result = greeting.maybe_prepend_daily_greeting(
            content,
            platform="telegram",
            chat_id="123",
            config=cfg,
        )
        return content, result

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(deliver, range(8)))

    greeted = sum(result != content for content, result in results)
    assert greeted == 1
