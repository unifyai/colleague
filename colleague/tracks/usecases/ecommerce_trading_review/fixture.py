"""Deterministic DTC trading sandbox for the ecommerce-trading-review use case.

Stands in for Shopify, Klaviyo and Meta Ads for an 11-person DTC brand.
Everything is seeded and stdlib-only so a third party reproduces the same
weekly history and the same ground truth forever.

The landing page's brief (the system under test receives it verbatim) flags:
  rule A: repeat purchase rate has fallen three weeks running
  rule B: blended CAC has risen more than 20% against the four-week average
  rule C: flow revenue drops while list size grows

Baselines are constructed so none of those can fire by accident, which for
weekly series means shape rather than bounded noise:

  - Repeat rate follows a fixed four-week up/up/down/down cadence, so a
    baseline decline run is never longer than two.
  - Ad spend and new customers move together within a few percent, holding
    blended CAC inside ±10% of its own four-week average.
  - List size and flow revenue are both monotonically non-decreasing, so
    "flow down while list up" cannot occur without a plant.

Three anomalies are planted in the reported week, one per rule, and the
repeat-rate slide is planted to *begin* two weeks earlier so the reported week
is the first week it qualifies — that makes "caught it the week it became
visible" a measurable claim rather than a comparison against how long a person
would have taken. `selftest` brute-forces a long window to assert no baseline
week trips anything.

Endpoints:
    GET  /health                                  -> {"status": "ok"}
    GET  /shopify/weekly?from=&to=                -> weekly orders/revenue/repeat rate
    GET  /klaviyo/weekly?from=&to=                -> campaign + flow revenue, list size
    GET  /meta/weekly?from=&to=                   -> ad spend + blended CAC
    POST /slack/trading                           -> stores the write-up
    GET  /slack/trading                           -> everything posted

Run standalone for manual poking:
    python -m colleague.tracks.usecases.ecommerce_trading_review.fixture --port 8152
"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

DEFAULT_SEED = 20260802
DEFAULT_PORT = 8152

# How far back the fixture is willing to generate, relative to the anchor.
HISTORY_WEEKS = 60

# ---------------------------------------------------------------------------
# Weeks
# ---------------------------------------------------------------------------


def week_start(d: date) -> date:
    """The Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


def default_anchor(today: date | None = None) -> str:
    """The week a run 'this Monday' reports on: the last complete week."""
    today = today or datetime.now(timezone.utc).date()
    return (week_start(today) - timedelta(days=7)).isoformat()


def shift_weeks(anchor: str, delta: int) -> str:
    return (date.fromisoformat(anchor) + timedelta(weeks=delta)).isoformat()


def _h(seed: int, *parts: Any) -> int:
    payload = ":".join([str(seed), *map(str, parts)]).encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _wobble(base: int, h: int, pct: int) -> int:
    span = pct * 100
    factor = 10000 + (h % (2 * span + 1)) - span
    return max(1, base * factor // 10000)


# ---------------------------------------------------------------------------
# Baseline shape
#
# Week index is measured from the anchor so a given (seed, week) is stable no
# matter which anchor a run uses.
# ---------------------------------------------------------------------------

# Repeat rate as a *level* per week index mod 4, in basis points off the base.
# Walking the cycle gives rise, fall, fall, rise — so a baseline decline run is
# always exactly two, and the value cannot drift because nothing accumulates.
# The gaps (180, 240, 80, 140) all exceed twice REPEAT_JITTER_BP, so jitter can
# never reorder two levels and break that property.
REPEAT_LEVELS = (0, 180, -60, -140)
REPEAT_JITTER_BP = 25

# Cumulative series accumulate from this fixed anchor-relative origin. Summing
# from a moving lower bound would make them sliding windows rather than prefix
# sums, and a sliding window is not monotonic — flow revenue would fall on
# ordinary weeks and trip rule C without a plant.
ORIGIN_WEEK = -HISTORY_WEEKS

REPEAT_BASE_BP = 2850  # 28.5% repeat purchase rate
ORDERS_BASE = 1450
AOV_CENTS = 7200
NEW_SHARE_BP = 6200  # 62% of revenue from new customers
LIST_BASE = 84000
LIST_GROWTH = 900  # subscribers added per week, before wobble
FLOW_RATE_BP = 46  # flow revenue per subscriber, in cents-per-100
CAMPAIGN_BASE_CENTS = 1_850_000
SPEND_BASE_CENTS = 3_100_000


def _week_index(anchor: str, week: str) -> int:
    return (date.fromisoformat(week) - date.fromisoformat(anchor)).days // 7


def _repeat_rate_bp(seed: int, anchor: str, week: str) -> int:
    """Repeat purchase rate: a bounded level per position in the cycle."""
    idx = _week_index(anchor, week)
    level = REPEAT_LEVELS[idx % 4]
    jitter = _h(seed, "repeat", idx) % (2 * REPEAT_JITTER_BP + 1) - REPEAT_JITTER_BP
    return REPEAT_BASE_BP + level + jitter


def _prefix_sum(
    seed: int,
    anchor: str,
    week: str,
    key: str,
    step: int,
    pct: int,
) -> int:
    """Sum of positive increments from a fixed origin, so it never decreases."""
    idx = _week_index(anchor, week)
    total = 0
    for i in range(ORIGIN_WEEK, idx + 1):
        total += _wobble(step, _h(seed, key, i), pct)
    return total


def _list_size(seed: int, anchor: str, week: str) -> int:
    return LIST_BASE + _prefix_sum(seed, anchor, week, "list", LIST_GROWTH, 40)


def _flow_revenue_cents(seed: int, anchor: str, week: str) -> int:
    """Flow revenue grows with the list and never falls on its own.

    A prefix sum of positive increments rather than a rate times the list size:
    a wobbling rate would let flow revenue dip while the list grew, which is
    exactly rule C and would fire without a plant.
    """
    return (LIST_BASE * FLOW_RATE_BP // 100) + _prefix_sum(
        seed,
        anchor,
        week,
        "flow",
        LIST_GROWTH * FLOW_RATE_BP // 100,
        30,
    )


def _new_customers(seed: int, anchor: str, week: str) -> int:
    idx = _week_index(anchor, week)
    orders = _wobble(ORDERS_BASE, _h(seed, "orders", idx), 8)
    repeat_bp = _repeat_rate_bp(seed, anchor, week)
    return max(1, orders * (10000 - repeat_bp) // 10000)


def _spend_cents(seed: int, anchor: str, week: str) -> int:
    """Ad spend moves with new customers, holding CAC in a narrow band."""
    idx = _week_index(anchor, week)
    new = _new_customers(seed, anchor, week)
    per_customer = _wobble(SPEND_BASE_CENTS // 550, _h(seed, "cac", idx), 4)
    return max(1, new * per_customer)


# ---------------------------------------------------------------------------
# Plants
# ---------------------------------------------------------------------------

# The repeat-rate slide starts here, relative to the anchor: three consecutive
# falls ending in the reported week, so the reported week is the first that
# qualifies.
SLIDE_WEEKS = (-2, -1, 0)
SLIDE_STEP_BP = -210

CAC_PLANT_MULTIPLIER = 135  # % of the four-week average
FLOW_PLANT_MULTIPLIER = 80  # % of the previous week


def shopify_week(seed: int, anchor: str, week: str) -> dict[str, Any]:
    idx = _week_index(anchor, week)
    orders = _wobble(ORDERS_BASE, _h(seed, "orders", idx), 8)
    repeat_bp = _repeat_rate_bp(seed, anchor, week)
    if idx in SLIDE_WEEKS:
        # Each slide week sits below the one before it by a fixed step, taken
        # from the pre-slide level so the run of falls is exact.
        base = _repeat_rate_bp(seed, anchor, shift_weeks(anchor, SLIDE_WEEKS[0] - 1))
        repeat_bp = base + SLIDE_STEP_BP * (SLIDE_WEEKS.index(idx) + 1)
    revenue = orders * AOV_CENTS
    new_revenue = revenue * NEW_SHARE_BP // 10000
    return {
        "week_start": week,
        "orders": orders,
        "revenue_cents": revenue,
        "new_customer_revenue_cents": new_revenue,
        "returning_customer_revenue_cents": revenue - new_revenue,
        "repeat_purchase_rate_bp": repeat_bp,
        "new_customers": max(1, orders * (10000 - repeat_bp) // 10000),
    }


def klaviyo_week(seed: int, anchor: str, week: str) -> dict[str, Any]:
    idx = _week_index(anchor, week)
    flow = _flow_revenue_cents(seed, anchor, week)
    if idx == 0:
        prev = _flow_revenue_cents(seed, anchor, shift_weeks(anchor, -1))
        flow = prev * FLOW_PLANT_MULTIPLIER // 100
    return {
        "week_start": week,
        "campaign_revenue_cents": _wobble(
            CAMPAIGN_BASE_CENTS,
            _h(seed, "campaign", idx),
            12,
        ),
        "flow_revenue_cents": flow,
        "list_size": _list_size(seed, anchor, week),
    }


def meta_week(seed: int, anchor: str, week: str) -> dict[str, Any]:
    idx = _week_index(anchor, week)
    spend = _spend_cents(seed, anchor, week)
    new = shopify_week(seed, anchor, week)["new_customers"]
    if idx == 0:
        prior = [
            _spend_cents(seed, anchor, shift_weeks(anchor, d))
            / max(
                1,
                shopify_week(seed, anchor, shift_weeks(anchor, d))["new_customers"],
            )
            for d in (-4, -3, -2, -1)
        ]
        target = sum(prior) / 4 * CAC_PLANT_MULTIPLIER / 100
        spend = int(target * new)
    return {
        "week_start": week,
        "ad_spend_cents": spend,
        "blended_cac_cents": spend // max(1, new),
    }


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------

METRICS = ("repeat_rate", "blended_cac", "flow_revenue")


def rules_tripped(
    seed: int,
    anchor: str,
    week: str,
    *,
    slide_len: int = 3,
    cac_rise: float = 0.20,
) -> list[str]:
    """Which of the brief's rules the given week trips, from served data."""
    tripped = []
    repeats = [
        shopify_week(seed, anchor, shift_weeks(week, -d))["repeat_purchase_rate_bp"]
        for d in range(slide_len, -1, -1)
    ]
    if all(b < a for a, b in zip(repeats, repeats[1:])):
        tripped.append("repeat_rate")

    cac = meta_week(seed, anchor, week)["blended_cac_cents"]
    prior = [
        meta_week(seed, anchor, shift_weeks(week, -d))["blended_cac_cents"]
        for d in (4, 3, 2, 1)
    ]
    if cac > sum(prior) / 4 * (1 + cac_rise):
        tripped.append("blended_cac")

    cur, prev = klaviyo_week(seed, anchor, week), klaviyo_week(
        seed,
        anchor,
        shift_weeks(week, -1),
    )
    if cur["flow_revenue_cents"] < prev["flow_revenue_cents"] and (
        cur["list_size"] > prev["list_size"]
    ):
        tripped.append("flow_revenue")
    return tripped


def expected_flags(
    seed: int,
    anchor: str,
    week: str | None = None,
    **tol: Any,
) -> list[str]:
    return rules_tripped(seed, anchor, week or anchor, **tol)


def selftest(seed: int = DEFAULT_SEED, anchor: str | None = None) -> dict[str, Any]:
    """Assert the reported week trips all three rules and no other week trips any.

    Sweeps the readings a reasonable person might take of "three weeks
    running" and "more than 20%", and brute-forces every baseline week in the
    history window, so a correct system's flag set is the planted set rather
    than an artifact of the series' shape.
    """
    anchor = anchor or default_anchor()
    sweeps = [{}, {"cac_rise": 0.15}, {"cac_rise": 0.25}]
    for tol in sweeps:
        assert sorted(expected_flags(seed, anchor, **tol)) == sorted(METRICS), (
            tol,
            expected_flags(seed, anchor, **tol),
        )
    clean = []
    for d in range(-HISTORY_WEEKS + 6, 0):
        week = shift_weeks(anchor, d)
        tripped = rules_tripped(seed, anchor, week)
        if tripped:
            clean.append((week, tripped))
    assert not clean, clean[:6]
    # The slide must be exactly three long: the week before it must not trip.
    before = shift_weeks(anchor, SLIDE_WEEKS[0] - 1)
    assert "repeat_rate" not in rules_tripped(seed, anchor, before), before
    return {
        "anchor_week": anchor,
        "planted": sorted(METRICS),
        "history_weeks_clean": HISTORY_WEEKS - 6,
        "slide_starts": shift_weeks(anchor, SLIDE_WEEKS[0]),
    }


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------


@dataclass
class PostSink:
    posts: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, body: Any) -> None:
        with self._lock:
            self.posts.append(
                {"received_at": datetime.now(timezone.utc).isoformat(), "body": body},
            )

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.posts)


class _Handler(BaseHTTPRequestHandler):
    seed: int = DEFAULT_SEED
    anchor: str = ""
    sink: PostSink

    def _send_json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _range(self, query: dict[str, list[str]]) -> list[str] | None:
        frm, to = query.get("from", [None])[0], query.get("to", [None])[0]
        if not frm or not to:
            return None
        try:
            start, end = week_start(date.fromisoformat(frm)), week_start(
                date.fromisoformat(to),
            )
        except ValueError:
            return None
        weeks, cur = [], start
        while cur <= end and len(weeks) <= HISTORY_WEEKS + 8:
            weeks.append(cur.isoformat())
            cur += timedelta(days=7)
        return weeks

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json(200, {"status": "ok"})
            return
        if parsed.path == "/slack/trading":
            self._send_json(200, self.sink.snapshot())
            return
        builders = {
            "/shopify/weekly": shopify_week,
            "/klaviyo/weekly": klaviyo_week,
            "/meta/weekly": meta_week,
        }
        build = builders.get(parsed.path)
        if build is None:
            self._send_json(404, {"error": f"unknown path {parsed.path}"})
            return
        weeks = self._range(parse_qs(parsed.query))
        if weeks is None:
            self._send_json(
                400,
                {"error": "from and to query params required, YYYY-MM-DD"},
            )
            return
        self._send_json(200, [build(self.seed, self.anchor, w) for w in weeks])

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path != "/slack/trading":
            self._send_json(404, {"error": f"unknown path {parsed.path}"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode() or "null")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "body must be valid JSON"})
            return
        self.sink.add(body)
        self._send_json(200, {"status": "posted", "channel": "#trading"})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


class FixtureServer:
    """In-process fixture server bound to 127.0.0.1."""

    def __init__(
        self,
        *,
        seed: int = DEFAULT_SEED,
        port: int = DEFAULT_PORT,
        anchor: str | None = None,
    ) -> None:
        self.seed = seed
        self.anchor = anchor or default_anchor()
        self.sink = PostSink()
        handler = type(
            "BoundHandler",
            (_Handler,),
            {"seed": seed, "anchor": self.anchor, "sink": self.sink},
        )
        self._handler = handler
        self._server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="etr-fixture-server",
            daemon=True,
        )

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def set_anchor(self, anchor: str) -> None:
        self.anchor = anchor
        self._handler.anchor = anchor

    def start(self) -> "FixtureServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--anchor",
        default=None,
        help="reported week start, YYYY-MM-DD",
    )
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        print(json.dumps(selftest(args.seed, args.anchor), indent=2))
        return
    server = FixtureServer(seed=args.seed, port=args.port, anchor=args.anchor).start()
    print(
        f"Fixture on {server.base_url} (seed={args.seed}, week={server.anchor}). "
        "Ctrl-C to stop.",
    )
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
