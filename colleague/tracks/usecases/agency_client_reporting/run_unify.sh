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

# A bare run spends real provider money (~$30 for a full cycle), and the driver
# takes no arguments, so anything that looks like a request for usage is
# answered here rather than by starting a run.
case "${1:-}" in
  -h | --help | help | -\? | usage)
    sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    cat <<'USAGE'

This launcher takes no arguments; configure it with the env vars above.

  ACR_CHECK=true bash .../run_unify.sh   boots everything, spends nothing
  bash .../run_unify.sh                  a real cycle, ~$30 of provider spend

Offline, for free: fixture.py --selftest, protocol.py --selftest, and
replay_entrypoint.py (replays a stored entrypoint against the fixture with the
narrative call stubbed).
USAGE
    exit 0
    ;;
esac
if [[ $# -gt 0 ]]; then
  echo "error: this launcher takes no arguments (got: $*) — see --help" >&2
  exit 2
fi

cd "$REPO_ROOT"

# Two runs cannot share this machine: both bind the fixture port, and the
# second would score the first's deliveries. On 2026-08-05 a cycle was launched
# while another session was mid-edit in this tree, which is how this guard came
# to exist.
if [[ "${ACR_CHECK:-}" != "true" ]]; then
  fixture_port="${ACR_PORT:-8151}"
  if lsof -nP -iTCP:"$fixture_port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "error: something is already listening on 127.0.0.1:$fixture_port —" >&2
    echo "       another run or a manual fixture is live. Wait for it, or set" >&2
    echo "       ACR_PORT to a free port." >&2
    exit 3
  fi
  if pgrep -f "agency_client_reporting.unify" >/dev/null 2>&1; then
    echo "error: an agency_client_reporting driver is already running." >&2
    exit 3
  fi

  # A figure may only go on a page if it can be re-derived from a commit, so a
  # cycle metered against uncommitted fixture, protocol or driver code produces
  # nothing transcribable — and code can change underneath a 45-minute setup.
  track_rel="colleague/tracks/usecases/agency_client_reporting"
  dirty="$(git status --porcelain -- "$track_rel" 2>/dev/null | grep -v "^.. $track_rel/results/" || true)"
  if [[ -n "$dirty" ]]; then
    echo "error: uncommitted changes under $track_rel:" >&2
    echo "$dirty" >&2
    echo "       Commit them first — a run metered against an uncommitted tree" >&2
    echo "       has no commit to transcribe from. ACR_ALLOW_DIRTY=true to override." >&2
    [[ "${ACR_ALLOW_DIRTY:-}" == "true" ]] || exit 3
    echo "       (ACR_ALLOW_DIRTY=true set; continuing, figures are not page-eligible)" >&2
  fi
fi

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
