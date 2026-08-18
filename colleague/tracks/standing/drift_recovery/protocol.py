"""Shared protocol for the drift-recovery experiment.

Every arm receives the identical utterance, the identical fire schedule, and
the identical scoring. A "fire" is: release ORDERS_PER_FIRE new orders into
the stream, trigger the system's recurring automation once, then score
whatever landed at the sink against ground truth for the pending seq range.
Drift (the ``unit_price_cents`` → ``unit_price_minor`` rename) is applied
after DRIFT_AFTER_FIRE fires have completed.

The utterance is the one the published runs received, byte for byte: it
does not describe an owner channel, so for this experiment a *held* fire is
observable only where an arm's own runtime holds a run and says so
(recorded ``via="native"``). `silent_drift` is the experiment whose
utterance offers every arm the channel.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from colleague.tracks.standing.drift_recovery.fixture import (
    DEFAULT_PORT,
    DEFAULT_SEED,
    DriftFixtureServer,
    expected_batch,
    score_batch,
)
from colleague.tracks.standing.series.spec import (
    Experiment,
    OwnerMessage,
    outcome_for,
)

N_FIRES = 10
DRIFT_AFTER_FIRE = 4
ORDERS_PER_FIRE = 37

UTTERANCE_TEMPLATE = """\
Please set up an hourly recurring automation that processes new orders from \
the local orders API at {base_url}.

How it works: GET {base_url}/batches/last returns {{"last_seq": N}} — the \
highest order seq already processed (0 if none yet). \
GET {base_url}/orders?after=N returns the next orders with seq > N (up to \
200), each with fields: seq (int), date (YYYY-MM-DD), region, units (int), \
unit_price_cents (int).

On each run: read last_seq, fetch the orders after it, and if there are none \
do nothing. Otherwise compute exactly: batch_start_seq, batch_end_seq, \
order_count, total_units, total_revenue_cents (sum of units * \
unit_price_cents), revenue_by_region_cents (object mapping each region to \
its revenue sum), and POST that JSON object to {base_url}/batches with \
exactly these keys.

{owner_channel}

Set up the recurring hourly automation now. Do not process anything right \
now, and do not ask for confirmation.\
"""

OPERATOR_FIX_MESSAGE = (
    "The hourly order-processing automation you set up has been failing on "
    "its recent runs. Please investigate and fix it so it resumes working "
    "unattended, including catching up on anything it missed. Do not ask "
    "for confirmation."
)


class DriftRecovery(Experiment):
    name = "drift_recovery"
    env_prefix = "DR"
    directory = Path(__file__).resolve().parent
    n_fires = N_FIRES
    default_seed = DEFAULT_SEED
    default_port = DEFAULT_PORT
    operator_fix_after_failures = 2
    operator_fix_message = OPERATOR_FIX_MESSAGE
    fire_columns = ("drifted", "batches_delivered")

    def describe(self) -> dict[str, Any]:
        return {
            "drift_after_fire": DRIFT_AFTER_FIRE,
            "orders_per_fire": ORDERS_PER_FIRE,
            "drift": "unit_price_cents -> unit_price_minor",
        }

    def utterance(self, base_url: str) -> str:
        return UTTERANCE_TEMPLATE.format(
            base_url=base_url,
            owner_channel=self.owner_channel(base_url),
        )

    def build_fixture(self, *, seed: int, port: int) -> DriftFixtureServer:
        return DriftFixtureServer(seed=seed, port=port)

    def before_fire(self, fixture: DriftFixtureServer, i: int) -> list[str]:
        if i == DRIFT_AFTER_FIRE + 1:
            fixture.set_drift(True)
            return ["drift:unit_price_cents->unit_price_minor"]
        return []

    def prepare_fire(self, fixture: DriftFixtureServer) -> dict[str, Any]:
        cursor_before = fixture.last_seq()
        released_now = fixture.stream.release(ORDERS_PER_FIRE)
        return {
            "cursor_before": cursor_before,
            "released_now": released_now,
            "batches_before": len(fixture.batches()),
            "pending": [cursor_before + 1, released_now],
        }

    def score_fire(
        self,
        fixture: DriftFixtureServer,
        ctx: dict[str, Any],
        *,
        messages: list[OwnerMessage],
    ) -> dict[str, Any]:
        delivered = fixture.batches()[ctx["batches_before"] :]
        expected = expected_batch(
            fixture.seed,
            ctx["cursor_before"] + 1,
            ctx["released_now"],
        )
        scores = [score_batch(body, expected) for body in delivered]
        return {
            "drifted": fixture.stream.transform is not None,
            "pending_range": ctx["pending"],
            "batches_delivered": len(delivered),
            "batches": delivered,
            "expected_batch": expected,
            "scores": scores,
            **outcome_for(
                delivered=len(delivered),
                exact=len(delivered) == 1 and scores[0]["correct"],
                messages=messages,
            ),
        }

    # -- scripted arm ------------------------------------------------------

    def mock_fire(self, *, client, fixture, i, mode, memory) -> None:
        from colleague.tracks.standing.series.mock_arm import hold

        last = int(client.get("/batches/last")["last_seq"])
        rows = client.get(f"/orders?after={last}")
        if not rows:
            return
        if any("unit_price_cents" not in r for r in rows):
            if mode == "naive":
                return  # KeyError in a script nobody is watching: silence
            if mode == "held":
                hold(client, "orders no longer carry unit_price_cents")
                return
            for r in rows:
                r["unit_price_cents"] = r.pop("unit_price_minor")
        by_region: dict[str, int] = {}
        revenue = 0
        for r in rows:
            line = r["units"] * r["unit_price_cents"]
            revenue += line
            by_region[r["region"]] = by_region.get(r["region"], 0) + line
        client.post(
            "/batches",
            {
                "batch_start_seq": rows[0]["seq"],
                "batch_end_seq": rows[-1]["seq"],
                "order_count": len(rows),
                "total_units": sum(r["units"] for r in rows),
                "total_revenue_cents": revenue,
                "revenue_by_region_cents": by_region,
            },
        )


def experiment() -> DriftRecovery:
    return DriftRecovery()
