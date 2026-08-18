#!/usr/bin/env bash
# Launcher for the drift recovery benchmark, prime-agent arm.
#
# Requires a built prime-agent checkout (default ~/prime-agent; override with
# PRIME_AGENT_REPO) — run `npm ci && npm run build` there once. Uses
# OPENROUTER_API_KEY from .env unless already exported.
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
exec .venv/bin/python -m colleague.tracks.standing.drift_recovery.prime_agent "$@"
