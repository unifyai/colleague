"""A ledger behind an expensive authentication step.

Authenticating is deliberately slow and deliberately observable. That makes
the cost of a cold restart visible as a fact rather than an inference: if the
second request re-authenticates, the fixture saw it do so.

This is the cheapest possible stand-in for the real thing, which is any piece
of working state a task built and did not write down — a client object, a
parsed dataframe, a mapping worked out from four API calls. The fixture
cannot observe those, but it can observe the one that costs a round trip.
"""

from __future__ import annotations

from typing import Any

from colleague.harness.fixture_server import FixtureServer, Request, stable_hash

DEFAULT_SEED = 20260801
DEFAULT_PORT = 8142

VENDORS = (
    "Halden Freight",
    "Trellis Packaging",
    "Cardinal Logistics",
    "Ostrava Metals",
    "Bergen Chemical",
    "Kestrel Tooling",
)
MONTHS = ("january", "february")


def entries_for(seed: int, month: str) -> list[dict[str, Any]]:
    """Deterministic spend rows, so the right answer is recomputable."""
    rows = []
    for i, vendor in enumerate(VENDORS):
        h = stable_hash(seed, month, vendor, i)
        for n in range(3):
            rows.append(
                {
                    "vendor": vendor,
                    "amount": 500 + (stable_hash(seed, month, vendor, n) % 9500),
                },
            )
        del h
    return rows


def top_vendors(seed: int, month: str, n: int = 3) -> list[str]:
    totals: dict[str, int] = {}
    for row in entries_for(seed, month):
        totals[row["vendor"]] = totals.get(row["vendor"], 0) + row["amount"]
    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    return [v for v, _ in ranked[:n]]


def build(*, seed: int = DEFAULT_SEED, port: int = DEFAULT_PORT) -> FixtureServer:
    fx = FixtureServer(seed=seed, port=port)
    fx.state["token"] = f"tok-{stable_hash(seed, 'token') % 10**8:08d}"

    def auth(r: Request) -> tuple[int, Any]:
        n = r.server.waypoints.reach("auth")
        r.server.recorder.record("auth", {"attempt": n})
        return 200, {"token": r.server.state["token"], "expires_in": 86400}

    def ledger(r: Request) -> tuple[int, Any]:
        if r.q("token") != r.server.state["token"]:
            return 401, {"error": "missing or invalid token; POST /auth first"}
        month = (r.q("month") or "").lower()
        if month not in MONTHS:
            return 400, {"error": f"month must be one of {list(MONTHS)}"}
        r.server.waypoints.reach(f"ledger_{month}")
        r.server.recorder.record("ledger", {"month": month})
        return 200, entries_for(r.server.seed, month)

    def report(r: Request) -> tuple[int, Any]:
        r.server.waypoints.reach("report")
        r.server.recorder.record("report", r.body)
        return 200, {"status": "received"}

    # Authentication is the expensive step, and staying authenticated is
    # the thing a persistent session buys.
    fx.route("POST", "/auth", auth, hold_ms=1500)
    fx.route("GET", "/ledger", ledger)
    fx.route("POST", "/report", report)
    return fx


API_DOC = """\
Ledger API at {base_url}:
  POST {base_url}/auth                            -> {{"token": "<str>"}}  (slow)
  GET  {base_url}/ledger?month=<name>&token=<tok> -> [{{vendor, amount}}]
  POST {base_url}/report                          -> body {{"month": "<name>", "top_vendors": ["<name>", ...]}}\
"""
