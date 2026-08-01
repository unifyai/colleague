#!/usr/bin/env bash
set -euo pipefail

# Trigger a benchmark sweep on GitHub Actions and hand back the run URL.
#
# The point is not to wait. A full sweep is dozens of shards running in
# parallel on someone else's machines; this fires it and returns.
#
# Usage:
#   scripts/cloud_run.sh                              # all tracks, unify arm
#   scripts/cloud_run.sh --arms all                   # all tracks, all arms
#   scripts/cloud_run.sh --tracks custody,attribution --arms unify,openclaw
#   scripts/cloud_run.sh --arms all --repeat 5        # distributions, not points
#   scripts/cloud_run.sh --dry-run                    # print the shard list only
#   scripts/cloud_run.sh --watch                      # follow to completion

REPO="${COLLEAGUE_REPO:-unifyai/colleague}"
WORKFLOW="benchmark.yml"

TRACKS="all"
ARMS="unify"
REPEAT=1
MAX_PARALLEL=20
TIMEOUT=45
NO_SHARD=false
WATCH=false
DRY_RUN=false
CONFIRM=""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$(cd "$SCRIPT_DIR/.." && pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tracks)       TRACKS="$2"; shift 2 ;;
    --arms)         ARMS="$2"; shift 2 ;;
    --repeat)       REPEAT="$2"; shift 2 ;;
    --max-parallel) MAX_PARALLEL="$2"; shift 2 ;;
    --timeout)      TIMEOUT="$2"; shift 2 ;;
    --no-shard)     NO_SHARD=true; shift ;;
    --watch)        WATCH=true; shift ;;
    --dry-run)      DRY_RUN=true; shift ;;
    --confirm)      CONFIRM="SPEND_OK"; shift ;;
    -h|--help)      sed -n '3,20p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

python3 -c 'import sys' 2>/dev/null || { echo "python3 required" >&2; exit 1; }

# Show what will be spent before spending it.
SHARDS=$(PYTHONPATH=. python3 -m colleague.plan \
  --tracks "$TRACKS" --arms "$ARMS" --repeat "$REPEAT" \
  ${NO_SHARD:+$([[ "$NO_SHARD" == true ]] && echo --no-shard)} \
  | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["include"]))')

echo "tracks=$TRACKS  arms=$ARMS  repeat=$REPEAT"
echo "$SHARDS shards, up to $MAX_PARALLEL at a time"

if [[ "$DRY_RUN" == true ]]; then
  PYTHONPATH=. python3 -m colleague.plan \
    --tracks "$TRACKS" --arms "$ARMS" --repeat "$REPEAT" --pretty
  exit 0
fi

# The workflow enforces this too; asking here means the answer arrives before
# a round trip rather than after one.
if (( SHARDS > 40 )) && [[ -z "$CONFIRM" ]]; then
  echo
  echo "$SHARDS shards is a large sweep and every one makes real LLM calls."
  echo "Re-run with --confirm to proceed."
  exit 1
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "note: uncommitted changes are not included; CI runs $BRANCH as pushed" >&2
fi

TRIGGERED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
gh workflow run "$WORKFLOW" \
  --repo "$REPO" \
  --ref "$BRANCH" \
  -f tracks="$TRACKS" \
  -f arms="$ARMS" \
  -f repeat="$REPEAT" \
  -f max_parallel="$MAX_PARALLEL" \
  -f timeout_minutes="$TIMEOUT" \
  -f no_shard="$NO_SHARD" \
  -f confirm_spend="$CONFIRM"

echo -n "waiting for the run to appear"
RUN_ID=""
for _ in $(seq 1 30); do
  RUN_ID=$(gh run list --repo "$REPO" --workflow "$WORKFLOW" --branch "$BRANCH" \
    --limit 5 --json databaseId,createdAt \
    --jq "[.[] | select(.createdAt >= \"$TRIGGERED_AT\")] | first | .databaseId" 2>/dev/null || true)
  [[ -n "$RUN_ID" && "$RUN_ID" != "null" ]] && break
  echo -n "."
  sleep 2
done
echo

if [[ -z "$RUN_ID" || "$RUN_ID" == "null" ]]; then
  echo "triggered, but the run did not appear in time — check:"
  echo "  gh run list --repo $REPO --workflow $WORKFLOW"
  exit 0
fi

echo "https://github.com/$REPO/actions/runs/$RUN_ID"
echo
echo "results:  gh run download $RUN_ID --repo $REPO --name benchmark-summary"

if [[ "$WATCH" == true ]]; then
  gh run watch "$RUN_ID" --repo "$REPO" --exit-status
fi
