"""Walk through it once, then ask for it again.

Week 31 is taught: the walkthrough states both exceptions, and any arm that
follows instructions will get it right. Week 32 is the measurement, and the
request deliberately restates nothing — "run the invoice chase for week 32"
is what a follow-up actually looks like.

An arm that kept the procedure applies both exceptions again. An arm that
did not will do the obvious thing: chase everyone over thirty days, directly,
including the vendor who is supposed to be handled through their account
manager. Both exceptions are absent from the API, so there is no way to
rediscover them.

The third scenario is the honest control. It teaches nothing and asks for
week 32 cold, which establishes what the API alone gets you. If an arm scores
the same on `untaught_control` as on `week_32_replay`, its second-week success
was not retention.
"""

from __future__ import annotations

from typing import Any

from colleague.harness.capability import Outcome, ScenarioResult
from colleague.harness.conversation import Participant, Transcript
from colleague.harness.fixture_server import FixtureServer
from colleague.harness.interlocutor import ScriptedTurn
from colleague.harness.scoring import Scorecard, only_recipients
from colleague.tracks.teaching.fixture import (
    ACCOUNT_MANAGER,
    API_DOC,
    OVERDUE_THRESHOLD_DAYS,
    VIA_ACCOUNT_MANAGER,
    expected_reminders,
    payment_plan_contacts,
)

SESSION_SCOPE = "track"

DANIEL = Participant(
    id="daniel",
    name="Daniel Okafor",
    role="the person you work for",
    email="daniel@northwind.example",
)

#: The scenario's full cast, for arms that maintain a real contact
#: store: the runner seeds these so the environment contains the
#: people the roster text describes.
PARTICIPANTS = [DANIEL]

WALKTHROUGH = f"""\
Let me show you how I do the weekly invoice chase, then you can take it over.

Pull the invoices for the week. Anything more than {OVERDUE_THRESHOLD_DAYS} \
days overdue gets a reminder — not thirty, we relaxed it last year because \
half our vendors bill on net-45 and it was generating noise.

One exception: {VIA_ACCOUNT_MANAGER}. Never chase them directly. Their AP \
inbox is a black hole and their account manager, {ACCOUNT_MANAGER}, actually \
answers. Anything of theirs goes to her instead.

Everything else goes to the contact on the invoice. One reminder per invoice.\
"""


def scenarios(base_url: str) -> list[dict[str, Any]]:
    api = API_DOC.format(base_url=base_url)
    roster = Transcript(participants=[DANIEL]).roster()
    return [
        {
            "name": "week_31_taught",
            "context": roster,
            "request": f"{api}\n\n{WALKTHROUGH}\n\nGo ahead and run it for week 31.",
            "persist": True,
            "sender": "daniel",
            "note": "Taught. Any arm following instructions should get this right.",
        },
        {
            "name": "week_32_replay",
            "request": "Run the invoice chase for week 32.",
            "continue": True,
            "sender": "daniel",
            "note": (
                "The measurement. Nothing is restated — not the threshold, "
                "not the exception, not the API."
            ),
        },
        {
            "name": "week_33_corrected",
            "request": "Run the invoice chase for week 33.",
            "continue": True,
            "sender": "daniel",
            "note": (
                "A third rule arrives as a correction after the first reminder "
                "has gone: don't chase anyone on a payment plan. Progress kept, "
                "remainder corrected."
            ),
        },
        {
            "name": "week_34_replay_after_correction",
            "request": "Run the invoice chase for week 34.",
            "continue": True,
            "sender": "daniel",
            "note": (
                "The measurement for the correction: nothing restated. A "
                "colleague who was corrected last week does not need telling "
                "again."
            ),
        },
        {
            "name": "untaught_control",
            "request": (
                f"{api}\n\nRun the weekly invoice chase for week 32 — send "
                "reminders for the overdue invoices."
            ),
            "fresh_session": True,
            "note": (
                "The control: no walkthrough, ever, in a session that never "
                "saw one. It ran third in the shared session and passed by "
                "remembering, which made the taught result unreadable — a "
                "control contaminated by the thing it controls for is worse "
                "than no control."
            ),
        },
    ]


def turns(name: str) -> list[ScriptedTurn]:
    if name != "week_33_corrected":
        return []
    return [
        ScriptedTurn(
            label="correction",
            sender="daniel",
            text=(
                "Oh — one more thing, from now on: anyone on a payment plan "
                "(the API shows it) doesn't get chased at all. Skip them."
            ),
            waypoint="remind",
            nth=1,
            timeout=240,
        ),
    ]


_WEEK = {
    "week_31_taught": 31,
    "week_32_replay": 32,
    "week_33_corrected": 33,
    "week_34_replay_after_correction": 34,
    "untaught_control": 32,
}


def mock_plan(
    *,
    scenario: str,
    mode: str,
    client,
    memory,
    corrections,
    **_: Any,
) -> dict[str, Any]:
    week = _WEEK[scenario]
    if scenario == "week_31_taught":
        memory["threshold"] = OVERDUE_THRESHOLD_DAYS
        memory["via_am"] = VIA_ACCOUNT_MANAGER
        memory["am"] = ACCOUNT_MANAGER

    taught = scenario != "untaught_control" and mode == "ideal"
    threshold = memory.get("threshold", 30) if taught else 30
    via_am = memory.get("via_am") if taught else None
    # A correction heard last week stays learned — for the arm that keeps it.
    skip_pp = bool(memory.get("skip_payment_plan")) if mode == "ideal" else False

    rows = client.get(f"/invoices?week={week}")
    sent = 0
    for row in rows:
        if row["days_overdue"] <= threshold:
            continue
        # Mid-run: has the correction arrived? Only the ideal arm listens.
        if mode == "ideal" and any(
            "payment plan" in c["text"].lower() for c in corrections
        ):
            memory["skip_payment_plan"] = True
            skip_pp = True
        if skip_pp and row["payment_plan"]:
            continue
        to = memory["am"] if (via_am and row["vendor"] == via_am) else row["contact"]
        client.post("/remind", {"to": to, "invoice_id": row["id"]})
        sent += 1
    return {"sent": sent}


def score(
    name: str,
    fixture: FixtureServer,
    *,
    record: dict[str, Any] | None = None,
    **_: Any,
) -> ScenarioResult:
    week = _WEEK[name]
    reminders = fixture.recorder.all("remind")
    got = only_recipients(reminders)
    card = Scorecard(name)

    if name == "week_33_corrected":
        journal = (record or {}).get("interlocutor", []) or []
        entry = next((e for e in journal if e.get("label") == "correction"), None)
        mode = str((entry or {}).get("mode") or "")
        if mode == "unsupported":
            return ScenarioResult(
                name,
                Outcome.UNSUPPORTED,
                {"reminders": len(reminders)},
                "no channel exists to reach work that has already started",
            )
        if not entry or not entry.get("delivered"):
            return ScenarioResult(
                name,
                Outcome.ERROR,
                {
                    "reminders": len(reminders),
                    "delivery_mode": mode or "no journal entry",
                },
                "the correction was never offered — nothing about learning was measured",
            )
        correction_seq = int(entry.get("recorder_seq") or 0)
        pp = payment_plan_contacts(fixture.seed, week)
        after = [r for r in reminders if r["seq"] > correction_seq]
        pp_after = sorted(only_recipients(after) & pp)
        needed = expected_reminders(fixture.seed, week, skip_payment_plan=True)
        card.check(
            "no_payment_plan_reminder_after_correction",
            not pp_after,
            sent_after=pp_after,
        )
        card.check(
            "everyone_else_still_reached",
            needed <= got,
            missing=sorted(needed - got),
        )
        dup = [r for r in reminders]
        card.check(
            "nobody_reminded_twice",
            len({str((r.get("payload") or {}).get("to", "")).lower() for r in dup})
            == len(dup),
        )
        card.check(
            "used_the_account_manager_route",
            ACCOUNT_MANAGER in got or ACCOUNT_MANAGER not in needed,
        )
        card.evidence["correction_seq"] = correction_seq
        card.evidence["reminder_seqs"] = [r["seq"] for r in reminders]
        outcome = Outcome.PASS if card.passed else Outcome.FAIL
        return ScenarioResult(
            name,
            outcome,
            card.as_dict(),
            "" if card.passed else f"failed: {', '.join(card.failures)}",
        )

    expected = expected_reminders(
        fixture.seed,
        week,
        skip_payment_plan=(name == "week_34_replay_after_correction"),
    )
    card.check(
        "exact_recipients",
        got == expected,
        got=sorted(got),
        expected=sorted(expected),
    )
    card.check(
        "used_the_account_manager_route",
        ACCOUNT_MANAGER in got or ACCOUNT_MANAGER not in expected,
    )
    card.evidence["reminders"] = len(fixture.recorder.all("remind"))

    if name == "untaught_control":
        # This one is expected to fail for everybody. It is a calibration
        # point, not a test of the arm, so a miss is reported as UNSUPPORTED
        # of the information rather than as a failure of the harness.
        if card.passed:
            return ScenarioResult(
                name,
                Outcome.PASS,
                card.as_dict(),
                "guessed both exceptions from the API alone — week 32 cannot "
                "be read as retention for this arm",
            )
        return ScenarioResult(
            name,
            Outcome.UNSUPPORTED,
            card.as_dict(),
            "as designed: the exceptions are not discoverable without being told",
        )

    outcome = Outcome.PASS if card.passed else Outcome.FAIL
    return ScenarioResult(
        name,
        outcome,
        card.as_dict(),
        "" if card.passed else f"failed: {', '.join(card.failures)}",
    )
