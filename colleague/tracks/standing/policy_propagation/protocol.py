"""Shared protocol for the policy propagation experiment.

Three verbal requests set up three recurring automations over the same
inquiry stream, each stating the identical escalation policy verbatim. The
fire schedule: every automation fires twice under the initial policy, then
ONE natural-language policy-update message is delivered, then every
automation fires three more times — scored against the updated policy.

What this measures: where each architecture put the shared policy, what one
change costs to apply, and — the reliability number — whether every
automation actually behaves per the updated policy afterwards. A stale copy
anywhere shows up as wrong priorities/counts on that automation's
post-change fires.
"""

from __future__ import annotations

from typing import Any

from colleague.tracks.standing.policy_propagation.fixture import (
    POLICY_STATEMENT,
    PolicyFixtureServer,
    score_sink_batch,
)

AUTOMATIONS = ("triage", "digests", "audits")
PRE_CHANGE_ROUNDS = 2
POST_CHANGE_ROUNDS = 3
ITEMS_PER_ROUND = 10

UTTERANCES: dict[str, str] = {
    "triage": (
        "Please set up an hourly recurring automation that triages new "
        "customer inquiries from the local support API at {base_url}.\n\n"
        'How it works: GET {base_url}/triage/last returns {{"last_seq": N}} '
        "— the highest inquiry seq this triage automation has already "
        "processed (0 if none yet). GET {base_url}/inquiries?after=N returns "
        "the next inquiries with seq > N (up to 200), each with fields: seq "
        "(int) and text (str).\n\n"
        "On each run: read last_seq, fetch the inquiries after it, and if "
        "there are none do nothing. Otherwise, for each inquiry decide its "
        'category — "refund" (they want money back for a charge), "bug" '
        "(something in the product is broken or not working correctly), "
        '"sales" (they want to buy, upgrade, get a quote, or discuss '
        'pricing), or "other" (anything else) — and its priority per our '
        "policy below.\n\n"
        "{policy}\n\n"
        'Priority is "urgent" or "normal" accordingly.\n\n'
        "POST the result to {base_url}/triage as a JSON object with exactly "
        "these keys: batch_start_seq (int), batch_end_seq (int), and "
        'classifications — a list of {{"seq": int, "category": str, '
        '"priority": str}} covering every fetched inquiry exactly once.\n\n'
        "Set up the recurring hourly automation now. Do not triage anything "
        "right now, and do not ask for confirmation."
    ),
    "digests": (
        "Please set up a daily recurring automation that summarizes urgent "
        "customer inquiries from the local support API at {base_url}.\n\n"
        'How it works: GET {base_url}/digests/last returns {{"last_seq": '
        "N}} — the highest inquiry seq this digest automation has already "
        "covered (0 if none yet). GET {base_url}/inquiries?after=N returns "
        "the next inquiries with seq > N (up to 200), each with fields: seq "
        "(int) and text (str).\n\n"
        "On each run: read last_seq, fetch the inquiries after it, and if "
        "there are none do nothing. Otherwise determine which inquiries are "
        "urgent per our policy below, and which category each urgent inquiry "
        'belongs to — "refund" (they want money back for a charge), '
        '"bug" (something broken or not working), "sales" (buying, '
        'upgrading, quotes, pricing), or "other".\n\n'
        "{policy}\n\n"
        "POST the digest to {base_url}/digests as a JSON object with exactly "
        "these keys: batch_start_seq (int), batch_end_seq (int), "
        "urgent_by_category — an object with keys refund, bug, sales, other "
        "and integer counts of urgent inquiries — and urgent_total (int, the "
        "sum of those counts).\n\n"
        "Set up the recurring daily automation now. Do not process anything "
        "right now, and do not ask for confirmation."
    ),
    "audits": (
        "Please set up a weekly recurring automation that audits escalation "
        "volume from the local support API at {base_url}.\n\n"
        'How it works: GET {base_url}/audits/last returns {{"last_seq": '
        "N}} — the highest inquiry seq this audit automation has already "
        "covered (0 if none yet). GET {base_url}/inquiries?after=N returns "
        "the next inquiries with seq > N (up to 200), each with fields: seq "
        "(int) and text (str).\n\n"
        "On each run: read last_seq, fetch the inquiries after it, and if "
        "there are none do nothing. Otherwise count how many are urgent per "
        "our policy below.\n\n"
        "{policy}\n\n"
        "POST the audit to {base_url}/audits as a JSON object with exactly "
        "these keys: batch_start_seq (int), batch_end_seq (int), "
        "urgent_count (int), total_count (int), and urgent_fraction (float, "
        "urgent_count / total_count rounded to 2 decimal places).\n\n"
        "Set up the recurring weekly automation now. Do not process anything "
        "right now, and do not ask for confirmation."
    ),
}


def build_utterance(automation: str, base_url: str) -> str:
    return UTTERANCES[automation].format(base_url=base_url, policy=POLICY_STATEMENT)


def release_round(fixture: PolicyFixtureServer) -> int:
    """Advance the shared stream once per round; all three automations then
    fire against the same released frontier, so after the first round each
    processes exactly ITEMS_PER_ROUND fresh seqs per round."""
    return fixture.stream.release(ITEMS_PER_ROUND)


def prepare_fire(
    fixture: PolicyFixtureServer,
    sink: str,
) -> tuple[int, int, int]:
    """Snapshot one automation's pending range; returns
    (cursor_before, released_now, batches_before)."""
    cursor_before = fixture.stream.last_processed_seq(sink)
    released_now = fixture.stream.released_seq
    batches_before = len(fixture.stream.snapshot(sink))
    return cursor_before, released_now, batches_before


def score_fire(
    fixture: PolicyFixtureServer,
    sink: str,
    *,
    cursor_before: int,
    released_now: int,
    batches_before: int,
    threshold: int,
) -> dict[str, Any]:
    delivered = fixture.stream.snapshot(sink)[batches_before:]
    scores = [
        score_sink_batch(
            sink,
            entry["body"],
            seed=fixture.stream.seed,
            start=cursor_before + 1,
            end=released_now,
            threshold=threshold,
        )
        for entry in delivered
    ]
    correct = len(delivered) == 1 and scores[0]["contract_correct"]
    return {
        "pending_range": [cursor_before + 1, released_now],
        "batches_delivered": len(delivered),
        "batches": [entry["body"] for entry in delivered],
        "scores": [{k: v for k, v in s.items() if k != "expected"} for s in scores],
        "expected": scores[0]["expected"] if scores else None,
        "correct": correct,
        "accuracy": scores[0]["accuracy"] if len(delivered) == 1 else 0.0,
    }
