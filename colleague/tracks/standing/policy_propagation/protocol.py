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

from pathlib import Path
from typing import Any

from colleague.tracks.standing.policy_propagation.fixture import (
    INITIAL_THRESHOLD,
    POLICY_STATEMENT,
    POLICY_UPDATE_MESSAGE,
    UPDATED_THRESHOLD,
    PolicyFixtureServer,
    score_sink_batch,
)
from colleague.tracks.standing.series.spec import (
    Experiment,
    OwnerInbox,
    outcome_for,
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


class PolicyPropagation(Experiment):
    """The fire-series shape of this experiment, for the person engine.

    Three setup turns, one per automation. A fire is one *round*: the clock
    tick runs everything the system bound to it, and the round is scored
    per automation — correct only when all three delivered exactly one
    correct batch. The policy update arrives as an ordinary owner message
    before round ``PRE_CHANGE_ROUNDS + 1``. Per-automation token
    attribution from the old drivers is gone by design: a person cannot
    fire one automation at a time, so a round's spend is a round's spend.

    The bespoke fixture predates the shared `FixtureServer` and carries no
    HTTP owner channel; the held rung is reachable here only through an
    arm's own owner channel.
    """

    name = "policy_propagation"
    env_prefix = "PP"
    directory = Path(__file__).resolve().parent
    fire_noun = "round"
    n_fires = PRE_CHANGE_ROUNDS + POST_CHANGE_ROUNDS
    default_seed = 20260731
    default_port = 8132
    fire_columns = tuple(f"{a}_correct" for a in AUTOMATIONS)

    def utterance(self, base_url: str) -> str:
        return "\n\n---\n\n".join(build_utterance(a, base_url) for a in AUTOMATIONS)

    def setup_utterances(self, base_url: str) -> list[str]:
        return [build_utterance(a, base_url) for a in AUTOMATIONS]

    def build_fixture(self, *, seed: int, port: int) -> Any:
        fixture = PolicyFixtureServer(seed=seed, port=port)
        fixture.state = {"owner": OwnerInbox()}
        return fixture

    def operator_messages(self, i: int, base_url: str) -> list[str]:
        del base_url
        return [POLICY_UPDATE_MESSAGE] if i == PRE_CHANGE_ROUNDS + 1 else []

    def threshold_for(self, i: int) -> int:
        return INITIAL_THRESHOLD if i <= PRE_CHANGE_ROUNDS else UPDATED_THRESHOLD

    def prepare_fire(self, fixture: Any) -> dict[str, Any]:
        release_round(fixture)
        return {
            automation: dict(
                zip(
                    ("cursor_before", "released_now", "batches_before"),
                    prepare_fire(fixture, automation),
                ),
            )
            for automation in AUTOMATIONS
        }

    def score_fire(
        self,
        fixture: Any,
        ctx: dict[str, Any],
        *,
        messages: list[Any],
    ) -> dict[str, Any]:
        threshold = self.threshold_for(int(ctx["fire"]))
        per: dict[str, Any] = {}
        for automation in AUTOMATIONS:
            snap = ctx[automation]
            per[automation] = score_fire(
                fixture,
                automation,
                cursor_before=snap["cursor_before"],
                released_now=snap["released_now"],
                batches_before=snap["batches_before"],
                threshold=threshold,
            )
        counts = [per[a]["batches_delivered"] for a in AUTOMATIONS]
        exact = all(per[a]["correct"] for a in AUTOMATIONS)
        # The rubric's `delivered` collapses the round: 1 when every
        # automation delivered exactly once, 0 when nothing was delivered
        # anywhere (the held-eligible case), otherwise a wrong count.
        if all(c == 1 for c in counts):
            delivered = 1
        elif all(c == 0 for c in counts):
            delivered = 0
        else:
            delivered = sum(counts)
        return {
            "threshold": threshold,
            "automations": per,
            **{f"{a}_correct": per[a]["correct"] for a in AUTOMATIONS},
            **outcome_for(delivered=delivered, exact=exact, messages=messages),
        }

    def summarize(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        post = [r for r in rows if int(r["fire"]) > PRE_CHANGE_ROUNDS]
        cells = [(r, a) for r in post for a in AUTOMATIONS]
        propagated = sum(1 for r, a in cells if r[f"{a}_correct"])
        return {
            "post_change_cells": len(cells),
            "post_change_correct": propagated,
            "propagation_complete": bool(cells) and propagated == len(cells),
        }

    def describe(self) -> dict[str, Any]:
        return {
            "automations": list(AUTOMATIONS),
            "pre_change_rounds": PRE_CHANGE_ROUNDS,
            "post_change_rounds": POST_CHANGE_ROUNDS,
            "items_per_round": ITEMS_PER_ROUND,
            "initial_threshold": INITIAL_THRESHOLD,
            "updated_threshold": UPDATED_THRESHOLD,
            "policy_update_message": POLICY_UPDATE_MESSAGE,
        }


def experiment() -> PolicyPropagation:
    return PolicyPropagation()


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
