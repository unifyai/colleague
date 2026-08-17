#!/usr/bin/env bash
# Launcher for the repair locality benchmark, hermes-agent arm.
#
# Requires a hermes-agent checkout (default ~/hermes-agent; override with
# RWR_HERMES_REPO) with `uv sync` run once. Uses OPENROUTER_API_KEY from .env
# unless already exported.
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
exec .venv/bin/python -m colleague.tracks.standing.repair_locality.hermes "$@"
