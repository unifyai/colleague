"""What the system under test is asked, and how its output is scored.

Same contract as the agency track: the page's `brief` is read out of
`useCases.tsx` at run time and passed through untouched, its sha256 recorded,
and only two things are added — where the fixture's endpoints are, and the
shape of the hand-over. Nothing tells the system which week to report on, how
to read "three weeks running" or "more than 20%", or which metrics are moving.

Scoring differs from the agency track in what a flag *is*. There are no
per-entity anomalies here: the brief's three rules each concern one metric of
the brand as a whole. So a flag is identified by metric name, drawn from the
brief's own vocabulary (repeat rate, blended CAC, flow revenue), and the set
of flagged metrics is compared exactly against ground truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from colleague.tracks.usecases.ecommerce_trading_review.fixture import (
    DEFAULT_SEED,
    METRICS,
    default_anchor,
    expected_flags,
)

SLUG = "ecommerce-trading-review"
DEFAULT_USECASES_TSX = Path.home() / "landing-page" / "src" / "data" / "useCases.tsx"

CONNECTION_BLOCK = """\
Connection details for this brand. Shopify, Klaviyo and Meta Ads are already \
authorised and are served by one local API at {base_url}. Every endpoint takes \
`from` and `to` query params, both Mondays in YYYY-MM-DD, and returns one row \
per week in that range:

  GET {base_url}/shopify/weekly?from=&to=
      week_start, orders, revenue_cents, new_customer_revenue_cents, \
returning_customer_revenue_cents, repeat_purchase_rate_bp, new_customers
  GET {base_url}/klaviyo/weekly?from=&to=
      week_start, campaign_revenue_cents, flow_revenue_cents, list_size
  GET {base_url}/meta/weekly?from=&to=
      week_start, ad_spend_cents, blended_cac_cents

Rates ending `_bp` are basis points, so 2850 means 28.50%. All money is \
integer cents. Every endpoint is read-only, and history runs about a year back.

Slack is not connected. Post the write-up by POSTing JSON to \
{base_url}/slack/trading instead, with exactly these keys:

  week_start     the Monday of the week you are reporting on, "YYYY-MM-DD"
  text           the write-up exactly as you would post it to #trading
  dashboard_url  the link you would include
  flagged        the metrics you are flagging: a list of objects with metric \
(one of "repeat_rate", "blended_cac", "flow_revenue") and reason
  moved          "new" or "returning", whichever you conclude moved

That POST is the whole hand-over.\
"""


def extract_brief(path: Path = DEFAULT_USECASES_TSX, slug: str = SLUG) -> str:
    """The page's `brief` string, verbatim, straight out of useCases.tsx."""
    if not path.exists():
        raise SystemExit(
            f"useCases.tsx not found at {path} — clone unifyai/landing-page "
            f"beside this repo or set ETR_USECASES_TSX",
        )
    text = path.read_text(encoding="utf-8")
    marker = f'slug: "{slug}"'
    start = text.find(marker)
    if start < 0:
        raise SystemExit(f"no use case with slug {slug!r} in {path}")
    nxt = text.find('slug: "', start + len(marker))
    block = text[start : nxt if nxt > 0 else len(text)]
    match = re.search(r'\bbrief:\s*("(?:[^"\\]|\\.)*")', block, re.DOTALL)
    if match is None:
        raise SystemExit(f"use case {slug!r} has no single-string `brief` field")
    return json.loads(match.group(1))


def brief_digest(brief: str) -> str:
    return hashlib.sha256(brief.encode()).hexdigest()


def utterance(brief: str, base_url: str) -> str:
    return f"{brief}\n\n---\n\n{CONNECTION_BLOCK.format(base_url=base_url)}"


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_run(posts: list[dict[str, Any]], *, seed: int, anchor: str) -> dict[str, Any]:
    """Score one Monday's review against the fixture's ground truth."""
    want = set(expected_flags(seed, anchor))
    bodies = [p["body"] for p in posts if isinstance(p.get("body"), dict)]
    latest = bodies[-1] if bodies else None
    got: set[str] = set()
    if latest is not None:
        got = {
            f["metric"]
            for f in (latest.get("flagged") or [])
            if isinstance(f, dict) and f.get("metric") in METRICS
        }
    unknown = []
    if latest is not None:
        unknown = [
            f.get("metric")
            for f in (latest.get("flagged") or [])
            if isinstance(f, dict) and f.get("metric") not in METRICS
        ]
    text = str((latest or {}).get("text") or "")
    return {
        "posted": len(bodies),
        "week_reported": (latest or {}).get("week_start"),
        "flags_expected": sorted(want),
        "flags_reported": sorted(got),
        "flags_matched": sorted(want & got),
        "flags_missed": sorted(want - got),
        "flags_extra": sorted(got - want),
        "flags_exact": want == got,
        "flags_unrecognised": unknown,
        "moved": (latest or {}).get("moved"),
        "dashboard_url": (latest or {}).get("dashboard_url"),
        "text_chars": len(text),
        # The brief asks for new-versus-returning to be split every time; the
        # split is scored as present-or-absent, never on its prose.
        "splits_new_vs_returning": bool(
            re.search(r"new", text, re.I) and re.search(r"return", text, re.I),
        ),
    }


def _perfect_post(seed: int, anchor: str) -> list[dict[str, Any]]:
    return [
        {
            "received_at": "",
            "body": {
                "week_start": anchor,
                "text": "New customer revenue moved; returning held. " + "x" * 400,
                "dashboard_url": "https://example.invalid/dash",
                "flagged": [
                    {"metric": m, "reason": "planted"} for m in expected_flags(seed, anchor)
                ],
                "moved": "new",
            },
        },
    ]


def selftest(seed: int = DEFAULT_SEED, anchor: str | None = None) -> dict[str, Any]:
    """Prove the scorer end to end without spending a token."""
    anchor = anchor or default_anchor()
    clean = score_run(_perfect_post(seed, anchor), seed=seed, anchor=anchor)
    assert clean["flags_exact"], clean
    assert not clean["flags_missed"] and not clean["flags_extra"], clean
    assert clean["week_reported"] == anchor, clean
    assert clean["splits_new_vs_returning"], clean

    missed = json.loads(json.dumps(_perfect_post(seed, anchor)))
    missed[0]["body"]["flagged"] = missed[0]["body"]["flagged"][1:]
    s = score_run(missed, seed=seed, anchor=anchor)
    assert len(s["flags_missed"]) == 1 and not s["flags_extra"], s

    over = json.loads(json.dumps(_perfect_post(seed, anchor)))
    over[0]["body"]["flagged"] = [{"metric": "flow_revenue", "reason": "only this one"}]
    s = score_run(over, seed=seed, anchor=anchor)
    assert len(s["flags_missed"]) == 2 and not s["flags_extra"], s

    junk = json.loads(json.dumps(_perfect_post(seed, anchor)))
    junk[0]["body"]["flagged"].append({"metric": "aov", "reason": "not a rule"})
    s = score_run(junk, seed=seed, anchor=anchor)
    assert s["flags_unrecognised"] == ["aov"], s
    assert s["flags_exact"], s  # an unrecognised metric is noted, not counted

    none = score_run([], seed=seed, anchor=anchor)
    assert none["posted"] == 0 and none["flags_missed"] == sorted(METRICS), none
    return {
        "anchor_week": anchor,
        "flags_expected": sorted(expected_flags(seed, anchor)),
        "scorer": "ok",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--brief", action="store_true")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--anchor", default=None)
    parser.add_argument("--usecases-tsx", default=None)
    args = parser.parse_args()
    if args.brief:
        path = Path(args.usecases_tsx) if args.usecases_tsx else DEFAULT_USECASES_TSX
        brief = extract_brief(path)
        print(json.dumps({"sha256": brief_digest(brief), "brief": brief}, indent=2))
        return
    print(json.dumps(selftest(args.seed, args.anchor), indent=2))


if __name__ == "__main__":
    main()
