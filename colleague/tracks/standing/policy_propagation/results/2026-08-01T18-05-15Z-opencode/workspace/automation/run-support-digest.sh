#!/bin/sh

set -eu

ROOT="/Users/djl11/unify/benchmarks/policy_propagation/results/2026-08-01T18-05-15Z-opencode/workspace"
OPENCODE="/Users/djl11/unify/benchmarks/policy_propagation/results/2026-08-01T18-05-15Z-opencode/opencode_state/bin/opencode"
LOCK_DIR="$ROOT/automation/.support-digest.lock"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  exit 0
fi
trap 'rmdir "$LOCK_DIR"' EXIT HUP INT TERM

"$OPENCODE" run --dir "$ROOT" --command support-digest
