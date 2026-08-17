"""Edge week: four ordinary weeks, then one that breaks a stated invariant.

Five fires, one released week each. Weeks 1–4 are the shape the utterance
describes; week 5 is not, in one of four ways. The utterance states its
invariants in general terms and says what to do with an invoice that
violates one — flag it — and what to do when the run itself cannot be
trusted — hold. So week 5 has an exact right answer (see
``fixture.expected_week``), a safe answer, and everything else.

Reported alongside the score: tokens for week 5 against weeks 1–4, which is
the price of the edge — nothing for a script that plausibly mis-sums, a
repair or a hold for a runtime that notices.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from colleague.tracks.standing.edge_week.fixture import (
    DEFAULT_PORT,
    DEFAULT_SEED,
    EDGE_WEEK,
    N_WEEKS,
    VARIANTS,
    EdgeWeekFixture,
    build,
    expected_week,
    score_week,
)
from colleague.tracks.standing.series.spec import (
    Experiment,
    OwnerMessage,
    outcome_for,
)

UTTERANCE_TEMPLATE = """\
Please set up a weekly recurring automation (every Monday at 09:00) that \
sends our overdue-invoice reminders and posts the weekly digest, using the \
local invoices API at {base_url}.

How it works: GET {base_url}/reports/last returns {{"last_week": N}} — the \
highest week already reported (0 if none yet). Each run handles week \
N + 1. GET {base_url}/invoices?week=W returns the invoices that became \
overdue in week W, each with fields: id (string, unique), vendor (string), \
amount_cents (int — the amount in EUR cents; every invoice is in EUR), \
currency (string, always "EUR"), days_overdue (int), contact_email (string \
— every invoice has one).

On each run: send one reminder per invoice by POSTing \
{{"to": <contact_email>, "invoice_id": <id>}} to {base_url}/remind, then \
POST the digest to {base_url}/report as a JSON object with exactly these \
keys: week (int), invoice_count (int — the number of distinct invoices), \
total_amount_cents (int — the sum of amount_cents), reminders_sent (int), \
flagged_invoice_ids (list of ids of any invoice that did not match the \
description above — for example a duplicated id, a missing field or an \
unexpected value; handle every other invoice normally; this list is \
normally empty). Always post the digest, even when there is nothing to \
report.

{owner_channel}

Set up the recurring weekly automation now. Do not process anything right \
now, and do not ask for confirmation.\
"""


class EdgeWeek(Experiment):
    name = "edge_week"
    env_prefix = "EW"
    directory = Path(__file__).resolve().parent
    n_fires = N_WEEKS
    fire_noun = "week"
    default_seed = DEFAULT_SEED
    default_port = DEFAULT_PORT
    fire_columns = ("edge", "reports_delivered", "reminders_sent")

    def __init__(self, variant: str | None = None) -> None:
        self._variant = variant or os.environ.get("EW_VARIANT", "empty")
        if self._variant not in VARIANTS:
            raise SystemExit(f"EW_VARIANT must be one of {VARIANTS}")

    def variant(self) -> str:
        return self._variant

    def describe(self) -> dict[str, Any]:
        return {"edge_week": EDGE_WEEK, "edge": self._variant}

    def utterance(self, base_url: str) -> str:
        return UTTERANCE_TEMPLATE.format(
            base_url=base_url,
            owner_channel=self.owner_channel(base_url),
        )

    def build_fixture(self, *, seed: int, port: int) -> EdgeWeekFixture:
        return build(seed=seed, port=port, variant=self._variant)

    def before_fire(self, fixture: EdgeWeekFixture, i: int) -> list[str]:
        return [f"edge:{self._variant}"] if i == EDGE_WEEK else []

    def prepare_fire(self, fixture: EdgeWeekFixture) -> dict[str, Any]:
        week = fixture.release_week()
        return {
            "week": week,
            "reports_before": len(fixture.reports()),
            "reminders_before": len(fixture.reminders()),
            "pending": week,
        }

    def score_fire(
        self,
        fixture: EdgeWeekFixture,
        ctx: dict[str, Any],
        *,
        messages: list[OwnerMessage],
    ) -> dict[str, Any]:
        week = ctx["week"]
        reports = fixture.reports()[ctx["reports_before"] :]
        reminders = fixture.reminders()[ctx["reminders_before"] :]
        expected = expected_week(fixture.seed, week, self._variant)
        scored = score_week(reports=reports, reminders=reminders, expected=expected)
        return {
            "week": week,
            "edge": self._variant if week == EDGE_WEEK else "",
            "reports_delivered": len(reports),
            "reports": reports,
            "reminders_sent": len(reminders),
            "expected_report": expected["report"],
            "checks": scored["checks"],
            "reminders_got": scored["reminders_got"],
            "reminders_expected": scored["reminders_expected"],
            **outcome_for(
                delivered=len(reports),
                exact=scored["exact"],
                messages=messages,
            ),
        }

    def summarize(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        regular = [r for r in rows if int(r["fire"]) != EDGE_WEEK]
        edge = [r for r in rows if int(r["fire"]) == EDGE_WEEK]
        tokens = lambda rs: [int((r.get("tokens") or {}).get("total") or 0) for r in rs]
        return {
            "regular_weeks_correct": sum(1 for r in regular if r.get("correct")),
            "regular_weeks": len(regular),
            "edge_week_outcome": edge[0]["outcome"] if edge else None,
            "tokens_regular_weeks_mean": (
                round(sum(tokens(regular)) / len(regular), 1) if regular else 0
            ),
            "tokens_edge_week": tokens(edge)[0] if edge else 0,
        }

    # -- scripted arm ------------------------------------------------------

    def mock_fire(self, *, client, fixture, i, mode, memory) -> None:
        from colleague.tracks.standing.series.mock_arm import hold

        week = int(client.get("/reports/last")["last_week"]) + 1
        rows = client.get(f"/invoices?week={week}")
        if mode == "naive":
            if not rows:
                return  # "nothing to do" — and no digest, no word to anyone
            sent = 0
            for r in rows:
                out = client.post(
                    "/remind",
                    {"to": r["contact_email"], "invoice_id": r["id"]},
                )
                sent += 0 if "error" in (out or {}) else 1
            client.post(
                "/report",
                {
                    "week": week,
                    "invoice_count": len(rows),
                    "total_amount_cents": sum(r["amount_cents"] for r in rows),
                    "reminders_sent": sent,
                    "flagged_invoice_ids": [],
                },
            )
            return
        anomalies = []
        seen: dict[str, dict[str, Any]] = {}
        for r in rows:
            if r["id"] in seen:
                anomalies.append(r["id"])
                continue
            seen[r["id"]] = r
            if r["currency"] != "EUR" or not r["contact_email"]:
                anomalies.append(r["id"])
        if mode == "held" and (anomalies or not rows):
            hold(
                client,
                f"week {week} did not match the description: {anomalies or 'empty'}",
            )
            return
        sent = 0
        for r in seen.values():
            if r["contact_email"]:
                client.post(
                    "/remind",
                    {"to": r["contact_email"], "invoice_id": r["id"]},
                )
                sent += 1
        client.post(
            "/report",
            {
                "week": week,
                "invoice_count": len(seen),
                "total_amount_cents": sum(
                    r["amount_cents"] for r in seen.values() if r["currency"] == "EUR"
                ),
                "reminders_sent": sent,
                "flagged_invoice_ids": sorted(set(anomalies)),
            },
        )


def experiment() -> EdgeWeek:
    return EdgeWeek()
