"""Deterministic ad-platform sandbox for the agency-client-reporting use case.

Stands in for Google Ads, Meta Ads and Google Analytics for a 14-client
performance agency. Everything is seeded and stdlib-only so any third party
can reproduce the exact same campaign data and ground truth.

The landing page's brief (the system under test receives it verbatim) flags:
  rule A: spend held steady or rose while conversions fell by more than a third
  rule B: cost per conversion moved more than 40%
  rule C: spent over $200 and converted nothing

Baseline campaigns are generated inside safe zones (month-over-month wobble
bounded well away from every rule threshold), then nine anomalies are planted
across six clients in the anchor month pair. Ground truth is recomputed from
the served data, and `selftest` asserts the derived flag set equals the
planted intent under a sweep of tolerance choices — so a correct system's
flag list is exactly the planted set, never an artifact of noise.

One client (c07) has an expired Meta Ads connection: its /meta_ads endpoint
returns 401 AUTH_EXPIRED. What the system does with that client is measured,
not prescribed.

Endpoints:
    GET  /health                                    -> {"status": "ok"}
    GET  /clients                                   -> the agency's client list
    GET  /clients/{id}/google_ads?month=YYYY-MM     -> campaign rows for the month
    GET  /clients/{id}/meta_ads?month=YYYY-MM       -> campaign rows (401 for c07)
    GET  /clients/{id}/analytics?month=YYYY-MM      -> sessions/conversions/revenue rows
    POST /deliveries                                -> stores the JSON body
    GET  /deliveries                                -> all stored deliveries (with receipts)

Run standalone for manual poking:
    python -m colleague.tracks.usecases.agency_client_reporting.fixture --port 8151
"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

DEFAULT_SEED = 20260801
DEFAULT_PORT = 8151

# ---------------------------------------------------------------------------
# The agency's book of clients (fictional; ids are the stable keys)
# ---------------------------------------------------------------------------

CLIENTS: list[dict[str, str]] = [
    {"client_id": "c01", "name": "Bluepine Outdoor Co.", "vertical": "ecommerce"},
    {"client_id": "c02", "name": "Harbor & Oak Furniture", "vertical": "ecommerce"},
    {"client_id": "c03", "name": "Verra Skincare", "vertical": "ecommerce"},
    {"client_id": "c04", "name": "Northgate Dental Group", "vertical": "local services"},
    {"client_id": "c05", "name": "Brightside HVAC", "vertical": "local services"},
    {"client_id": "c06", "name": "Fernway Coffee Roasters", "vertical": "ecommerce"},
    {"client_id": "c07", "name": "Atlas Legal Partners", "vertical": "professional services"},
    {"client_id": "c08", "name": "Cobalt Cycling", "vertical": "ecommerce"},
    {"client_id": "c09", "name": "Meridian Software", "vertical": "b2b saas"},
    {"client_id": "c10", "name": "Sunhaven Resorts", "vertical": "travel"},
    {"client_id": "c11", "name": "Pallas Home Security", "vertical": "consumer services"},
    {"client_id": "c12", "name": "Quill & Willow Stationery", "vertical": "ecommerce"},
    {"client_id": "c13", "name": "Redrock Auto Glass", "vertical": "local services"},
    {"client_id": "c14", "name": "Lanternfield Tutoring", "vertical": "education"},
]

# Clients whose analytics property has revenue (ecommerce-style) tracking.
REVENUE_TRACKED = {"c01", "c03", "c06", "c09", "c12"}

# The one account whose Meta Ads OAuth connection has expired.
BROKEN_META_CLIENT = "c07"

GOOGLE_CAMPAIGN_POOL = (
    "Search - Brand",
    "Search - Non-brand",
    "Search - Competitors",
    "PMax - Catalog",
    "Display - Retargeting",
    "YouTube - Prospecting",
    "Search - Local",
    "Demand Gen - Trial",
)
META_CAMPAIGN_POOL = (
    "Prospecting - Lookalike",
    "Prospecting - Broad",
    "Retargeting - 30d",
    "Retargeting - Cart",
    "Advantage+ - Catalog",
    "Stories - Offer",
    "Reels - UGC",
)

# ---------------------------------------------------------------------------
# Planted anomalies: nine campaigns across six clients in the anchor month
# pair. Rule letters name the *primary* rule each plant exists to trip; a
# rule-A collapse also moves cost per conversion, so ground truth records
# every rule a campaign trips, and the flag set is compared campaign-wise.
# ---------------------------------------------------------------------------

PLANTS: dict[str, list[tuple[str, str]]] = {
    "c02": [("google_ads", "A")],
    "c04": [("meta_ads", "B"), ("google_ads", "C")],
    "c05": [("google_ads", "C")],
    "c09": [("google_ads", "A"), ("meta_ads", "B")],
    "c11": [("meta_ads", "A"), ("google_ads", "C")],
    "c13": [("google_ads", "B")],
}

# Rule-B plants swing cost per conversion in a fixed direction per client so
# the narrative isn't three copies of the same failure.
RULE_B_DIRECTION = {"c04": "worse", "c09": "worse", "c13": "better"}


def _h(seed: int, *parts: Any) -> int:
    """Stable 64-bit hash of the seed plus any parts."""
    payload = ":".join([str(seed), *map(str, parts)]).encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _wobble(base: int, h: int, pct: int) -> int:
    """base scaled by a hash-derived factor in [1 - pct%, 1 + pct%]."""
    span = pct * 100  # basis points
    factor = 10000 + (h % (2 * span + 1)) - span
    return max(1, base * factor // 10000)


def month_str(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def prev_month(m: str) -> str:
    year, mon = map(int, m.split("-"))
    return month_str(date(year - 1, 12, 1) if mon == 1 else date(year, mon - 1, 1))


def default_anchor(today: date | None = None) -> str:
    """The month a report run 'this month' covers: the last full month."""
    return prev_month(month_str(today or datetime.now(timezone.utc).date()))


# ---------------------------------------------------------------------------
# Baseline generation (safe zones)
#
# Each campaign has a stable base level; a month's value is the base times a
# small month-keyed wobble. Spend wobbles ±6% and conversions ±6% with base
# conversions >= 30, so month-over-month conversion ratios stay within
# ~[0.85, 1.17] (rule A needs < 0.667) and cost-per-conversion ratios within
# ~[0.76, 1.32] including integer rounding (rule B needs beyond 0.60/1.40).
# Every baseline campaign converts, so rule C can only come from a plant.
# `selftest` verifies all of this by brute force rather than trusting the
# algebra.
# ---------------------------------------------------------------------------


def campaign_defs(seed: int, client_id: str, platform: str) -> list[dict[str, str]]:
    pool = GOOGLE_CAMPAIGN_POOL if platform == "google_ads" else META_CAMPAIGN_POOL
    lo, hi = (3, 6) if platform == "google_ads" else (2, 5)
    n = lo + _h(seed, client_id, platform, "count") % (hi - lo + 1)
    offset = _h(seed, client_id, platform, "offset") % len(pool)
    prefix = "g" if platform == "google_ads" else "m"
    return [
        {
            "campaign_id": f"{client_id}-{prefix}{i + 1}",
            "campaign": pool[(offset + i) % len(pool)],
        }
        for i in range(n)
    ]


def _base_levels(seed: int, client_id: str, platform: str, idx: int) -> dict[str, int]:
    hs = _h(seed, client_id, platform, idx, "spend")
    hc = _h(seed, client_id, platform, idx, "conv")
    spend_cents = 15000 + hs % 785001  # $150 .. $8000 / month
    conversions = 30 + hc % 370  # >= 30 keeps integer wobble far from thresholds
    cpm_cents = 400 + _h(seed, client_id, platform, idx, "cpm") % 2101
    ctr_bp = 50 + _h(seed, client_id, platform, idx, "ctr") % 551  # 0.5% .. 6%
    return {
        "spend_cents": spend_cents,
        "conversions": conversions,
        "cpm_cents": cpm_cents,
        "ctr_bp": ctr_bp,
    }


def baseline_stats(
    seed: int,
    client_id: str,
    platform: str,
    month: str,
) -> list[dict[str, Any]]:
    rows = []
    for idx, defn in enumerate(campaign_defs(seed, client_id, platform)):
        base = _base_levels(seed, client_id, platform, idx)
        spend = _wobble(
            base["spend_cents"],
            _h(seed, client_id, platform, idx, month, "spend"),
            6,
        )
        conversions = _wobble(
            base["conversions"],
            _h(seed, client_id, platform, idx, month, "conv"),
            6,
        )
        impressions = spend * 1000 // base["cpm_cents"]
        clicks = impressions * base["ctr_bp"] // 10000
        rows.append(
            {
                **defn,
                "month": month,
                "spend_cents": spend,
                "impressions": impressions,
                "clicks": clicks,
                "conversions": conversions,
            },
        )
    return rows


# ---------------------------------------------------------------------------
# Plants
# ---------------------------------------------------------------------------


def _plant_slots(seed: int, client_id: str) -> dict[tuple[str, int], str]:
    """Map (platform, campaign index) -> rule for one client's plants.

    Plants occupy the highest campaign indices of their platform so two
    plants on one client's platform never collide with index 0 baselines.
    """
    slots: dict[tuple[str, int], str] = {}
    used: dict[str, int] = {}
    for platform, rule in PLANTS.get(client_id, []):
        n = len(campaign_defs(seed, client_id, platform))
        used[platform] = used.get(platform, 0) + 1
        slots[(platform, n - used[platform])] = rule
    return slots


def stats(
    seed: int,
    client_id: str,
    platform: str,
    month: str,
    anchor: str,
) -> list[dict[str, Any]]:
    """Campaign rows for one client/platform/month, plants applied.

    Rules A and B override only the anchor month (the reported month), scaled
    from the served previous-month row so the planted relationship is exact.
    Rule C (a burner that never converts) overrides both months of the pair.
    """
    rows = baseline_stats(seed, client_id, platform, month)
    month_a = prev_month(anchor)
    if month not in (anchor, month_a):
        return rows
    for (plat, idx), rule in _plant_slots(seed, client_id).items():
        if plat != platform or idx >= len(rows):
            continue
        hp = _h(seed, client_id, platform, idx, "plant")
        if rule == "C":
            spend_a = 24000 + hp % 56001  # $240 .. $800
            row = rows[idx]
            row["conversions"] = 0
            row["spend_cents"] = (
                spend_a if month == month_a else _wobble(spend_a, hp >> 8, 10)
            )
            row["impressions"] = row["spend_cents"] * 1000 // 900
            row["clicks"] = row["impressions"] * 120 // 10000
            continue
        if month != anchor:
            continue  # A and B plants leave the previous month at baseline
        prior = baseline_stats(seed, client_id, platform, month_a)[idx]
        row = rows[idx]
        if rule == "A":
            # Conversions collapse 45-60% while spend holds or rises 3-15%.
            fall = 40 + hp % 16  # keep 40-55% of prior conversions
            rise = 103 + (hp >> 8) % 13
            row["conversions"] = max(1, prior["conversions"] * fall // 100)
            row["spend_cents"] = prior["spend_cents"] * rise // 100
        elif rule == "B" and RULE_B_DIRECTION.get(client_id) == "worse":
            # Cost per conversion up ~47-79%: spend up, conversions dip mildly.
            row["spend_cents"] = prior["spend_cents"] * (125 + hp % 16) // 100
            row["conversions"] = max(
                1,
                prior["conversions"] * (78 + (hp >> 8) % 8) // 100,
            )
        elif rule == "B":
            # Cost per conversion down 40%+: conversions surge on flat spend.
            row["spend_cents"] = prior["spend_cents"] * (95 + hp % 11) // 100
            row["conversions"] = prior["conversions"] * (175 + (hp >> 8) % 36) // 100
        row["impressions"] = row["spend_cents"] * 1000 // 900
        row["clicks"] = row["impressions"] * 150 // 10000
    return rows


def analytics_stats(
    seed: int,
    client_id: str,
    month: str,
    anchor: str,
) -> list[dict[str, Any]]:
    """The analytics view: sessions + conversions per campaign, revenue where
    the client tracks it. Analytics sees both platforms' campaigns regardless
    of ad-platform API auth (site tracking is independent of OAuth)."""
    rows = []
    aov_cents = 4500 + _h(seed, client_id, "aov") % 27501  # $45 .. $320
    for platform in ("google_ads", "meta_ads"):
        for idx, row in enumerate(stats(seed, client_id, platform, month, anchor)):
            sessions = row["clicks"] * (80 + _h(seed, client_id, platform, idx, month, "sess") % 31) // 100
            out = {
                "campaign_id": row["campaign_id"],
                "campaign": row["campaign"],
                "source": "google" if platform == "google_ads" else "meta",
                "month": month,
                "sessions": sessions,
                "conversions": row["conversions"],
            }
            if client_id in REVENUE_TRACKED:
                out["revenue_cents"] = _wobble(
                    row["conversions"] * aov_cents,
                    _h(seed, client_id, platform, idx, month, "rev"),
                    5,
                )
            rows.append(out)
    return rows


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------


def _rules_tripped(
    prior: dict[str, Any],
    current: dict[str, Any],
    *,
    steady_floor: float = 0.95,
    fall_ratio: float = 2 / 3,
    cpa_move: float = 0.40,
    burner_cents: int = 20000,
) -> list[str]:
    rules = []
    spend_a, spend_b = prior["spend_cents"], current["spend_cents"]
    conv_a, conv_b = prior["conversions"], current["conversions"]
    if spend_b >= spend_a * steady_floor and conv_a > 0 and conv_b < conv_a * fall_ratio:
        rules.append("A")
    if conv_a > 0 and conv_b > 0:
        cpa_ratio = (spend_b / conv_b) / (spend_a / conv_a)
        if abs(cpa_ratio - 1) > cpa_move:
            rules.append("B")
    if spend_b > burner_cents and conv_b == 0:
        rules.append("C")
    return rules


def expected_flags(
    seed: int,
    anchor: str,
    month: str | None = None,
    **tolerances: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Per-client flagged campaigns for the (month-1, month) pair, recomputed
    from the served data. Plants stay pinned to `anchor` regardless of the
    pair being evaluated; a correct system evaluates month == anchor."""
    month = month or anchor
    month_a = prev_month(month)
    flags: dict[str, list[dict[str, Any]]] = {}
    for client in CLIENTS:
        cid = client["client_id"]
        client_flags = []
        for platform in ("google_ads", "meta_ads"):
            prior_rows = stats(seed, cid, platform, month_a, anchor)
            current_rows = stats(seed, cid, platform, month, anchor)
            for prior, current in zip(prior_rows, current_rows):
                rules = _rules_tripped(prior, current, **tolerances)
                if rules:
                    client_flags.append(
                        {
                            "platform": platform,
                            "campaign_id": current["campaign_id"],
                            "campaign": current["campaign"],
                            "rules": rules,
                        },
                    )
        if client_flags:
            flags[cid] = client_flags
    return flags


def selftest(seed: int = DEFAULT_SEED, anchor: str | None = None) -> dict[str, Any]:
    """Assert the derived flag set equals the planted intent, robustly.

    Sweeps the tolerance knobs a reasonable reader might choose (how exactly
    is "held steady" or "more than a third" read?) and asserts the flagged
    campaign set never changes. Also asserts no baseline campaign anywhere
    near the anchor pair trips any rule, and that the broken-Meta client and
    plant clients are disjoint.
    """
    anchor = anchor or default_anchor()
    assert BROKEN_META_CLIENT not in PLANTS
    planted = {
        (cid, platform, len(campaign_defs(seed, cid, platform)) - used)
        for cid, plants in PLANTS.items()
        for platform, used in [
            (p, [x[0] for x in plants[: i + 1]].count(p))
            for i, (p, _) in enumerate(plants)
        ]
    }
    sweeps = [
        {},
        {"steady_floor": 0.90, "fall_ratio": 0.70, "cpa_move": 0.36},
        {"steady_floor": 1.00, "fall_ratio": 0.63, "cpa_move": 0.44},
    ]
    for tol in sweeps:
        derived = expected_flags(seed, anchor, **tol)
        derived_set = {
            (cid, f["platform"], int(f["campaign_id"].rsplit("-", 1)[1][1:]) - 1)
            for cid, fs in derived.items()
            for f in fs
        }
        assert derived_set == planted, (tol, derived_set ^ planted)
    # No baseline month pair outside the anchor pair trips anything.
    for probe in ("2026-03", "2026-04", "2025-11", prev_month(prev_month(anchor))):
        assert expected_flags(seed, anchor, month=probe) == {}, probe
    n_campaigns = sum(
        len(campaign_defs(seed, c["client_id"], p))
        for c in CLIENTS
        for p in ("google_ads", "meta_ads")
    )
    baseline = expected_flags(seed, anchor)
    return {
        "anchor": anchor,
        "clients": len(CLIENTS),
        "campaigns": n_campaigns,
        "flagged_campaigns": sum(len(v) for v in baseline.values()),
        "flagged_clients": sorted(baseline),
        "flags": baseline,
    }


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------


@dataclass
class DeliverySink:
    """Thread-safe store of delivered reports."""

    deliveries: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, body: Any) -> None:
        with self._lock:
            self.deliveries.append(
                {
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "body": body,
                },
            )

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.deliveries)


class _Handler(BaseHTTPRequestHandler):
    seed: int = DEFAULT_SEED
    anchor: str = ""
    sink: DeliverySink

    def _send_json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        if parsed.path == "/health":
            self._send_json(200, {"status": "ok"})
            return
        if parsed.path == "/clients":
            self._send_json(
                200,
                [
                    {**c, "revenue_tracked": c["client_id"] in REVENUE_TRACKED}
                    for c in CLIENTS
                ],
            )
            return
        if parsed.path == "/deliveries":
            self._send_json(200, self.sink.snapshot())
            return
        if len(parts) == 3 and parts[0] == "clients":
            client_id, platform = parts[1], parts[2]
            if not any(c["client_id"] == client_id for c in CLIENTS):
                self._send_json(404, {"error": f"unknown client {client_id}"})
                return
            month = parse_qs(parsed.query).get("month", [None])[0]
            try:
                assert month and len(month) == 7
                date(int(month[:4]), int(month[5:]), 1)
            except (AssertionError, ValueError):
                self._send_json(400, {"error": "month query param required, YYYY-MM"})
                return
            if platform == "meta_ads" and client_id == BROKEN_META_CLIENT:
                self._send_json(
                    401,
                    {
                        "error": "AUTH_EXPIRED",
                        "message": (
                            "The Meta Ads connection for this client has expired; "
                            "a member of the team needs to reconnect the account."
                        ),
                    },
                )
                return
            if platform in ("google_ads", "meta_ads"):
                self._send_json(
                    200,
                    stats(self.seed, client_id, platform, month, self.anchor),
                )
                return
            if platform == "analytics":
                self._send_json(
                    200,
                    analytics_stats(self.seed, client_id, month, self.anchor),
                )
                return
            self._send_json(404, {"error": f"unknown platform {platform}"})
            return
        self._send_json(404, {"error": f"unknown path {parsed.path}"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path != "/deliveries":
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
        self._send_json(200, {"status": "received"})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass  # keep benchmark output clean; traffic is visible via the sink


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
        self.sink = DeliverySink()
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
            name="acr-fixture-server",
            daemon=True,
        )

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def set_anchor(self, anchor: str) -> None:
        """Move the reported month the plants are pinned to.

        A scheduled task reports the month before the activation it fires on,
        which is not the month before *now* when a harness fires it early. The
        caller aligns the fixture to the task's own activation so the planted
        anomalies land in the pair the system will actually compare. Data is
        generated per request, so this takes effect immediately.
        """
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
    parser.add_argument("--anchor", default=None, help="reported month, YYYY-MM")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        report = selftest(args.seed, args.anchor)
        print(json.dumps(report, indent=2))
        return
    server = FixtureServer(seed=args.seed, port=args.port, anchor=args.anchor).start()
    print(
        f"Fixture on {server.base_url} (seed={args.seed}, anchor={server.anchor}). "
        "Ctrl-C to stop.",
    )
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
