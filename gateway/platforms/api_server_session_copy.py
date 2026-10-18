"""Privacy-projected session copies for ``POST /api/sessions/{id}/fork`` (Anthony-local).

Port of 93dfc7115a to v0.22.2. ``preserve_source: true`` leaves the source session open (a
cross-client import, not a CLI ``/branch``); ``projection: "conversation"`` keeps only visible
user/assistant text with secrets, ``MEDIA:`` lines and local paths removed and same-role turns
merged so role alternation holds; ``copy_system_prompt: false`` drops the source prompt.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from agent.redact import redact_sensitive_text

PROJECTIONS = frozenset({"full", "conversation"})

_MEDIA_LINE_RE = re.compile(r"(?im)^\s*MEDIA\s*:\s*\S+[^\r\n]*$")
_LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:/Users/[^\s\]\[(){}<>\"']+|/tmp/[^\s\]\[(){}<>\"']+"
    r"|/private/[^\s\]\[(){}<>\"']+|/Volumes/[^\s\]\[(){}<>\"']+|[A-Za-z]:\\[^\s\]\[(){}<>\"']+)"
)
_TEXT_PARTS = frozenset({"text", "input_text", "output_text"})
_IMAGE_PARTS = frozenset({"image_url", "input_image"})


def session_copy_text(content: Any) -> str:
    """User-visible text without secrets, local paths, or binary payloads."""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") in _TEXT_PARTS and isinstance(part.get("text"), str):
                parts.append(part["text"])
            elif part.get("type") in _IMAGE_PARTS:
                parts.append("[Eerdere afbeelding uit bronchat]")
        text = "\n".join(parts)
    else:
        text = ""
    text = redact_sensitive_text(text, force=True)
    text = _MEDIA_LINE_RE.sub("[Eerdere bijlage uit bronchat]", text)
    text = _LOCAL_PATH_RE.sub("[lokaal pad verwijderd]", text)
    return text.strip()


def project_conversation(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Project a transcript to alternating visible user/assistant conversation."""
    projected: List[Dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        text = session_copy_text(message.get("content"))
        if not text:
            continue
        if projected and projected[-1]["role"] == role:
            projected[-1]["content"] = f"{projected[-1]['content']}\n\n{text}"
            continue
        item: Dict[str, Any] = {"role": role, "content": text}
        if message.get("timestamp") is not None:
            item["timestamp"] = message.get("timestamp")
        projected.append(item)
    return projected
