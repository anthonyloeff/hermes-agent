#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_VENV="${HINDSIGHT_RUNTIME_VENV:-$HOME/.hermes/runtime/hindsight-v0.8.3}"
PYTHON_BIN="${HINDSIGHT_RUNTIME_PYTHON:-/opt/homebrew/opt/python@3.12/bin/python3.12}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  printf 'Required Python not found: %s\n' "$PYTHON_BIN" >&2
  exit 1
fi

"$PYTHON_BIN" - <<'PY'
import sqlite3

version = tuple(map(int, sqlite3.sqlite_version.split(".")))
if version < (3, 51, 3):
    raise SystemExit(f"Runtime SQLite is not current enough: {sqlite3.sqlite_version}")
print(f"Python SQLite runtime: {sqlite3.sqlite_version}")
PY

uv venv "$RUNTIME_VENV" --python "$PYTHON_BIN" --clear
uv pip install --python "$RUNTIME_VENV/bin/python" \
  --requirement "$ROOT/deploy/anthony-hindsight-runtime-requirements.txt"
uv pip check --python "$RUNTIME_VENV/bin/python"

"$RUNTIME_VENV/bin/python" - <<'PY'
import importlib.metadata as metadata

expected = {
    "hindsight-all": "0.8.3",
    "hindsight-api-slim": "0.8.3",
    "hindsight-embed": "0.8.3",
    "hindsight-client": "0.6.1",
    "sentence-transformers": "5.6.0",
    "mcp": "1.28.1",
}
actual = {name: metadata.version(name) for name in expected}
if actual != expected:
    raise SystemExit(f"Hindsight runtime dependency mismatch: {actual}")
print({"hindsight_runtime_dependencies": actual})
PY