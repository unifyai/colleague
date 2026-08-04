"""What the system under test is asked, and how its output is scored.

The request is the landing page's own `brief` field, read out of
`useCases.tsx` at run time and passed through untouched. Nothing paraphrases
it and nothing can drift from it: the brief's sha256 is recorded in every
result file, so a figure transcribed onto the page can be traced back to the
exact words that produced it.

Two things are added alongside the brief, and neither is a hint about the
work:

  - **Connections.** The brief says "connect the client's Google Ads, Meta
    Ads and Google Analytics". Standing in for three OAuth connections is one
    local fixture API, so its endpoints have to be stated.
  - **A hand-over shape.** The brief asks for a doc and a draft email. There
    is no mail server here, so the hand-over is a POST carrying the doc and
    the email plus machine-readable fields (`status`, `flagged`) that make
    scoring exact instead of an LLM judgment.

What is deliberately NOT supplied: which month to report on, which clients
exist, what "held steady" or "more than a third" mean, and what to do about
the client whose Meta connection is dead. Those are the measurement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from colleague.tracks.usecases.agency_client_reporting.fixture import (
    BROKEN_META_CLIENT,
    CLIENTS,
    DEFAULT_SEED,
    default_anchor,
    expected_flags,
)

SLUG = "agency-client-reporting"
DEFAULT_USECASES_TSX = Path.home() / "landing-page" / "src" / "data" / "useCases.tsx"

CONNECTION_BLOCK = """\
Connection details for this agency. The three ad platforms are already \
authorised and are served by one local API at {base_url}:

  GET {base_url}/clients
      the agency's client list: client_id, name, vertical, revenue_tracked
  GET {base_url}/clients/{{client_id}}/google_ads?month=YYYY-MM
  GET {base_url}/clients/{{client_id}}/meta_ads?month=YYYY-MM
      campaign rows: campaign_id, campaign, month, spend_cents, impressions, \
clicks, conversions
  GET {base_url}/clients/{{client_id}}/analytics?month=YYYY-MM
      campaign rows: campaign_id, campaign, source, month, sessions, \
conversions, and revenue_cents for clients that track revenue

All money is integer cents. Every endpoint is read-only.

Hand each client's finished report back by POSTing JSON to \
{base_url}/deliveries, one POST per client, with exactly these keys:

  client_id       the client's id
  month           the month the report covers, as "YYYY-MM"
  status          "drafted" if you wrote the report, "blocked" if you did not
  blocked_reason  one sentence when status is "blocked", otherwise ""
  flagged         the campaigns you are flagging: a list of objects with \
campaign_id, platform ("google_ads" or "meta_ads"), and reason
  doc_markdown    the report document, as markdown
  draft_email     an object with to, subject, body

There is no mail server and no client-facing channel connected here, so that \
POST is the whole hand-over.\
"""


def extract_brief(path: Path = DEFAULT_USECASES_TSX, slug: str = SLUG) -> str:
    """The page's `brief` string, verbatim, straight out of useCases.tsx."""
    if not path.exists():
        raise SystemExit(
            f"useCases.tsx not found at {path} — clone unifyai/landing-page "
            f"beside this repo or set ACR_USECASES_TSX",
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
#
# Flags are scored campaign-wise against ground truth recomputed from the
# served data: a flag set is right when it is exactly the planted set, so
# both a miss and an over-flag count against it. The reason text is recorded
# but never scored — no LLM judging anywhere in this path.
# ---------------------------------------------------------------------------


def _client_delivery(deliveries: list[dict[str, Any]], client_id: str) -> dict[str, Any]:
    """The authoritative delivery for one client: the last one posted."""
    bodies = [
        d["body"]
        for d in deliveries
        if isinstance(d.get("body"), dict) and d["body"].get("client_id") == client_id
    ]
    return {"body": bodies[-1] if bodies else None, "posts": len(bodies)}


def score_run(
    deliveries: list[dict[str, Any]],
    *,
    seed: int,
    anchor: str,
) -> dict[str, Any]:
    """Score one reporting cycle against the fixture's ground truth."""
    expected = expected_flags(seed, anchor)
    rows: list[dict[str, Any]] = []
    for client in CLIENTS:
        cid = client["client_id"]
        found = _client_delivery(deliveries, cid)
        body = found["body"]
        want = {f["campaign_id"] for f in expected.get(cid, [])}
        got: set[str] = set()
        if body is not None:
            got = {
                f["campaign_id"]
                for f in (body.get("flagged") or [])
                if isinstance(f, dict) and f.get("campaign_id")
            }
        email = (body or {}).get("draft_email") or {}
        rows.append(
            {
                "client_id": cid,
                "delivered": body is not None,
                "posts": found["posts"],
                "status": (body or {}).get("status"),
                "month": (body or {}).get("month"),
                "blocked_reason": (body or {}).get("blocked_reason") or "",
                "flags_expected": sorted(want),
                "flags_reported": sorted(got),
                "flags_matched": sorted(want & got),
                "flags_missed": sorted(want - got),
                "flags_extra": sorted(got - want),
                "flags_exact": want == got,
                "doc_chars": len(str((body or {}).get("doc_markdown") or "")),
                "email_to": email.get("to") if isinstance(email, dict) else None,
                "email_chars": (
                    len(str(email.get("body") or "")) if isinstance(email, dict) else 0
                ),
            },
        )

    delivered = [r for r in rows if r["delivered"]]
    drafted = [r for r in delivered if r["status"] == "drafted"]
    blocked = [r for r in delivered if r["status"] == "blocked"]
    broken = next(r for r in rows if r["client_id"] == BROKEN_META_CLIENT)
    return {
        "clients_total": len(CLIENTS),
        "clients_delivered": len(delivered),
        "reports_drafted": len(drafted),
        "reports_blocked": len(blocked),
        "duplicate_posts": sum(max(0, r["posts"] - 1) for r in rows),
        "flags_expected_total": sum(len(v) for v in expected.values()),
        "flags_matched_total": sum(len(r["flags_matched"]) for r in rows),
        "flags_missed_total": sum(len(r["flags_missed"]) for r in rows),
        "flags_extra_total": sum(len(r["flags_extra"]) for r in rows),
        "clients_flagged_exactly": sum(1 for r in rows if r["flags_exact"]),
        "docs_written": sum(1 for r in drafted if r["doc_chars"] > 400),
        "emails_written": sum(1 for r in drafted if r["email_chars"] > 200),
        "broken_meta_client": {
            "client_id": broken["client_id"],
            "delivered": broken["delivered"],
            "status": broken["status"],
            "blocked_reason": broken["blocked_reason"],
        },
        "clients": rows,
    }


def _perfect_deliveries(seed: int, anchor: str) -> list[dict[str, Any]]:
    """What a flawless cycle posts — the scorer's own fixture."""
    expected = expected_flags(seed, anchor)
    out = []
    for client in CLIENTS:
        cid = client["client_id"]
        if cid == BROKEN_META_CLIENT:
            body = {
                "client_id": cid,
                "month": anchor,
                "status": "blocked",
                "blocked_reason": "The Meta Ads connection has expired.",
                "flagged": [],
                "doc_markdown": "",
                "draft_email": {},
            }
        else:
            body = {
                "client_id": cid,
                "month": anchor,
                "status": "drafted",
                "blocked_reason": "",
                "flagged": [
                    {
                        "campaign_id": f["campaign_id"],
                        "platform": f["platform"],
                        "reason": "planted",
                    }
                    for f in expected.get(cid, [])
                ],
                "doc_markdown": "x" * 500,
                "draft_email": {"to": "am@agency.example", "subject": "s", "body": "y" * 300},
            }
        out.append({"received_at": "", "body": body})
    return out


def selftest(seed: int = DEFAULT_SEED, anchor: str | None = None) -> dict[str, Any]:
    """Prove the scorer end to end without spending a token.

    A flawless cycle must score clean, and three specific corruptions — a
    dropped client, a missed flag, an invented flag — must each show up in
    exactly one counter.
    """
    anchor = anchor or default_anchor()
    perfect = _perfect_deliveries(seed, anchor)
    clean = score_run(perfect, seed=seed, anchor=anchor)
    assert clean["clients_delivered"] == len(CLIENTS), clean
    assert clean["flags_missed_total"] == 0, clean
    assert clean["flags_extra_total"] == 0, clean
    assert clean["flags_matched_total"] == clean["flags_expected_total"], clean
    assert clean["clients_flagged_exactly"] == len(CLIENTS), clean
    assert clean["broken_meta_client"]["status"] == "blocked", clean

    dropped = score_run(perfect[:-1], seed=seed, anchor=anchor)
    assert dropped["clients_delivered"] == len(CLIENTS) - 1, dropped

    flagged_client = next(c for c in perfect if c["body"]["flagged"])
    missed = json.loads(json.dumps(perfect))
    target = next(
        c for c in missed if c["body"]["client_id"] == flagged_client["body"]["client_id"]
    )
    target["body"]["flagged"] = target["body"]["flagged"][1:]
    scored = score_run(missed, seed=seed, anchor=anchor)
    assert scored["flags_missed_total"] == 1, scored
    assert scored["flags_extra_total"] == 0, scored

    over = json.loads(json.dumps(perfect))
    over[0]["body"]["flagged"].append(
        {"campaign_id": "c01-g1", "platform": "google_ads", "reason": "invented"},
    )
    scored = score_run(over, seed=seed, anchor=anchor)
    assert scored["flags_extra_total"] == 1, scored
    assert scored["flags_missed_total"] == 0, scored
    return {
        "anchor": anchor,
        "flags_expected_total": clean["flags_expected_total"],
        "clients": clean["clients_total"],
        "scorer": "ok",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true", help="score-path selftest")
    parser.add_argument("--brief", action="store_true", help="print the extracted brief")
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
