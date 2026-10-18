#!/usr/bin/env bash
set -euo pipefail

PROFILE="${1:-}"
case "$PROFILE" in
  jill-default|kelly-legal|angel-anthony) ;;
  *)
    printf 'Unsupported Hindsight profile: %s\n' "$PROFILE" >&2
    exit 64
    ;;
esac

BIN="/Users/macmini/.hermes/runtime/hindsight-v0.8.3/bin/hindsight-embed"
if [[ ! -x "$BIN" ]]; then
  printf 'Hindsight runtime missing: %s\n' "$BIN" >&2
  exit 69
fi

exec "$BIN" -p "$PROFILE" daemon start
