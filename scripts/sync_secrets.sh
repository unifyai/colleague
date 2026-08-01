#!/usr/bin/env bash
set -euo pipefail

# Push the credentials a benchmark sweep needs from local env files into the
# repo's Actions secrets, without a human copy-pasting them.
#
# Values are never printed. Each one is reported by name, source file, and a
# short SHA-256 fingerprint, which is enough to confirm the right value moved
# and useless for recovering it. Values reach `gh` over stdin rather than argv,
# so they never appear in the process table.
#
# Usage:
#   scripts/sync_secrets.sh                    # from ~/unify/.env, then ./.env
#   scripts/sync_secrets.sh --dry-run          # report what would be set
#   scripts/sync_secrets.sh --from /path/.env  # additional source, later wins
#
# There is deliberately no flag to mirror `gh auth token`. A developer's CLI
# token typically carries repo, admin:org and delete_repo, and a secret on a
# public repo is readable by any workflow anyone with write access can add —
# so that trade is a broad org credential in exchange for cloning two public
# harness repos. If a private harness repo ever needs one, mint a fine-grained
# token scoped to read-only contents on exactly those repos and set it by hand:
#
#   gh secret set HARNESS_TOKEN --repo unifyai/colleague

REPO="${COLLEAGUE_REPO:-unifyai/colleague}"
DRY_RUN=false
SOURCES=()

# Fall back to the staging backend rather than whatever a local checkout is
# pointed at — a localhost ORCHESTRA_URL is correct locally and useless in CI.
DEFAULT_ORCHESTRA_URL="https://api.staging.internal.saas.unify.ai/v0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from)           SOURCES+=("$2"); shift 2 ;;
    --dry-run)        DRY_RUN=true; shift ;;
    --repo)           REPO="$2"; shift 2 ;;
    -h|--help)        sed -n '3,22p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ ${#SOURCES[@]} -eq 0 ]]; then
  SOURCES=("$HOME/unify/.env" "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.env")
fi

command -v gh >/dev/null || { echo "gh CLI required" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "run: gh auth login" >&2; exit 1; }

# ---------------------------------------------------------------------------

fingerprint() {
  # Short, non-reversible identity for a value, so a human can confirm the
  # right thing moved without the value being shown or logged.
  printf '%s' "$1" | shasum -a 256 | cut -c1-8
}

# Sets VALUE and VALUE_SRC rather than echoing, because command substitution
# runs in a subshell and the source file would not survive it.
read_key() {
  local key="$1" file line
  VALUE=""
  VALUE_SRC=""
  for file in "${SOURCES[@]}"; do
    [[ -f "$file" ]] || continue
    line=$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}=" "$file" | tail -1 || true)
    [[ -z "$line" ]] && continue
    line="${line#*=}"
    line="${line%%$'\r'}"
    # Strip surrounding quotes; leave inner content untouched.
    if [[ "$line" =~ ^\"(.*)\"$ ]] || [[ "$line" =~ ^\'(.*)\'$ ]]; then
      line="${BASH_REMATCH[1]}"
    fi
    # Last definition wins, matching how a shell would source these in order.
    VALUE="$line"
    VALUE_SRC="$file"
  done
}

set_secret() {
  local name="$1" value="$2" src="$3"
  if [[ -z "$value" ]]; then
    printf '  %-22s %s\n' "$name" "MISSING — not found in any source"
    MISSING+=("$name")
    return
  fi
  printf '  %-22s %s  (sha256:%s, from %s)\n' \
    "$name" "secret" "$(fingerprint "$value")" "$(basename "$src")"
  if [[ "$DRY_RUN" == false ]]; then
    # stdin, not --body: an argv value is visible in `ps` for the call's life.
    printf '%s' "$value" | gh secret set "$name" --repo "$REPO" >/dev/null
  fi
}

set_variable() {
  local name="$1" value="$2"
  if [[ -z "$value" ]]; then
    printf '  %-22s %s\n' "$name" "MISSING"
    MISSING+=("$name")
    return
  fi
  # Variables are not secret and are shown, which is the point of them.
  printf '  %-22s %s  = %s\n' "$name" "variable" "$value"
  if [[ "$DRY_RUN" == false ]]; then
    gh variable set "$name" --repo "$REPO" --body "$value" >/dev/null
  fi
}

# ---------------------------------------------------------------------------

echo "repo:    $REPO"
echo "sources: ${SOURCES[*]}"
[[ "$DRY_RUN" == true ]] && echo "mode:    dry run, nothing will be written"
echo

MISSING=()
VALUE=""
VALUE_SRC=""

echo "Secrets"
read_key OPENROUTER_API_KEY
set_secret OPENROUTER_API_KEY "$VALUE" "$VALUE_SRC"

read_key UNIFY_KEY
set_secret UNIFY_KEY "$VALUE" "$VALUE_SRC"

echo
echo "Variables"
read_key ORCHESTRA_URL
ORCHESTRA="$VALUE"
if [[ -z "$ORCHESTRA" || "$ORCHESTRA" == *"127.0.0.1"* || "$ORCHESTRA" == *"localhost"* ]]; then
  [[ -n "$ORCHESTRA" ]] && echo "  note: local ORCHESTRA_URL ignored; CI cannot reach it"
  ORCHESTRA="$DEFAULT_ORCHESTRA_URL"
fi
set_variable ORCHESTRA_URL "$ORCHESTRA"
set_variable COLLEAGUE_PROJECT "${COLLEAGUE_PROJECT:-Benchmarks}"

# Comparison-arm harnesses. Defaults are best guesses; an arm whose checkout
# fails is recorded as unavailable rather than failing the sweep.
set_variable OPENCLAW_REPO "${OPENCLAW_REPO:-openclaw/openclaw}"
set_variable OPENCODE_REPO "${OPENCODE_REPO:-sst/opencode}"
set_variable HERMES_REPO   "${HERMES_REPO:-unifyai/hermes-agent}"

echo
if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "missing: ${MISSING[*]}"
  echo "add them to one of the source files, or pass --from <file>"
fi

if [[ "$DRY_RUN" == true ]]; then
  echo "dry run complete — nothing written"
  exit 0
fi

echo "Configured on $REPO:"
gh secret list --repo "$REPO" 2>/dev/null | sed 's/^/  secret   /' || true
gh variable list --repo "$REPO" 2>/dev/null | sed 's/^/  variable /' || true

cat <<'NOTE'

Note: this repo is public. Secrets are encrypted and are never exposed to
workflows triggered from forks, and the Benchmark workflow is dispatch-only
with no pull_request trigger — so the exposure is to accounts with write
access, which is the same set that could read them anyway.
NOTE
