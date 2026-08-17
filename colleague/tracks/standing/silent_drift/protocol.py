"""Silent drift: the API keeps its words and changes what they mean.

Ten fires, ``ORDERS_PER_FIRE`` new orders released before each. Before fire
5 the API drifts without a rename and without an error — ``amount`` in major
units instead of minor, or a page cap under the documented "every pending
order". A stored function that trusts the description keeps running and
keeps delivering: the numbers are simply wrong.

The measurement is which of three things happens from fire 5 on, per the
shared rubric — right numbers (2), a hold with a reason (1), or plausible
wrong numbers or silence (0) — and what each costs in tokens.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from colleague.tracks.standing.series.spec import (
    Experiment,
    OwnerMessage,
    outcome_for,
)
from colleague.tracks.standing.silent_drift.fixture import (
    DEFAULT_PAGE_LIMIT,
    DEFAULT_PORT,
    DEFAULT_SEED,
    VARIANTS,
    SilentDriftFixture,
    build,
    expected_batch,
    score_batch,
)

N_FIRES = 10
DRIFT_AFTER_FIRE = 4
ORDERS_PER_FIRE = 80

UTTERANCE_TEMPLATE = """\
Please set up an hourly recurring automation that processes new orders from \
the local orders API at {base_url}.

How it works: GET {base_url}/batches/last returns {{"last_seq": N}} — the \
highest order seq already processed (0 if none yet). \
GET {base_url}/orders?after=N returns every order with seq > N, ascending \
(a run never has more than {page_limit} pending), each with fields: \
seq (int), date (YYYY-MM-DD), region (string), units (int), \
amount (int — the order's total in minor units, i.e. cents).

On each run: read last_seq, fetch the orders after it, and if there are none \
do nothing. Otherwise compute exactly: batch_start_seq, batch_end_seq, \
order_count, total_units, total_amount_minor (sum of amount), \
amount_by_region_minor (object mapping each region to its amount sum), and \
POST that JSON object to {base_url}/batches with exactly these keys, all \
integers.

{owner_channel}

Set up the recurring hourly automation now. Do not process anything right \
now, and do not ask for confirmation.\
"""


class SilentDrift(Experiment):
    name = "silent_drift"
    env_prefix = "SD"
    directory = Path(__file__).resolve().parent
    n_fires = N_FIRES
    default_seed = DEFAULT_SEED
    default_port = DEFAULT_PORT
    fire_columns = ("drifted", "batches_delivered")

    def __init__(self, variant: str | None = None) -> None:
        self._variant = variant or os.environ.get("SD_VARIANT", "units")
        if self._variant not in VARIANTS:
            raise SystemExit(f"SD_VARIANT must be one of {VARIANTS}")

    def variant(self) -> str:
        return self._variant

    def describe(self) -> dict[str, Any]:
        return {
            "drift_after_fire": DRIFT_AFTER_FIRE,
            "orders_per_fire": ORDERS_PER_FIRE,
            "drift": (
                "amount: minor units (int) -> major units (float)"
                if self._variant == "units"
                else "page cap 100 -> 50 under 'returns every pending order'"
            ),
        }

    def utterance(self, base_url: str) -> str:
        return UTTERANCE_TEMPLATE.format(
            base_url=base_url,
            page_limit=DEFAULT_PAGE_LIMIT,
            owner_channel=self.owner_channel(base_url),
        )

    def build_fixture(self, *, seed: int, port: int) -> SilentDriftFixture:
        return build(seed=seed, port=port, variant=self._variant)

    def before_fire(self, fixture: SilentDriftFixture, i: int) -> list[str]:
        if i == DRIFT_AFTER_FIRE + 1:
            fixture.set_drift(True)
            return [f"drift:{self._variant}"]
        return []

    def prepare_fire(self, fixture: SilentDriftFixture) -> dict[str, Any]:
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
        fixture: SilentDriftFixture,
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
            "drifted": fixture.stream.transform is not None
            or fixture.stream.page_limit != DEFAULT_PAGE_LIMIT,
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
        if mode == "naive":
            # One fetch, amounts as served.
            pass
        else:
            # Keep paging: the description said "every pending order", so a
            # second non-empty page is itself a sign the description is off.
            more = client.get(f"/orders?after={rows[-1]['seq']}")
            if more:
                if mode == "held":
                    hold(client, "the orders API returned more than one page")
                    return
                while more:
                    rows.extend(more)
                    more = client.get(f"/orders?after={rows[-1]['seq']}")
            if any(not isinstance(r["amount"], int) for r in rows):
                if mode == "held":
                    hold(client, "amount is no longer an integer in minor units")
                    return
                for r in rows:
                    r["amount"] = int(round(r["amount"] * 100))
        by_region: dict[str, Any] = {}
        for r in rows:
            by_region[r["region"]] = by_region.get(r["region"], 0) + r["amount"]
        client.post(
            "/batches",
            {
                "batch_start_seq": rows[0]["seq"],
                "batch_end_seq": rows[-1]["seq"],
                "order_count": len(rows),
                "total_units": sum(r["units"] for r in rows),
                "total_amount_minor": sum(r["amount"] for r in rows),
                "amount_by_region_minor": by_region,
            },
        )


def experiment() -> SilentDrift:
    return SilentDrift()
