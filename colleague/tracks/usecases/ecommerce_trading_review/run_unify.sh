#!/usr/bin/env bash
# Launcher for the ecommerce-trading-review measurement, Unify arm.
#
# Prepares the environment BEFORE Python starts (unify settings read env at
# import time), probes staging Orchestra auth, then runs the driver.
#
# Overrides:
#   ETR_CHECK=true        boot everything, print the utterance, spend nothing
#   ETR_RUNS              Monday wakes (default 2; guarantees one aligned window)
#   ETR_ORCHESTRA_URL     target Orchestra (default: staging)
#   ETR_UNIFY_KEY         key to use (default: SHARED_UNIFY_KEY from .env)
#   ETR_SEED / ETR_PORT   fixture data seed / port
#   ETR_USECASES_TSX      path to landing-page src/data/useCases.tsx
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

# A bare run spends real provider money, and the driver takes no arguments, so
# anything that looks like a request for usage is answered here rather than by
# starting a run.
case "${1:-}" in
  -h | --help | help | -\? | usage)
    sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    cat <<'USAGE'

This launcher takes no arguments; configure it with the env vars above.

  ETR_CHECK=true bash .../run_unify.sh   boots everything, spends nothing
  bash .../run_unify.sh                  a real cycle, tens of dollars

Offline, for free: fixture.py --selftest and protocol.py --selftest.
USAGE
    exit 0
    ;;
esac
if [[ $# -gt 0 ]]; then
  echo "error: this launcher takes no arguments (got: $*) — see --help" >&2
  exit 2
fi

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

export ORCHESTRA_URL="${ETR_ORCHESTRA_URL:-https://api.staging.internal.saas.unify.ai/v0}"
export UNIFY_KEY="${ETR_UNIFY_KEY:-${SHARED_UNIFY_KEY:-${UNIFY_KEY:-}}}"
if [[ -z "$UNIFY_KEY" ]]; then
  echo "error: no key — set ETR_UNIFY_KEY, or SHARED_UNIFY_KEY/UNIFY_KEY in .env" >&2
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

# Refuse to spend on a sick provider path. Three cycles were destroyed on
# 2026-08-05 by whitespace bodies and 600s hangs, each discovered only after
# setup was paid for. Costs about a cent. ETR_SKIP_PREFLIGHT=true to bypass.
if [[ "${ETR_SKIP_PREFLIGHT:-}" != "true" ]]; then
  .venv/bin/python -m colleague.tracks.usecases.preflight || exit 1
fi

exec .venv/bin/python -m colleague.tracks.usecases.ecommerce_trading_review.unify "$@"
