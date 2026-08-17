"""Repair locality: one of three inputs drifts; how much of the automation moves?

Ten fires. Before each, new orders, refunds and tickets are released. Before
fire 5 the refunds API renames one field; orders and tickets do not change.
Three things are measured from fire 5 on:

- **recovery** — the report is right again (the shared rubric, per fire);
- **repair cost** — tokens spent repairing (the ``repair`` bucket where the
  arm's meter has one; the operator-fix phase for arms fixed by a person);
- **locality** — the orders and tickets sections of the report keep exactly
  the shape they had before the drift: same keys, same order, same value
  types. A repair that reaches into what was not broken shows up here as a
  section whose shape moved, even if its numbers happen to be right.

The unify driver also records which stored functions changed around each
fire. That is evidence in the run record, never a score: the benchmark
asks what the report consumer sees, not how the arm is built.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from colleague.tracks.standing.repair_locality.fixture import (
    DEFAULT_PORT,
    DEFAULT_SEED,
    STREAMS,
    RepairLocalityFixture,
    build,
    expected_sections,
    score_report,
)
from colleague.tracks.standing.series.spec import (
    Experiment,
    OwnerMessage,
    outcome_for,
)

N_FIRES = 10
DRIFT_AFTER_FIRE = 4
RELEASE_PER_FIRE = {"orders": 24, "refunds": 9, "tickets": 15}

UTTERANCE_TEMPLATE = """\
Please set up an hourly recurring automation that posts an operations report \
from three local APIs at {base_url}.

Cursors: GET {base_url}/reports/last returns \
{{"orders_last_seq": A, "refunds_last_seq": B, "tickets_last_seq": C}} — the \
highest seq already reported for each stream (0 if none yet).

Streams (each returns rows with seq > N, ascending, up to 200):
- GET {base_url}/orders?after=A → seq (int), region (string), units (int), \
unit_price_cents (int)
- GET {base_url}/refunds?after=B → seq (int), order_seq (int), amount_cents \
(int), reason (string)
- GET {base_url}/tickets?after=C → seq (int), priority ("low" | "normal" | \
"high"), channel (string)

On each run: read the cursors, fetch every new row from each stream, and if \
all three are empty do nothing. Otherwise POST one JSON object to \
{base_url}/report with exactly these three keys, each an object with exactly \
these fields:
- orders: start_seq, end_seq, count, total_units, total_revenue_cents (sum \
of units * unit_price_cents)
- refunds: start_seq, end_seq, count, total_refunded_cents (sum of \
amount_cents)
- tickets: start_seq, end_seq, count, by_priority (object with keys low, \
normal, high mapping to counts, all three always present)

{owner_channel}

Set up the recurring hourly automation now. Do not process anything right \
now, and do not ask for confirmation.\
"""


class RepairLocality(Experiment):
    name = "repair_locality"
    env_prefix = "RL"
    directory = Path(__file__).resolve().parent
    n_fires = N_FIRES
    default_seed = DEFAULT_SEED
    default_port = DEFAULT_PORT
    fire_columns = ("drifted", "reports_delivered", "sections_correct")

    def describe(self) -> dict[str, Any]:
        return {
            "drift_after_fire": DRIFT_AFTER_FIRE,
            "release_per_fire": RELEASE_PER_FIRE,
            "drift": "refunds.amount_cents -> amount_minor (orders, tickets unchanged)",
        }

    def utterance(self, base_url: str) -> str:
        return UTTERANCE_TEMPLATE.format(
            base_url=base_url,
            owner_channel=self.owner_channel(base_url),
        )

    def build_fixture(self, *, seed: int, port: int) -> RepairLocalityFixture:
        return build(seed=seed, port=port)

    def before_fire(self, fixture: RepairLocalityFixture, i: int) -> list[str]:
        if i == DRIFT_AFTER_FIRE + 1:
            fixture.set_drift(True)
            return ["drift:refunds.amount_cents->amount_minor"]
        return []

    def prepare_fire(self, fixture: RepairLocalityFixture) -> dict[str, Any]:
        cursors = fixture.cursors()
        ranges = {}
        for name in STREAMS:
            before = cursors[f"{name}_last_seq"]
            released = fixture.streams[name].release(RELEASE_PER_FIRE[name])
            ranges[name] = (before + 1, released)
        return {
            "ranges": ranges,
            "reports_before": len(fixture.reports()),
            "pending": {k: list(v) for k, v in ranges.items()},
        }

    def score_fire(
        self,
        fixture: RepairLocalityFixture,
        ctx: dict[str, Any],
        *,
        messages: list[OwnerMessage],
    ) -> dict[str, Any]:
        delivered = fixture.reports()[ctx["reports_before"] :]
        expected = expected_sections(fixture.seed, ctx["ranges"])
        scored = [score_report(body, expected) for body in delivered]
        one = scored[0] if len(delivered) == 1 else None
        return {
            "drifted": fixture.streams["refunds"].transform is not None,
            "pending": ctx["pending"],
            "reports_delivered": len(delivered),
            "reports": delivered,
            "expected": expected,
            "sections_correct": one["sections_correct"] if one else None,
            "shapes": one["shapes"] if one else None,
            **outcome_for(
                delivered=len(delivered),
                exact=bool(one and one["exact"]),
                messages=messages,
            ),
        }

    def summarize(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Locality: untouched sections keep their pre-drift shape after recovery."""
        pre = [
            r for r in rows if int(r["fire"]) <= DRIFT_AFTER_FIRE and r.get("shapes")
        ]
        post = [
            r for r in rows if int(r["fire"]) > DRIFT_AFTER_FIRE and r.get("shapes")
        ]
        out: dict[str, Any] = {
            "recovered": any(r.get("correct") for r in post),
            "first_correct_after_drift": next(
                (int(r["fire"]) for r in post if r.get("correct")),
                None,
            ),
            "post_drift_correct": sum(1 for r in post if r.get("correct")),
            "post_drift_fires": len(
                [r for r in rows if int(r["fire"]) > DRIFT_AFTER_FIRE],
            ),
            "repair_tokens": sum(
                sum(
                    ((r.get("tokens") or {}).get("repair") or {}).get(k, 0)
                    for k in ("prompt", "completion")
                )
                for r in rows
            ),
        }
        if pre and post:
            reference = pre[-1]["shapes"]
            for name in ("orders", "tickets"):
                out[f"{name}_shape_identical_after_repair"] = all(
                    r["shapes"].get(name) == reference.get(name) for r in post
                )
        return out

    # -- scripted arm ------------------------------------------------------

    def mock_fire(self, *, client, fixture, i, mode, memory) -> None:
        from colleague.tracks.standing.series.mock_arm import hold

        cursors = client.get("/reports/last")
        rows = {
            name: client.get(f"/{name}?after={cursors[f'{name}_last_seq']}")
            for name in STREAMS
        }
        if all(not v for v in rows.values()):
            return
        refunds = rows["refunds"]
        if any("amount_cents" not in r for r in refunds):
            if mode == "naive":
                return  # the whole run dies on the refunds KeyError
            if mode == "held":
                hold(client, "refunds rows no longer carry amount_cents")
                return
            for r in refunds:
                r["amount_cents"] = r.pop("amount_minor")
        orders, tickets = rows["orders"], rows["tickets"]
        by_priority = {"low": 0, "normal": 0, "high": 0}
        for t in tickets:
            by_priority[t["priority"]] += 1
        client.post(
            "/report",
            {
                "orders": {
                    "start_seq": orders[0]["seq"],
                    "end_seq": orders[-1]["seq"],
                    "count": len(orders),
                    "total_units": sum(o["units"] for o in orders),
                    "total_revenue_cents": sum(
                        o["units"] * o["unit_price_cents"] for o in orders
                    ),
                },
                "refunds": {
                    "start_seq": refunds[0]["seq"],
                    "end_seq": refunds[-1]["seq"],
                    "count": len(refunds),
                    "total_refunded_cents": sum(r["amount_cents"] for r in refunds),
                },
                "tickets": {
                    "start_seq": tickets[0]["seq"],
                    "end_seq": tickets[-1]["seq"],
                    "count": len(tickets),
                    "by_priority": by_priority,
                },
            },
        )


def experiment() -> RepairLocality:
    return RepairLocality()
