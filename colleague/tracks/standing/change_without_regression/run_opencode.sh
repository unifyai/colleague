#!/usr/bin/env bash
# Launcher for the change without regression benchmark, OpenCode arm.
#
# Requires an OpenCode checkout (default ~/opencode; override with
# OCODE_REPO). Uses OPENROUTER_API_KEY from .env unless already exported.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

if [[ -z "${OPENROUTER_API_KEY:-}" && -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
: "${OPENROUTER_API_KEY:?OPENROUTER_API_KEY required}"

export PYTHONUNBUFFERED=1
exec .venv/bin/python -m colleague.tracks.standing.change_without_regression.opencode "$@"
