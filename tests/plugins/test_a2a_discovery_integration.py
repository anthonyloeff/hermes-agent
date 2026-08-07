"""End-to-end discovery contract for the hybrid A2A plugin."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_enabled_a2a_plugin_exposes_outbound_tools_without_gateway_lookup(tmp_path):
    """Outbound A2A must work in plain CLI sessions.

    Bundled platform plugins are normally deferred until a gateway asks for the
    platform. A2A is hybrid: it also owns outbound model tools, so those tools
    must be registered during normal plugin discovery.
    """
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(
        "plugins:\n  enabled:\n    - a2a-platform\n",
        encoding="utf-8",
    )

    repo = Path(__file__).resolve().parents[2]
    code = """
from hermes_cli.plugins import discover_plugins
discover_plugins(force=True)
from tools.registry import registry
expected = {'a2a_discover', 'a2a_call', 'a2a_list', 'a2a_history', 'a2a_orchestrate'}
actual = set(registry.get_tool_names_for_toolset('a2a'))
if actual != expected:
    raise SystemExit(f'a2a toolset mismatch: {sorted(actual)}')
from gateway.platform_registry import platform_registry
if platform_registry.get('a2a') is None:
    raise SystemExit('a2a platform was not registered')
"""
    env = os.environ.copy()
    env["HERMES_HOME"] = str(home)
    env["PYTHONPATH"] = str(repo)

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
