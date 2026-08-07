from pathlib import Path

from gateway.config import Platform, load_gateway_config


def test_top_level_telegram_group_topics_bridge_to_platform_extra(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    (home / "config.yaml").write_text(
        """
telegram:
  allowed_chats: -1003989269873
  group_topics:
  - chat_id: -1003989269873
    topics:
    - thread_id: 13
      name: Angel
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHATS", raising=False)

    cfg = load_gateway_config()
    telegram = cfg.platforms[Platform.TELEGRAM]

    assert telegram.extra["group_topics"] == [
        {
            "chat_id": -1003989269873,
            "topics": [{"thread_id": 13, "name": "Angel"}],
        }
    ]


def test_top_level_telegram_dm_topics_bridge_to_platform_extra(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    (home / "config.yaml").write_text(
        """
telegram:
  dm_topics:
  - chat_id: 208214988
    topics:
    - thread_id: 17585
      name: Coaching
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(home))

    cfg = load_gateway_config()
    telegram = cfg.platforms[Platform.TELEGRAM]

    assert telegram.extra["dm_topics"] == [
        {
            "chat_id": 208214988,
            "topics": [{"thread_id": 17585, "name": "Coaching"}],
        }
    ]
