"""Shared protocol for the semantic triage experiment.

Both arms receive the identical utterance and fire schedule. A fire releases
ITEMS_PER_FIRE new inquiries, triggers the system's automation once, and
scores whatever landed at the sink: contract exactness (chaining, coverage,
closed category set) and per-item classification accuracy against golden
labels. No drift event — this experiment measures the steady-state cost and
reliability of recurring work that contains a genuine judgment substep.
"""

from __future__ import annotations

from typing import Any

from colleague.tracks.standing.semantic_triage.fixture import (
    TriageFixtureServer,
    score_triage_batch,
)

N_FIRES = 8
ITEMS_PER_FIRE = 12

UTTERANCE_TEMPLATE = """\
Please set up an hourly recurring automation that triages new customer \
inquiries from the local support API at {base_url}.

How it works: GET {base_url}/batches/last returns {{"last_seq": N}} — the \
highest inquiry seq already triaged (0 if none yet). \
GET {base_url}/inquiries?after=N returns the next inquiries with seq > N \
(up to 200), each with fields: seq (int) and text (str).

On each run: read last_seq, fetch the inquiries after it, and if there are \
none do nothing. Otherwise classify each inquiry into exactly one category \
based on what the customer needs: "refund" (they want money back for \
something they were charged), "bug" (something in the product is broken or \
not working correctly), "sales" (they want to buy, upgrade, get a quote, or \
discuss pricing), or "other" (anything else). Classification must be based \
on understanding the request, not on keyword matching — inquiries are \
worded in many different ways.

POST the result to {base_url}/batches as a JSON object with exactly these \
keys: batch_start_seq (int), batch_end_seq (int), and classifications — a \
list of {{"seq": int, "category": str}} covering every fetched inquiry \
exactly once.

Set up the recurring hourly automation now. Do not triage anything right \
now, and do not ask for confirmation.\
"""


def prepare_fire(fixture: TriageFixtureServer) -> tuple[int, int, int]:
    """Release new inquiries; returns (cursor_before, released_now, batches_before)."""
    cursor_before = fixture.stream.last_processed_seq()
    released_now = fixture.stream.release(ITEMS_PER_FIRE)
    batches_before = len(fixture.stream.snapshot_batches())
    return cursor_before, released_now, batches_before


def score_fire(
    fixture: TriageFixtureServer,
    *,
    cursor_before: int,
    released_now: int,
    batches_before: int,
) -> dict[str, Any]:
    delivered = fixture.stream.snapshot_batches()[batches_before:]
    scores = [
        score_triage_batch(
            entry["body"],
            seed=fixture.stream.seed,
            start_seq=cursor_before + 1,
            end_seq=released_now,
        )
        for entry in delivered
    ]
    contract_correct = len(delivered) == 1 and scores[0]["contract_correct"]
    return {
        "pending_range": [cursor_before + 1, released_now],
        "batches_delivered": len(delivered),
        "batches": [entry["body"] for entry in delivered],
        "scores": scores,
        "correct": contract_correct,
        "accuracy": scores[0]["accuracy"] if len(delivered) == 1 else 0.0,
    }
