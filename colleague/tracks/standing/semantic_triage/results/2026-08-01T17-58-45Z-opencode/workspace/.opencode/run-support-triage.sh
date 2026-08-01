#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OPENCODE=/Users/djl11/unify/benchmarks/semantic_triage/results/2026-08-01T17-58-45Z-opencode/opencode_state/bin/opencode

exec "$OPENCODE" run \
  --dir "$PROJECT_DIR" \
  --agent support-triage \
  --auto \
  --title "Hourly support triage" \
  "Perform one support-triage run now."
