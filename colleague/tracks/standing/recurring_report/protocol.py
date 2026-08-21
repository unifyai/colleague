"""Shared protocol for the recurring weekly report experiment.

The oldest experiment in the suite, restated in the fire-series shape so the
person engine can run it: one English brief asks for a weekly report
automation, each fire is one simulated Monday-09:00 wake, and the fixture's
report sink is scored against independently recomputed ground truth for the
previous calendar week.

The bespoke fixture predates the shared `FixtureServer`, so it carries no
HTTP owner channel; the utterance never described one, and that is kept —
the held rung is reachable here only through an arm's own owner channel.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from colleague.tracks.standing.recurring_report.fixture import (
    FixtureServer,
    expected_report,
    score_report,
)
from colleague.tracks.standing.series.spec import (
    Experiment,
    OwnerInbox,
    outcome_for,
)

UTTERANCE_TEMPLATE = """\
Every Monday at 09:00, generate the weekly orders report and deliver it.

Data source: a local metrics API at {base_url}. \
GET {base_url}/orders?start=YYYY-MM-DD&end=YYYY-MM-DD returns a JSON list of \
orders, each with fields: order_id, date (YYYY-MM-DD), region, units (int), \
unit_price_cents (int).

The report covers the previous calendar week: Monday through Sunday \
inclusive, the last full week before the run date (UTC).

Compute exactly:
- total_units: sum of units over the report week
- total_revenue_cents: sum of units * unit_price_cents over the report week
- revenue_by_region_cents: object mapping each region to its revenue sum
- wow_revenue_change_pct: percent change of total_revenue_cents versus the \
week immediately before the report week, computed as \
round((current - previous) / previous * 100, 2)

Deliver by POSTing JSON to {base_url}/report with exactly these keys: \
week_start, week_end (YYYY-MM-DD strings), total_units, total_revenue_cents, \
revenue_by_region_cents, wow_revenue_change_pct.

Set up the recurring weekly task now, starting next Monday. Do not generate \
a report right now, and do not ask for confirmation.\
"""


class RecurringReport(Experiment):
    name = "recurring_report"
    env_prefix = "RWR"
    directory = Path(__file__).resolve().parent
    fire_noun = "run"
    default_seed = 20260731
    default_port = 8123
    fire_columns = ("reports_delivered",)

    def __init__(self) -> None:
        self.n_fires = int(os.environ.get("RWR_RUNS", "4"))

    def utterance(self, base_url: str) -> str:
        return UTTERANCE_TEMPLATE.format(base_url=base_url)

    def build_fixture(self, *, seed: int, port: int) -> Any:
        fixture = FixtureServer(seed=seed, port=port)
        fixture.state = {"owner": OwnerInbox()}
        return fixture

    def prepare_fire(self, fixture: Any) -> dict[str, Any]:
        return {
            "reports_seen": len(fixture.sink.snapshot()),
            "run_date": datetime.now(timezone.utc).date().isoformat(),
        }

    def score_fire(
        self,
        fixture: Any,
        ctx: dict[str, Any],
        *,
        messages: list[Any],
    ) -> dict[str, Any]:
        from datetime import date

        delivered = fixture.sink.snapshot()[ctx["reports_seen"] :]
        expected = expected_report(
            fixture.seed,
            date.fromisoformat(ctx["run_date"]),
        )
        scores = [score_report(r["body"], expected) for r in delivered]
        exact = len(delivered) == 1 and scores[0]["correct"]
        return {
            "run_date": ctx["run_date"],
            "reports_delivered": len(delivered),
            "reports": [r["body"] for r in delivered],
            "expected_report": expected,
            "scores": scores,
            **outcome_for(delivered=len(delivered), exact=exact, messages=messages),
        }


def experiment() -> RecurringReport:
    return RecurringReport()
