#!/usr/bin/env bash
# Launcher for the policy propagation benchmark, Unify arm (staging Orchestra).
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

export ORCHESTRA_URL="${PP_ORCHESTRA_URL:-https://api.staging.internal.saas.unify.ai/v0}"
export UNIFY_KEY="${PP_UNIFY_KEY:-${SHARED_UNIFY_KEY:-${UNIFY_KEY:-}}}"
if [[ -z "$UNIFY_KEY" ]]; then
  echo "error: no key — set PP_UNIFY_KEY, or SHARED_UNIFY_KEY/UNIFY_KEY in .env" >&2
  exit 1
fi

export PYTHONUNBUFFERED=1
export UNILLM_CACHE=false
export TEST=true
unset ASSISTANT_ID
export TQDM_DISABLE=1
for m in CONTACT TRANSCRIPT TASK KNOWLEDGE GUIDANCE SECRET WEB FILE DATA FUNCTION CONVERSATION MEMORY CONFIG; do
  export "UNITY_${m}_IMPL=real"
done

probe_url="$ORCHESTRA_URL/projects"
[[ "$ORCHESTRA_URL" != */v0 ]] && probe_url="${ORCHESTRA_URL%/}/v0/projects"
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
  -H "Authorization: Bearer $UNIFY_KEY" "$probe_url" || true)
if [[ "$code" != "200" ]]; then
  echo "error: auth probe against $probe_url returned HTTP $code" >&2
  exit 1
fi
echo "[run_unify.sh] auth OK against $ORCHESTRA_URL"

exec .venv/bin/python -m colleague.tracks.standing.policy_propagation.unify "$@"
