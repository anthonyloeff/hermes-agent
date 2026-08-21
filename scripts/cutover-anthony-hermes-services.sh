#!/usr/bin/env bash
set -euo pipefail

OLD="/Users/macmini/.hermes/runtime/hermes-v0.20.0"
NEW="/Users/macmini/.hermes/runtime/hermes-v0.20.4"
STAMP="$(date +%Y%m%d-%H%M%S)"

if [[ "$EUID" -ne 0 ]]; then
  printf 'Run this script with sudo from a separate Terminal window.\n' >&2
  exit 77
fi
if [[ ! -x "$NEW/.venv-runtime/bin/python" ]]; then
  printf 'Candidate runtime is missing: %s\n' "$NEW" >&2
  exit 69
fi

if [[ "$#" -eq 0 ]]; then
  set -- angel-pa m-pa angel kelly default
fi

plist_for() {
  case "$1" in
    default) printf '/Library/LaunchDaemons/ai.hermes.gateway.plist\n' ;;
    angel) printf '/Library/LaunchDaemons/ai.hermes.gateway-angel.plist\n' ;;
    angel-pa) printf '/Library/LaunchDaemons/ai.hermes.gateway-angel-pa.plist\n' ;;
    kelly) printf '/Library/LaunchDaemons/ai.hermes.gateway-kelly.plist\n' ;;
    m-pa) printf '/Library/LaunchDaemons/ai.hermes.gateway-m-pa.plist\n' ;;
    *) return 64 ;;
  esac
}
label_for() {
  case "$1" in
    default) printf 'ai.hermes.gateway\n' ;;
    *) printf 'ai.hermes.gateway-%s\n' "$1" ;;
  esac
}

for profile in "$@"; do
  plist="$(plist_for "$profile")" || { printf 'Unsupported profile: %s\n' "$profile" >&2; exit 64; }
  label="$(label_for "$profile")"
  backup="${plist}.pre-v0204-${STAMP}"
  cp -p "$plist" "$backup"

  /usr/bin/python3 - "$plist" "$OLD" "$NEW" <<'PY'
import os, plistlib, sys, tempfile
from pathlib import Path
path, old, new = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
with path.open('rb') as f:
    data = plistlib.load(f)

def replace(value):
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [replace(v) for v in value]
    if isinstance(value, dict):
        return {k: replace(v) for k, v in value.items()}
    return value

updated = replace(data)
if updated == data and new not in repr(data):
    raise SystemExit(f'No runtime path found in {path}')
fd, tmp_name = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
try:
    with os.fdopen(fd, 'wb') as f:
        plistlib.dump(updated, f, fmt=plistlib.FMT_XML, sort_keys=False)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp_name, 0o644)
    os.chown(tmp_name, 0, 0)
    os.replace(tmp_name, path)
finally:
    if os.path.exists(tmp_name):
        os.unlink(tmp_name)
PY

  plutil -lint "$plist" >/dev/null
  if /usr/bin/grep -q "$OLD" "$plist"; then
    printf 'Old runtime path remains in %s\n' "$plist" >&2
    cp -p "$backup" "$plist"
    exit 65
  fi

  launchctl bootout "system/$label" 2>/dev/null || true
  if ! launchctl bootstrap system "$plist"; then
    printf 'Bootstrap failed for %s, restoring old plist.\n' "$label" >&2
    cp -p "$backup" "$plist"
    launchctl bootstrap system "$plist" || true
    exit 70
  fi
  launchctl enable "system/$label"

  ready=0
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if launchctl print "system/$label" 2>/dev/null | /usr/bin/grep -q 'state = running'; then
      ready=1
      break
    fi
    sleep 1
  done
  if [[ "$ready" -ne 1 ]]; then
    printf 'Service did not become ready: %s. Restoring old plist.\n' "$label" >&2
    launchctl bootout "system/$label" 2>/dev/null || true
    cp -p "$backup" "$plist"
    launchctl bootstrap system "$plist" || true
    exit 71
  fi
  printf 'MIGRATED %s\n' "$label"
done
