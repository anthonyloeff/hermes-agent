"""Profile-scoped first-contact-of-day greeting helper for Hermes deliveries."""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)
_STATE_LOCK = threading.RLock()

_DEFAULT_TZ = "Europe/Amsterdam"
_DEFAULT_RECIPIENT = "Anthony"
_NOTICE_PREFIXES = ("\u26a0",)  # "⚠️ Something went wrong ...", "⚠️ Session storage ..."
_GREETING_RE = re.compile(
    r"^\s*(goedemorgen|goedemiddag|goedenavond|hallo)\b\s*,?\s*anthony[.!,:;]?\s*",
    re.IGNORECASE,
)


def _state_path() -> Path:
    return get_hermes_home() / "state" / "daily_greeting_state.json"


def _load_state(path: Path) -> dict[str, str]:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Daily greeting state load failed: %s", exc)
        return {}


def _save_state(path: Path, state: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _daypart_greeting(now: datetime, recipient_name: str) -> str:
    hour = now.hour
    if 6 <= hour <= 11:
        greeting = "Goedemorgen"
    elif 12 <= hour <= 17:
        greeting = "Goedemiddag"
    elif 18 <= hour <= 21:
        greeting = "Goedenavond"
    else:
        greeting = "Hallo"
    return f"{greeting}, {recipient_name}."


def _daily_config(config: dict | None) -> dict:
    cfg = config or {}
    daily_cfg = cfg.get("daily_greeting", {}) if isinstance(cfg, dict) else {}
    return daily_cfg if isinstance(daily_cfg, dict) else {}


def _enabled_config(config: dict | None) -> tuple[bool, str, str, str]:
    daily_cfg = _daily_config(config)
    if not daily_cfg:
        return False, _DEFAULT_RECIPIENT, _DEFAULT_TZ, "target"
    scope = str(daily_cfg.get("scope") or "target").lower().strip()
    if scope not in {"target", "platform", "profile"}:
        scope = "target"
    return (
        bool(daily_cfg.get("enabled", False)),
        str(daily_cfg.get("recipient_name") or _DEFAULT_RECIPIENT),
        str(daily_cfg.get("timezone") or _DEFAULT_TZ),
        scope,
    )


def _state_key(*, platform: str, chat_id: str, thread_id: str | None, scope: str) -> str:
    platform_key = str(platform).lower()
    if scope == "profile":
        return "profile|daily_greeting"
    if scope == "platform":
        return f"platform|{platform_key}"
    return f"{platform_key}|{chat_id}|{thread_id or ''}"


def _is_excluded_target(
    config: dict | None,
    *,
    platform: str,
    chat_id: str,
    thread_id: str | None = None,
) -> bool:
    """Return True when daily greetings are disabled for this delivery target."""
    cfg = config or {}
    daily_cfg = cfg.get("daily_greeting", {}) if isinstance(cfg, dict) else {}
    if not isinstance(daily_cfg, dict):
        return False

    excluded = daily_cfg.get("excluded_targets", [])
    if not isinstance(excluded, list):
        return False

    target = {
        "platform": str(platform).lower(),
        "chat_id": str(chat_id),
        "thread_id": "" if thread_id is None else str(thread_id),
    }
    target_key = f"{target['platform']}|{target['chat_id']}|{target['thread_id']}"

    for item in excluded:
        if isinstance(item, str):
            if item == target_key:
                return True
            continue
        if not isinstance(item, dict):
            continue
        item_platform = str(item.get("platform", "")).lower()
        item_chat_id = str(item.get("chat_id", ""))
        if not item_platform or not item_chat_id:
            continue
        if item_platform != target["platform"] or item_chat_id != target["chat_id"]:
            continue
        if "thread_id" not in item:
            return True
        item_thread_id = "" if item.get("thread_id") is None else str(item.get("thread_id"))
        if item_thread_id == target["thread_id"]:
            return True
    return False


def maybe_prepend_daily_greeting(
    content: str,
    *,
    platform: str,
    chat_id: str,
    thread_id: str | None = None,
    config: dict | None = None,
) -> str:
    """Prepend a Dutch greeting once per local day for this profile/target.

    State is stored below the active HERMES_HOME, so named profiles do not share
    greeting state. If the content already starts with a supported greeting, the
    day is still marked as greeted to avoid a duplicate later that day.
    """
    if not content:
        return content
    # System notices (gateway failure/warning texts) never open the day and never claim it.
    if content.lstrip().startswith(_NOTICE_PREFIXES):
        return content

    try:
        enabled, recipient_name, tz_name, scope = _enabled_config(config)
        if not enabled:
            return content
        if _is_excluded_target(
            config,
            platform=platform,
            chat_id=chat_id,
            thread_id=thread_id,
        ):
            return content

        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            logger.warning("Invalid daily_greeting.timezone=%r; falling back to %s", tz_name, _DEFAULT_TZ)
            tz = ZoneInfo(_DEFAULT_TZ)

        now = datetime.now(tz)
        today = now.date().isoformat()
        key = _state_key(
            platform=platform,
            chat_id=chat_id,
            thread_id=thread_id,
            scope=scope,
        )
        path = _state_path()
        with _STATE_LOCK:
            state = _load_state(path)
            if state.get(key) == today:
                return content
            state[key] = today
            _save_state(path, state)

        if _GREETING_RE.match(content):
            return content
        return f"{_daypart_greeting(now, recipient_name)}\n\n{content}"
    except Exception as exc:
        logger.warning("Daily greeting failed: %s", exc)
        return content


def greet_platform_final(platform: str, source, text: str) -> str:
    """Gateway final-reply hook (``gateway/platforms/base.py``): profile config read at call time."""
    if not text:
        return text
    try:
        from hermes_cli.config import load_config_readonly

        return maybe_prepend_daily_greeting(
            text, platform=platform, chat_id=str(getattr(source, "chat_id", "") or ""),
            thread_id=getattr(source, "thread_id", None), config=load_config_readonly())
    except Exception as exc:
        logger.warning("[%s] Daily greeting failed: %s", platform, exc)
        return text


def greet_pwa(text: str, config: dict | None = None) -> str:
    """PWA lanes (API runs + cron ``pwa:self``): one profile-scoped greeting key, never blocks."""
    if not text:
        return text
    try:
        if config is None:
            from hermes_cli.config import load_config_readonly
            config = load_config_readonly()
        return maybe_prepend_daily_greeting(text, platform="pwa", chat_id="", config=config)
    except Exception as exc:
        logger.warning("[pwa] Daily greeting failed: %s", exc)
        return text


class RunGreetingBuffer:
    """Holds the first streamed characters of an API run until the opening is known, so a
    model-authored greeting is detected instead of doubled. Not thread-safe by design: deltas
    come from one agent thread and ``flush`` runs after that thread finished."""

    _MIN_CHARS = 24

    def __init__(self) -> None:
        self.done = False
        self._buf: list[str] = []

    def feed(self, delta: str) -> str:
        if self.done:
            return delta
        self._buf.append(delta)
        joined = "".join(self._buf)
        if len(joined.strip()) < self._MIN_CHARS and "\n" not in joined.strip():
            return ""
        return self.flush()

    def flush(self) -> str:
        if self.done:
            return ""
        self.done = True
        joined, self._buf = "".join(self._buf), []
        return greet_pwa(joined) if joined.strip() else joined

    def greet_output(self, output: str) -> str:
        """Non-streamed run: greet the final output once."""
        if self.done or not output:
            return output
        self.done = True
        return greet_pwa(output)


def greet_cron_delivery(platform: str, chat_id: str, thread_id, text: str, config: dict | None) -> str:
    """Cron delivery hook (``cron/scheduler_delivery.py``): same once-per-day state as chat finals."""
    if not text or not config:
        return text
    return maybe_prepend_daily_greeting(text, platform=platform, chat_id=str(chat_id or ""),
                                        thread_id=thread_id, config=config)
