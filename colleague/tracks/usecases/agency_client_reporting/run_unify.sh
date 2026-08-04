#!/usr/bin/env bash
# Launcher for the agency-client-reporting measurement, Unify arm.
#
# Prepares the environment BEFORE Python starts (unify settings read env at
# import time), probes staging Orchestra auth, then runs the driver.
#
# Overrides:
#   ACR_CHECK=true        boot everything, print the utterance, spend nothing
#   ACR_RUNS              monthly wakes (default 1; 2 also measures convergence)
#   ACR_ORCHESTRA_URL     target Orchestra (default: staging)
#   ACR_UNIFY_KEY         key to use (default: SHARED_UNIFY_KEY from .env)
#   ACR_SEED / ACR_PORT   fixture data seed / port
#   ACR_USECASES_TSX      path to landing-page src/data/useCases.tsx
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -x .venv/bin/python ]]; then
  echo "error: .venv missing — run: pip install uv && uv sync --all-groups" >&2
  exit 1
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export ORCHESTRA_URL="${ACR_ORCHESTRA_URL:-https://api.staging.internal.saas.unify.ai/v0}"
export UNIFY_KEY="${ACR_UNIFY_KEY:-${SHARED_UNIFY_KEY:-${UNIFY_KEY:-}}}"
if [[ -z "$UNIFY_KEY" ]]; then
  echo "error: no key — set ACR_UNIFY_KEY, or SHARED_UNIFY_KEY/UNIFY_KEY in .env" >&2
  exit 1
fi

# Measurement invariants.
export PYTHONUNBUFFERED=1       # live phase markers when piped/tee'd
export UNILLM_CACHE=false
export TEST=true                # unify.init honors the pre-set context
unset ASSISTANT_ID              # never bind to a real assistant
export TQDM_DISABLE=1

# Real manager implementations (mirrors sandboxes/conversation_manager).
for m in CONTACT TRANSCRIPT TASK KNOWLEDGE GUIDANCE SECRET WEB FILE DATA FUNCTION CONVERSATION MEMORY CONFIG; do
  export "UNITY_${m}_IMPL=real"
done

# Fail fast on auth before burning any tokens.
probe_url="$ORCHESTRA_URL/projects"
[[ "$ORCHESTRA_URL" != */v0 ]] && probe_url="${ORCHESTRA_URL%/}/v0/projects"
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
  -H "Authorization: Bearer $UNIFY_KEY" "$probe_url" || true)
if [[ "$code" != "200" ]]; then
  echo "error: auth probe against $probe_url returned HTTP $code" >&2
  echo "       (staging needs a staging-valid key, e.g. SHARED_UNIFY_KEY)" >&2
  exit 1
fi
echo "[run_unify.sh] auth OK against $ORCHESTRA_URL"

exec .venv/bin/python -m colleague.tracks.usecases.agency_client_reporting.unify "$@"
