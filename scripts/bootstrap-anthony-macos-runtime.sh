#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_VENV="${HERMES_RUNTIME_VENV:-$ROOT/.venv-runtime}"
PYTHON_BIN="${HERMES_RUNTIME_PYTHON:-/opt/homebrew/opt/python@3.12/bin/python3.12}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  printf 'Required Python not found: %s\n' "$PYTHON_BIN" >&2
  exit 1
fi

"$PYTHON_BIN" - <<'PY'
import sqlite3

version = tuple(map(int, sqlite3.sqlite_version.split(".")))
safe = version >= (3, 51, 3) or version in {(3, 50, 7), (3, 44, 6)}
if not safe:
    raise SystemExit(f"Unsafe SQLite runtime: {sqlite3.sqlite_version}")
print(f"Python SQLite runtime: {sqlite3.sqlite_version}")
PY

cd "$ROOT"
uv venv "$RUNTIME_VENV" --python "$PYTHON_BIN" --clear
UV_PROJECT_ENVIRONMENT="$RUNTIME_VENV" uv sync --frozen \
  --python "$PYTHON_BIN" \
  --extra acp \
  --extra mcp \
  --extra messaging \
  --extra hindsight
uv pip install --python "$RUNTIME_VENV/bin/python" \
  --requirement deploy/anthony-macos-runtime-requirements.txt
uv pip check --python "$RUNTIME_VENV/bin/python"

"$RUNTIME_VENV/bin/python" - <<'PY'
import importlib.metadata as metadata
import sqlite3

expected = {
    "agent-client-protocol": "0.9.0",
    "hindsight-all": "0.8.3",
    "hindsight-embed": "0.8.3",
    "hindsight-client": "0.6.1",
    "mcp": "1.28.1",
    "sentence-transformers": "5.6.0",
}
actual = {name: metadata.version(name) for name in expected}
if actual != expected:
    raise SystemExit(f"Runtime dependency mismatch: {actual}")
if tuple(map(int, sqlite3.sqlite_version.split("."))) < (3, 51, 3):
    raise SystemExit(f"Runtime SQLite is not current enough: {sqlite3.sqlite_version}")
print({"runtime_dependencies": actual, "sqlite": sqlite3.sqlite_version})
PY
