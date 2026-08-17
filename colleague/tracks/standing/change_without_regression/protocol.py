"""Change without regression: add one column, keep every other byte.

Six fires. Fires 1–3 establish a correct steady state. Before fire 4 the
owner asks, in one message to every arm alike, for one more column in the
batch report. Fires 4–6 are scored on the new column being right *and* every
old column being byte-identical to what a correct report would have carried
anyway — the JSON encoding of each old value, and no other key added,
removed or renamed.

The cost of the change is the message phase (planning, or repair, or a
person's time) plus whatever the next fires cost; the risk of the change is
in the old columns.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from colleague.tracks.standing.change_without_regression.fixture import (
    DEFAULT_PORT,
    DEFAULT_SEED,
    NEW_COLUMN,
    OLD_COLUMNS,
    ChangeFixture,
    build,
    expected_batch,
    score_batch,
)
from colleague.tracks.standing.series.spec import (
    Experiment,
    OwnerMessage,
    outcome_for,
)

N_FIRES = 6
STEADY_FIRES = 3
ORDERS_PER_FIRE = 40

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
unit_price_cents), and POST that JSON object to {base_url}/batches with \
exactly these keys.

{owner_channel}

Set up the recurring hourly automation now. Do not process anything right \
now, and do not ask for confirmation.\
"""

CHANGE_REQUEST_TEMPLATE = """\
One change to the hourly order batches: add a column total_refunded_cents to \
each batch report — the sum of amount_cents over \
GET {base_url}/refunds?start_seq=<batch_start_seq>&end_seq=<batch_end_seq> \
(each row: order_seq (int), amount_cents (int); 0 if there are none). Keep \
every other column exactly as it is, in the same format. Do not process \
anything right now, and do not ask for confirmation.\
"""


class ChangeWithoutRegression(Experiment):
    name = "change_without_regression"
    env_prefix = "CWR"
    directory = Path(__file__).resolve().parent
    n_fires = N_FIRES
    default_seed = DEFAULT_SEED
    default_port = DEFAULT_PORT
    fire_columns = (
        "changed",
        "batches_delivered",
        "old_columns_identical",
        "new_column_correct",
    )

    def describe(self) -> dict[str, Any]:
        return {
            "steady_fires": STEADY_FIRES,
            "orders_per_fire": ORDERS_PER_FIRE,
            "change": f"add {NEW_COLUMN}; old columns {list(OLD_COLUMNS)} byte-identical",
        }

    def utterance(self, base_url: str) -> str:
        return UTTERANCE_TEMPLATE.format(
            base_url=base_url,
            owner_channel=self.owner_channel(base_url),
        )

    def build_fixture(self, *, seed: int, port: int) -> ChangeFixture:
        return build(seed=seed, port=port)

    def before_fire(self, fixture: ChangeFixture, i: int) -> list[str]:
        return ["change_requested"] if i == STEADY_FIRES + 1 else []

    def operator_messages(self, i: int, base_url: str) -> list[str]:
        if i == STEADY_FIRES + 1:
            return [CHANGE_REQUEST_TEMPLATE.format(base_url=base_url)]
        return []

    def prepare_fire(self, fixture: ChangeFixture) -> dict[str, Any]:
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
        fixture: ChangeFixture,
        ctx: dict[str, Any],
        *,
        messages: list[OwnerMessage],
    ) -> dict[str, Any]:
        with_refunds = int(ctx["fire"]) > STEADY_FIRES
        delivered = fixture.batches()[ctx["batches_before"] :]
        expected = expected_batch(
            fixture.seed,
            ctx["cursor_before"] + 1,
            ctx["released_now"],
            with_refunds=with_refunds,
        )
        scores = [
            score_batch(b, expected, with_refunds=with_refunds) for b in delivered
        ]
        one = scores[0] if len(delivered) == 1 else None
        return {
            "changed": with_refunds,
            "pending_range": ctx["pending"],
            "batches_delivered": len(delivered),
            "batches": delivered,
            "expected_batch": expected,
            "checks": one["checks"] if one else None,
            "old_columns_identical": bool(
                one and one["checks"].get("old_columns_identical"),
            ),
            "new_column_correct": (
                bool(one and one["checks"].get("new_column_correct"))
                if with_refunds
                else None
            ),
            **outcome_for(
                delivered=len(delivered),
                exact=bool(one and one["exact"]),
                messages=messages,
            ),
        }

    def summarize(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        steady = [r for r in rows if int(r["fire"]) <= STEADY_FIRES]
        after = [r for r in rows if int(r["fire"]) > STEADY_FIRES]
        return {
            "steady_state_reached": bool(steady)
            and all(r.get("correct") for r in steady),
            "new_column_correct_fires": sum(
                1 for r in after if r.get("new_column_correct")
            ),
            "old_columns_identical_fires": sum(
                1 for r in after if r.get("old_columns_identical")
            ),
            "post_change_fires": len(after),
            "regression_free": bool(after) and all(r.get("correct") for r in after),
        }

    # -- scripted arm ------------------------------------------------------

    def mock_operator_message(self, *, memory, i, text, mode) -> None:
        memory["change"] = (
            mode  # ideal adds the column; naive "adds" it and breaks another
        )

    def mock_fire(self, *, client, fixture, i, mode, memory) -> None:
        from colleague.tracks.standing.series.mock_arm import hold

        last = int(client.get("/batches/last")["last_seq"])
        rows = client.get(f"/orders?after={last}")
        if not rows:
            return
        change = memory.get("change")
        if change == "held":
            hold(
                client,
                "not sure how to add the refunds column without breaking the batch",
            )
            return
        batch: dict[str, Any] = {
            "batch_start_seq": rows[0]["seq"],
            "batch_end_seq": rows[-1]["seq"],
            "order_count": len(rows),
            "total_units": sum(r["units"] for r in rows),
            "total_revenue_cents": sum(
                r["units"] * r["unit_price_cents"] for r in rows
            ),
        }
        if change:
            refunds = client.get(
                f"/refunds?start_seq={rows[0]['seq']}&end_seq={rows[-1]['seq']}",
            )
            batch[NEW_COLUMN] = sum(r["amount_cents"] for r in refunds)
            if change == "naive":
                # The rewrite "tidied" the batch on the way: one old column
                # comes back as a float — right value, different bytes.
                batch["total_revenue_cents"] = float(batch["total_revenue_cents"])
        client.post("/batches", batch)


def experiment() -> ChangeWithoutRegression:
    return ChangeWithoutRegression()
