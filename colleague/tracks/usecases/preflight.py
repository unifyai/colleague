"""Cheap health gate to run before paying for a cycle.

A cycle costs tens of dollars and takes over an hour, and on 2026-08-05 three
of them were destroyed by a provider path that was answering in whitespace or
not at all — each discovered only after setup had been paid for. This checks
the same path for about a cent, and refuses the run instead.

What it proves, in the order that matters:

1. **Credit.** The Unify account's own balance is what gates an LLM call, not
   the provider's. Auto-topup fires on its own schedule rather than when a run
   needs it, so a cycle that starts thin can die mid-flight with setup already
   spent.
2. **The provider answers, and answers correctly.** Both the actor's reasoning
   model and the cheap model distilled functions pick for prose, asked for the
   same `json_object` shape a real narrative call uses. A body of whitespace
   counts as a failure, which is exactly what killed two cycles: valid HTTP,
   unparseable content.
3. **It answers promptly.** A model that took 2.2s when healthy waited 601s
   during the bad window. Latency far above the healthy baseline means the path
   is degrading even when it eventually responds.

Deliberately not a unify/unillm call: this tests the provider leg directly,
which is the leg that failed, and it stays stdlib-only so it cannot itself be
broken by the stack under test.

    python -m colleague.tracks.usecases.preflight            # gate a run
    python -m colleague.tracks.usecases.preflight --topup    # grant staging credit first
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
STAGING_ORCHESTRA = "https://api.staging.internal.saas.unify.ai/v0"

# The actor's reasoning model, and the cheap one distilled functions have
# chosen for prose. Both have failed on us; both are worth a cent to check.
DEFAULT_MODELS = ("openai/gpt-5.6-sol", "openai/gpt-5.4-mini")

# A cycle has cost $30-39 each time it completed. Starting below this risks
# dying mid-flight with setup already paid for.
DEFAULT_CREDIT_FLOOR = 45.0

# Healthy is single-digit seconds. The bad window sat at 601s. Anything beyond
# this is degrading even if it does eventually answer.
LATENCY_CEILING_S = 90.0

PROBE_PROMPT = (
    "Return one JSON object with exactly three string fields: what_happened, "
    "why, what_wed_change. One short sentence each."
)
PROBE_FIELDS = ("what_happened", "why", "what_wed_change")


def credits(api_key: str, orchestra_url: str = STAGING_ORCHESTRA) -> float:
    req = urllib.request.Request(
        f"{orchestra_url}/credits",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return float(json.load(response)["credits"])


def topup(api_key: str, amount: float, orchestra_url: str = STAGING_ORCHESTRA) -> dict:
    """Grant staging credit. No charge, no card, hard-gated off in production."""
    req = urllib.request.Request(
        f"{orchestra_url}/credits/topup",
        data=json.dumps({"amount": amount}).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def probe(model: str, api_key: str) -> dict:
    """One small json_object call, timed and validated."""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": PROBE_PROMPT}],
        "response_format": {"type": "json_object"},
        "max_tokens": 300,
    }
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=LATENCY_CEILING_S) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "model": model,
            "ok": False,
            "seconds": round(time.monotonic() - started, 1),
            "problem": f"{type(exc).__name__}: {exc}",
        }
    elapsed = time.monotonic() - started
    choice = (payload.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content")
    result = {
        "model": model,
        "seconds": round(elapsed, 1),
        "provider": payload.get("provider"),
        "finish": choice.get("finish_reason"),
    }
    if not content or not str(content).strip():
        # The failure that destroyed two cycles: HTTP 200, body is whitespace.
        return {**result, "ok": False, "problem": "empty or whitespace content"}
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        return {**result, "ok": False, "problem": f"content is not JSON: {exc}"}
    missing = [f for f in PROBE_FIELDS if not isinstance(parsed.get(f), str)]
    if missing:
        return {**result, "ok": False, "problem": f"missing fields: {missing}"}
    if elapsed > LATENCY_CEILING_S:
        return {**result, "ok": False, "problem": f"slower than {LATENCY_CEILING_S}s"}
    return {**result, "ok": True, "problem": None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--credit-floor", type=float, default=DEFAULT_CREDIT_FLOOR)
    parser.add_argument(
        "--topup",
        action="store_true",
        help="grant staging credit up to the floor before checking",
    )
    parser.add_argument("--orchestra-url", default=STAGING_ORCHESTRA)
    args = parser.parse_args()

    provider_key = os.environ.get("OPENROUTER_API_KEY")
    unify_key = os.environ.get("SHARED_UNIFY_KEY") or os.environ.get("UNIFY_KEY")
    if not provider_key or not unify_key:
        print("[preflight] FAIL: need OPENROUTER_API_KEY and a Unify key in the env")
        return 2

    balance = credits(unify_key, args.orchestra_url)
    print(f"[preflight] credit balance ${balance:.2f} (floor ${args.credit_floor:.2f})")
    while args.topup and balance < args.credit_floor:
        before = balance
        result = topup(unify_key, 100.0, args.orchestra_url)
        balance = float(result["current_credits"])
        print(f"[preflight] topped up: ${before:.2f} -> ${balance:.2f}")
        if balance <= before:
            print("[preflight] FAIL: top-up did not raise the balance")
            return 1

    failures = []
    if balance < args.credit_floor:
        failures.append(
            f"balance ${balance:.2f} is below the ${args.credit_floor:.2f} a cycle needs "
            f"(pass --topup, or raise the floor if you know the cycle is cheaper)",
        )

    for model in [m for m in args.models.split(",") if m]:
        outcome = probe(model, provider_key)
        state = "ok " if outcome["ok"] else "FAIL"
        print(
            f"[preflight] {state} {outcome['model']:24} {outcome['seconds']:6.1f}s "
            f"provider={outcome.get('provider')} {outcome['problem'] or ''}",
        )
        if not outcome["ok"]:
            failures.append(f"{outcome['model']}: {outcome['problem']}")

    if failures:
        print("\n[preflight] REFUSING the run:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("[preflight] path is healthy; a cycle is worth starting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
