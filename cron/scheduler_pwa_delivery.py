"""Cron delivery into this profile's private loopback PWA inbox (``deliver: pwa`` / ``pwa:self``).

Anthony-local integration, ported from the v0.21 fleet runtime. The target is always the job's
own profile: ``pwa:<other>`` is not a PWA token and fails preflight as an unknown platform. The
endpoint must be an explicit loopback HTTP origin and the ingest key comes from the profile's
``.env`` (``AGENT_PWA_CRON_INGEST_KEY``), never from config.yaml.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Optional

from hermes_cli.config import get_env_value  # scope-aware under multiplexed profiles

PWA_DELIVERY_PLATFORM = "pwa"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def is_pwa_delivery_token(part: str) -> bool:
    """Whether a deliver token routes into this profile's private PWA inbox."""
    return (part or "").strip().lower() in {PWA_DELIVERY_PLATFORM, f"{PWA_DELIVERY_PLATFORM}:self"}


def pwa_target() -> dict:
    return {
        "platform": PWA_DELIVERY_PLATFORM,
        "chat_id": "self",
        "thread_id": None,
        "_resolved_from": "explicit",
    }


def _loopback_origin(base_url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(base_url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname in _LOOPBACK_HOSTS
        and bool(port)
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )


def deliver_to_pwa(job: dict, content: str) -> Optional[str]:
    """POST one cron result to the loopback PWA inbox. Returns None on success, else an error."""
    from cron import scheduler as _sched

    try:
        cfg = _sched.load_config() or {}
        pwa_cfg = (cfg.get("cron", {}) or {}).get("pwa_delivery", {}) or {}
    except Exception as exc:
        return f"PWA delivery config could not be loaded: {exc}"
    if not pwa_cfg.get("enabled", False):
        return "PWA delivery is disabled in cron.pwa_delivery.enabled"
    base_url = str(pwa_cfg.get("url") or "").strip().rstrip("/")
    if not _loopback_origin(base_url):
        return "PWA delivery URL must be an explicit loopback HTTP origin with a port"
    key = str(get_env_value("AGENT_PWA_CRON_INGEST_KEY") or "").strip()
    if len(key) < 32:
        return "PWA delivery credential is missing or too short"
    execution_id = str(
        job.get("_delivery_execution_id") or job.get("execution_id") or f"manual-{uuid.uuid4().hex}"
    )
    payload = json.dumps(
        {
            "jobId": str(job.get("id") or "")[:80],
            "executionId": execution_id[:128],
            "jobName": str(job.get("name") or job.get("id") or "Cronjob")[:120],
            "content": content,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/automation/deliver",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "Hermes-Cron-PWA/1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read(65536).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return f"PWA delivery returned HTTP {exc.code}"
    except Exception as exc:
        return f"PWA delivery failed: {type(exc).__name__}"
    if not isinstance(result, dict) or not result.get("accepted"):
        return "PWA delivery endpoint did not acknowledge the cron result"
    return None
