"""Anthony-local: PWA daily greeting (API runs + cron pwa:self) and notice exclusion."""

import agent_daily_greeting as g

CFG = {"daily_greeting": {"enabled": True, "recipient_name": "Anthony",
                          "timezone": "Europe/Amsterdam", "scope": "profile"}}


def _cfg(monkeypatch, tmp_path):
    monkeypatch.setattr(g, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr("hermes_cli.config.load_config_readonly", lambda *a, **k: CFG)


def test_failure_notice_neither_greeted_nor_claims_day(monkeypatch, tmp_path):
    _cfg(monkeypatch, tmp_path)
    notice = "\u26a0\ufe0f Something went wrong and I couldn't finish this reply."
    assert g.maybe_prepend_daily_greeting(notice, platform="telegram", chat_id="1", config=CFG) == notice
    out = g.maybe_prepend_daily_greeting("Antwoord.", platform="telegram", chat_id="1", config=CFG)
    assert out.endswith("Antwoord.") and out != "Antwoord."


def test_streamed_run_greets_once_and_keeps_text(monkeypatch, tmp_path):
    _cfg(monkeypatch, tmp_path)
    buf = g.RunGreetingBuffer()
    parts = ["Mooi", ", dan ", "staat Desktop goed en ", "werkt alles."]
    emitted = "".join(buf.feed(p) for p in parts) + buf.flush()
    assert emitted.endswith("Mooi, dan staat Desktop goed en werkt alles.")
    assert emitted.split(",")[0] in {"Goedemorgen", "Goedemiddag", "Goedenavond", "Hallo"}
    second = g.RunGreetingBuffer()
    again = "".join(second.feed(p) for p in parts) + second.flush()
    assert again == "".join(parts)


def test_model_authored_greeting_not_doubled(monkeypatch, tmp_path):
    _cfg(monkeypatch, tmp_path)
    buf = g.RunGreetingBuffer()
    text = "Goedemorgen, Anthony.\n\nHier is de status."
    emitted = "".join(buf.feed(c) for c in text) + buf.flush()
    assert emitted == text


def test_short_reply_flushed_at_end(monkeypatch, tmp_path):
    _cfg(monkeypatch, tmp_path)
    buf = g.RunGreetingBuffer()
    assert buf.feed("Klaar.") == ""
    out = buf.flush()
    assert out.endswith("\n\nKlaar.") and buf.flush() == ""


def test_non_streamed_output_and_cron_share_profile_key(monkeypatch, tmp_path):
    _cfg(monkeypatch, tmp_path)
    assert g.greet_pwa("Cronbericht.", CFG) != "Cronbericht."
    buf = g.RunGreetingBuffer()
    assert buf.greet_output("Run-antwoord.") == "Run-antwoord."


def test_disabled_profile_untouched(monkeypatch, tmp_path):
    monkeypatch.setattr(g, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr("hermes_cli.config.load_config_readonly", lambda *a, **k: {})
    buf = g.RunGreetingBuffer()
    assert "".join(buf.feed(p) for p in ["Een langer antwoord ", "zonder groet."]) + buf.flush() \
        == "Een langer antwoord zonder groet."
