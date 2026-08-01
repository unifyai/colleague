"""Shared protocol for the drift-recovery experiment.

Both arms receive the identical utterance, the identical fire schedule, and
the identical scoring. A "fire" is: release ORDERS_PER_FIRE new orders into
the stream, trigger the system's recurring automation once, then score
whatever landed at the sink against ground truth for the pending seq range.
Drift (the ``unit_price_cents`` → ``unit_price_minor`` rename) is applied
after DRIFT_AFTER_FIRE fires have completed.
"""

from __future__ import annotations

from typing import Any

from colleague.tracks.standing.drift_recovery.fixture import (
    DriftFixtureServer,
    expected_batch,
    score_batch,
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

Set up the recurring hourly automation now. Do not process anything right \
now, and do not ask for confirmation.\
"""


def prepare_fire(fixture: DriftFixtureServer) -> tuple[int, int, int]:
    """Release new orders; returns (cursor_before, released_now, batches_before)."""
    cursor_before = fixture.stream.last_processed_seq()
    released_now = fixture.stream.release(ORDERS_PER_FIRE)
    batches_before = len(fixture.stream.snapshot_batches())
    return cursor_before, released_now, batches_before


def score_fire(
    fixture: DriftFixtureServer,
    *,
    cursor_before: int,
    released_now: int,
    batches_before: int,
) -> dict[str, Any]:
    """Score the fire: exactly one correctly-chained, exactly-correct batch."""
    delivered = fixture.stream.snapshot_batches()[batches_before:]
    expected = expected_batch(fixture.stream.seed, cursor_before + 1, released_now)
    scores = [score_batch(entry["body"], expected) for entry in delivered]
    return {
        "pending_range": [cursor_before + 1, released_now],
        "batches_delivered": len(delivered),
        "batches": [entry["body"] for entry in delivered],
        "expected_batch": expected,
        "scores": scores,
        "correct": len(delivered) == 1 and scores[0]["correct"],
    }
