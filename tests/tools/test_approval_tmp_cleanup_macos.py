"""macOS ``/tmp`` spelling for Hermes verification-artifact cleanup (Anthony-local; part of 66b990d4db).

On macOS ``/tmp`` is a symlink to ``/private/tmp``. The agent naturally writes ``rm -f /tmp/hermes-verify-x``,
which must be recognised as the same narrow cleanup as the realpath spelling, and nothing broader.
"""

import os
import tempfile

import pytest

from tools.approval_detection import _is_verification_artifact_cleanup


@pytest.mark.platforms("macos")
def test_literal_tmp_spelling_is_accepted_when_tmp_is_the_tempdir(monkeypatch):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: "/tmp")
    assert os.path.realpath("/tmp") != "/tmp"
    assert _is_verification_artifact_cleanup("rm -f /tmp/hermes-verify-abc.py")
    assert _is_verification_artifact_cleanup(f"rm -f {os.path.realpath('/tmp')}/hermes-ad-hoc-1.sh")


@pytest.mark.parametrize("command", [
    "rm -f /tmp/not-hermes.py",
    "rm -f /tmp/sub/hermes-verify-abc.py",
    "rm -rf /tmp/hermes-verify-abc.py",
    "rm -f /etc/hermes-verify-abc.py",
])
def test_anything_broader_is_still_rejected(monkeypatch, command):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: "/tmp")
    assert not _is_verification_artifact_cleanup(command)
