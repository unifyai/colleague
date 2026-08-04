#!/usr/bin/env bash
# Launcher for the hermes-agent comparison arm.
#
# Requires a synced hermes-agent checkout (default ~/hermes-agent; override
# with RWR_HERMES_REPO) — run `uv sync` there once. Uses OPENROUTER_API_KEY
# from unify/.env unless already exported.
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
exec .venv/bin/python -m colleague.arms.hermes "$@"
