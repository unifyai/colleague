"""Deterministic ad-platform sandbox for the agency-client-reporting use case.

Stands in for Google Ads, Meta Ads and Google Analytics for a 14-client
performance agency. Everything is seeded and stdlib-only so any third party
can reproduce the exact same campaign data and ground truth.

The landing page's brief (the system under test receives it verbatim) flags:
  rule A: spend held steady or rose while conversions fell by more than a third
  rule B: cost per conversion moved more than 40%
  rule C: spent over $200 and converted nothing

Baseline campaigns are generated inside safe zones (month-over-month wobble
bounded well away from every rule threshold), then eleven anomalies are
planted across eight clients in the anchor month pair. Ground truth is
recomputed from the served data, and `selftest` asserts the derived flag set
equals the planted intent under a sweep of tolerance choices — so a correct
system's flag list is exactly the planted set, never an artifact of noise.

Both sides of that are also asserted *as margins*, and re-asserted across a
sweep of seeds. Baselines have to stay clear of every threshold and plants
have to clear them, both by a stated distance; a plant tuned to land a
thousandth the right side of one reading is a plant that stops tripping when
`ACR_SEED` changes. `ACR_SEED` is a documented knob, so a user can reach any
seed, and a live run costs real money — the seed sweep is what keeps the
fixture's guarantee from being true only of the seed it was tuned on.

Four plant *shapes* cover the three rules. Shape AC — a campaign that
converted normally last month and not at all this month, on spend that rose —
trips rules A and C at once and is the case where cost per conversion is a
number on one side of the comparison and undefined on the other. Report code
that guards the prior month against None but not the reported one dies on it,
so the shape has to exist in the fixture.

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
    {
        "client_id": "c04",
        "name": "Northgate Dental Group",
        "vertical": "local services",
    },
    {"client_id": "c05", "name": "Brightside HVAC", "vertical": "local services"},
    {"client_id": "c06", "name": "Fernway Coffee Roasters", "vertical": "ecommerce"},
    {
        "client_id": "c07",
        "name": "Atlas Legal Partners",
        "vertical": "professional services",
    },
    {"client_id": "c08", "name": "Cobalt Cycling", "vertical": "ecommerce"},
    {"client_id": "c09", "name": "Meridian Software", "vertical": "b2b saas"},
    {"client_id": "c10", "name": "Sunhaven Resorts", "vertical": "travel"},
    {
        "client_id": "c11",
        "name": "Pallas Home Security",
        "vertical": "consumer services",
    },
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
# Planted anomalies: eleven campaigns across eight clients in the anchor month
# pair. The letters name the *shape* each plant exists to trip, not a
# taxonomy of the page's rules: a rule-A collapse also moves cost per
# conversion, and shape AC trips A and C together by design. Ground truth
# records every rule a campaign trips, and the flag set is compared
# campaign-wise.
#
# Shapes:
#   A   conversions collapse while spend holds or rises
#   B   cost per conversion moves well past 40% (either direction), without
#       the conversion fall that would also make it a shape A
#   C   a burner that converts nothing in either month of the pair
#   AC  converted normally last month, nothing this month, spend up — the
#       realistic dead campaign, and the only shape where cost per conversion
#       is defined on one side of the comparison and undefined on the other
# ---------------------------------------------------------------------------

# The page read literally, and the source of `_rules_tripped`'s defaults — one
# definition, so the sweep below cannot stop covering the default reading just
# because someone retuned the function signature.
PAGE_READING: dict[str, float] = {
    "steady_floor": 0.95,
    "fall_ratio": 2 / 3,
    "cpa_move": 0.40,
}

# The readings a reasonable person might take of the page's wording — how
# exactly is "held steady" or "by more than a third" meant? `selftest` asserts
# the flagged set is identical under all of them, so a correct system's answer
# is never an artifact of one reading. Module-level rather than local to
# `selftest` because the plants are tuned against the strictest entry below,
# and the two must not drift apart.
TOLERANCE_SWEEP: tuple[dict[str, float], ...] = (
    PAGE_READING,
    {"steady_floor": 0.90, "fall_ratio": 0.70, "cpa_move": 0.36},  # lenient reader
    {"steady_floor": 1.00, "fall_ratio": 0.63, "cpa_move": 0.44},  # strict reader
)

# The hardest combination for a plant to trip, taken across the sweep rather
# than written down: the highest bar for "spend held steady", the smallest
# conversion fall that still counts, the largest cost-per-conversion move that
# still counts. Plants must clear these; baselines must stay clear of them.
STRICTEST = {
    "steady_floor": max(t["steady_floor"] for t in TOLERANCE_SWEEP),
    "fall_ratio": min(t["fall_ratio"] for t in TOLERANCE_SWEEP),
    "cpa_move": max(t["cpa_move"] for t in TOLERANCE_SWEEP),
}

# And the most permissive rule-A reading, which a rule-B plant must stay on the
# right side of: a B plant whose conversions dip past this is indistinguishable
# from an A plant, which would make the narrative three copies of one failure.
LOOSEST_FALL_RATIO = max(t["fall_ratio"] for t in TOLERANCE_SWEEP)

# How far past a threshold a plant has to sit, in ratio units, before
# `selftest` calls it deliberate rather than lucky. Tuning a plant to land
# 0.001 the right side of the strictest reading is how seed fragility gets in.
PLANT_MARGIN = 0.05

# Seeds `selftest` re-checks on every call, so a tuning change that only holds
# at the default seed fails offline instead of during a $30 live run. `ACR_SEED`
# is a documented knob, so an arbitrary seed is reachable in practice.
SEED_SWEEP: tuple[int, ...] = tuple(range(1, 65))

PLANTS: dict[str, list[tuple[str, str]]] = {
    "c02": [("google_ads", "A")],
    "c04": [("meta_ads", "B"), ("google_ads", "C")],
    "c05": [("google_ads", "C")],
    "c06": [("google_ads", "AC")],
    "c09": [("google_ads", "A"), ("meta_ads", "B")],
    "c10": [("meta_ads", "AC")],
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
# small month-keyed wobble. Spend wobbles ±6% and conversions ±6% on a base of
# >= 60 conversions, so month-over-month conversion ratios stay within
# ~[0.87, 1.15] and cost-per-conversion ratios within ~[0.78, 1.28], integer
# rounding included.
#
# Those are measured against the *strictest* reading in TOLERANCE_SWEEP, not
# the page read literally: rule A needs a fall past 0.63 and rule B a move
# beyond 0.56/1.44. So the nearest baseline still sits ~0.24 of a ratio clear
# of rule A and ~0.17 clear of rule B — the wobble is not what any seed
# fragility comes from, and widening it would only spend that margin. Every
# baseline campaign converts, so rule C can only come from a plant.
# `selftest` verifies all of this by brute force, across seeds, rather than
# trusting the algebra.
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
    # >= 60, not >= 30. Baselines were never the fragile part — even at 30 they
    # sat 0.2 of a ratio away from every threshold. What a low floor costs is
    # *rounding slop*: the plants scale this number by a factor and floor the
    # result, so dropping one conversion from a base of 28 moves the realised
    # ratio 3.6%, which is the same order as a plant's margin. Doubling the
    # floor halves that slop and buys back the margin.
    conversions = 60 + hc % 340
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

    Shapes A, B and AC override only the anchor month (the reported month),
    scaled from the served previous-month row so the planted relationship is
    exact — the previous month stays a healthy baseline, which for AC is the
    whole point. Shape C (a burner that never converts) overrides both months
    of the pair.
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
            # $300 floor, not $240: after the ±10% wobble on the reported month
            # the lower end still clears rule C's $200 by a third, so the one
            # threshold the sweep does not vary (the page says "over $200"
            # unambiguously) is not carried by rounding either.
            spend_a = 30000 + hp % 56001  # $300 .. $860
            row = rows[idx]
            row["conversions"] = 0
            row["spend_cents"] = (
                spend_a if month == month_a else _wobble(spend_a, hp >> 8, 10)
            )
            row["impressions"] = row["spend_cents"] * 1000 // 900
            row["clicks"] = row["impressions"] * 120 // 10000
            continue
        if month != anchor:
            continue  # A, B and AC plants leave the previous month at baseline
        prior = baseline_stats(seed, client_id, platform, month_a)[idx]
        row = rows[idx]
        if rule == "A":
            # Conversions collapse 45-60% while spend holds or rises 3-15%.
            fall = 40 + hp % 16  # keep 40-55% of prior conversions
            rise = 103 + (hp >> 8) % 13
            row["conversions"] = max(1, prior["conversions"] * fall // 100)
            row["spend_cents"] = prior["spend_cents"] * rise // 100
        elif rule == "AC":
            # Converted normally last month, nothing this month, spend up
            # 3-15%. The floor keeps the reported month clear of rule C's $200
            # threshold whatever level this campaign's baseline happens to sit
            # at, so the shape survives a change of seed.
            row["conversions"] = 0
            row["spend_cents"] = max(
                prior["spend_cents"] * (103 + (hp >> 8) % 13) // 100,
                30000 + hp % 56001,  # $300 .. $860
            )
        elif rule == "B":
            # Cost per conversion is moved to an explicit multiple of the prior
            # month's, not to whatever the quotient of two independently
            # wobbled ranges happens to work out to. The quotient's extremes
            # are easy to mis-derive — the previous form's flat-spend surge
            # bottomed out at a 40.0% improvement against a rule that needs
            # *more* than 40%, so some seeds produced a plant the page's own
            # threshold does not flag. Naming the target move keeps the margin
            # visible, and `_assert_plant_margins` measures it.
            worse = RULE_B_DIRECTION.get(client_id) == "worse"
            if worse:
                # Spend up 40-52% for cost per conversion up 62-76%, which
                # leaves conversions dipping only 6-20% — mild enough that even
                # the loosest rule-A reading never reads it as a collapse, so
                # this stays a rule-B story rather than a second shape A.
                spend_pct, cpa_pct = 140 + hp % 13, 162 + (hp >> 8) % 15
            else:
                # Conversions roughly double to triple on flat spend, taking
                # cost per conversion down 52-62%.
                spend_pct, cpa_pct = 95 + hp % 11, 38 + (hp >> 8) % 11
            row["spend_cents"] = prior["spend_cents"] * spend_pct // 100
            # conversions = prior * (spend move / cost-per-conversion move).
            # Rounded in whichever direction pushes the realised move further
            # past the threshold, never back toward it: floor shrinks
            # conversions and so raises cost per conversion, ceil does the
            # reverse. Integer rounding therefore cannot eat the margin.
            num = row["spend_cents"] * prior["conversions"] * 100
            den = prior["spend_cents"] * cpa_pct
            row["conversions"] = max(1, num // den if worse else -(-num // den))
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
            sessions = (
                row["clicks"]
                * (80 + _h(seed, client_id, platform, idx, month, "sess") % 31)
                // 100
            )
            out = {
                "campaign_id": row["campaign_id"],
                "campaign": row["campaign"],
                "source": "google" if platform == "google_ads" else "meta",
                "month": month,
                "sessions": sessions,
                "conversions": row["conversions"],
            }
            if client_id in REVENUE_TRACKED:
                # A campaign that converted nothing earned nothing. _wobble
                # floors at 1 cent, which would read as a penny of revenue on
                # zero orders, so zero conversions short-circuit it.
                out["revenue_cents"] = (
                    _wobble(
                        row["conversions"] * aov_cents,
                        _h(seed, client_id, platform, idx, month, "rev"),
                        5,
                    )
                    if row["conversions"]
                    else 0
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
    steady_floor: float = PAGE_READING["steady_floor"],
    fall_ratio: float = PAGE_READING["fall_ratio"],
    cpa_move: float = PAGE_READING["cpa_move"],
    burner_cents: int = 20000,
) -> list[str]:
    rules = []
    spend_a, spend_b = prior["spend_cents"], current["spend_cents"]
    conv_a, conv_b = prior["conversions"], current["conversions"]
    if (
        spend_b >= spend_a * steady_floor
        and conv_a > 0
        and conv_b < conv_a * fall_ratio
    ):
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


def _planted_set(seed: int) -> set[tuple[str, str, int]]:
    """The (client, platform, campaign index) triples PLANTS occupies."""
    return {
        (cid, platform, idx)
        for cid in PLANTS
        for platform, idx in _plant_slots(seed, cid)
    }


def _assert_flag_set(seed: int, anchor: str) -> None:
    """The derived flag set equals the planted intent under every reading."""
    planted = _planted_set(seed)
    for tol in TOLERANCE_SWEEP:
        derived = expected_flags(seed, anchor, **tol)
        derived_set = {
            (cid, f["platform"], int(f["campaign_id"].rsplit("-", 1)[1][1:]) - 1)
            for cid, fs in derived.items()
            for f in fs
        }
        assert derived_set == planted, (seed, anchor, tol, derived_set ^ planted)


def _assert_plant_margins(seed: int, anchor: str) -> int:
    """Assert every plant clears the strictest reading by `PLANT_MARGIN`.

    `_assert_flag_set` already fails when a plant misses a threshold, but it
    fails with a bare campaign id and only at the seeds where the miss actually
    happens. These assertions name the quantity and the distance instead, so a
    plant tuned to sit a thousandth the right side of a threshold fails here —
    at every seed, with the number in the message — rather than waiting for the
    seed that tips it over. Returns the number of plants checked.
    """
    month_a = prev_month(anchor)
    burner = 20000  # rule C's $200; the page's wording leaves nothing to read
    seen = 0
    for cid in PLANTS:
        for (platform, idx), rule in _plant_slots(seed, cid).items():
            seen += 1
            prior = stats(seed, cid, platform, month_a, anchor)[idx]
            current = stats(seed, cid, platform, anchor, anchor)[idx]
            where = (seed, anchor, cid, platform, idx, rule)
            conv_a, conv_b = prior["conversions"], current["conversions"]
            spend_a, spend_b = prior["spend_cents"], current["spend_cents"]
            if rule in ("A", "AC"):
                # Spend has to read as held-or-risen against the highest bar,
                # and conversions have to fall past the smallest fall that
                # counts. AC's fall is to zero, so only spend needs a margin.
                assert spend_b >= spend_a * STRICTEST["steady_floor"], (
                    where,
                    spend_a,
                    spend_b,
                )
                if rule == "A":
                    assert conv_a > 0, (where, conv_a)
                    ratio = conv_b / conv_a
                    assert ratio <= STRICTEST["fall_ratio"] - PLANT_MARGIN, (
                        where,
                        ratio,
                    )
            if rule == "B":
                assert conv_a > 0 and conv_b > 0, (where, conv_a, conv_b)
                move = abs((spend_b / conv_b) / (spend_a / conv_a) - 1)
                assert move >= STRICTEST["cpa_move"] + PLANT_MARGIN, (where, move)
                # A B plant must not also read as a conversion collapse, or it
                # becomes a second shape A and the direction split is pointless.
                ratio = conv_b / conv_a
                assert ratio >= LOOSEST_FALL_RATIO + PLANT_MARGIN, (where, ratio)
            if rule in ("C", "AC"):
                assert conv_b == 0, (where, conv_b)
                # 1.20x rather than 1.0x: rule C's threshold is the one the
                # sweep does not vary, so its margin is asserted rather than
                # left to the wobble happening to stay on the right side.
                assert spend_b >= burner * 1.20, (where, spend_b)
                if rule == "C":
                    assert conv_a == 0 and spend_a >= burner * 1.20, (
                        where,
                        conv_a,
                        spend_a,
                    )
            # Every AC plant is a live campaign that went dead, not a burner:
            # healthy conversions in the prior month, none in the reported one.
            # This is the shape that leaves cost per conversion defined on one
            # side of the comparison and undefined on the other, so its exact
            # rule set is asserted rather than left to the set comparison.
            if rule == "AC":
                assert conv_a >= 20, (where, conv_a)
                for tol in TOLERANCE_SWEEP:
                    tripped = _rules_tripped(prior, current, **tol)
                    assert tripped == ["A", "C"], (where, tol, tripped)
    return seen


def selftest(seed: int = DEFAULT_SEED, anchor: str | None = None) -> dict[str, Any]:
    """Assert the derived flag set equals the planted intent, robustly.

    Sweeps the tolerance knobs a reasonable reader might choose (how exactly
    is "held steady" or "more than a third" read?) and asserts the flagged
    campaign set never changes. Also asserts no baseline campaign anywhere
    near the anchor pair trips any rule, that every plant clears the strictest
    reading in the sweep by a stated margin rather than by luck, and that the
    broken-Meta client and plant clients are disjoint.

    All of that then re-runs across `SEED_SWEEP`. `ACR_SEED` is a documented
    knob, so any seed is reachable by a user; a guarantee that holds only at
    the default is not a guarantee, and a $30 live run is the wrong place to
    find that out.
    """
    anchor = anchor or default_anchor()
    assert BROKEN_META_CLIENT not in PLANTS
    _assert_flag_set(seed, anchor)
    # No baseline month pair outside the anchor pair trips anything. Probes are
    # derived from the anchor, never hardcoded: the pair (m - 1, m) is only
    # plant-free for m at or before prev^2(anchor), because shape C overrides
    # the anchor pair's *prior* month too. A fixed list silently becomes a
    # false failure as soon as a caller anchors onto one of its months — and
    # the harness now re-anchors mid-run, so that is reachable.
    probe = prev_month(anchor)
    for _ in range(6):
        probe = prev_month(probe)  # prev^2 .. prev^7 of the anchor
        assert expected_flags(seed, anchor, month=probe) == {}, probe
    n_plants = _assert_plant_margins(seed, anchor)
    assert n_plants == sum(len(ps) for ps in PLANTS.values())
    assert sum(1 for ps in PLANTS.values() for _, r in ps if r == "AC") >= 1
    # The same guarantees at seeds nobody chose. Only the per-seed core, not
    # the probe months: those are the expensive part and they exercise the
    # anchor, which the caller varies, rather than the seed.
    for other in SEED_SWEEP:
        if other == seed:
            continue
        _assert_flag_set(other, anchor)
        _assert_plant_margins(other, anchor)
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
