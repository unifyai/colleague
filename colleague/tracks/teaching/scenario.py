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
from colleague.harness.scoring import Scorecard, only_recipients
from colleague.tracks.teaching.fixture import (
    ACCOUNT_MANAGER,
    API_DOC,
    OVERDUE_THRESHOLD_DAYS,
    VIA_ACCOUNT_MANAGER,
    expected_reminders,
)

SESSION_SCOPE = "track"

DANIEL = Participant(
    id="daniel",
    name="Daniel Okafor",
    role="the person you work for",
    email="daniel@northwind.example",
)

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
            "name": "untaught_control",
            "request": (
                f"{api}\n\nRun the weekly invoice chase for week 32 — send "
                "reminders for the overdue invoices."
            ),
            "note": (
                "The control: no walkthrough, ever. Establishes what the API "
                "alone yields, so week 32's score can be read as retention "
                "rather than inference."
            ),
        },
    ]


def mock_plan(*, scenario: str, mode: str, client, memory, **_: Any) -> dict[str, Any]:
    week = 31 if scenario == "week_31_taught" else 32
    if scenario == "week_31_taught":
        memory["threshold"] = OVERDUE_THRESHOLD_DAYS
        memory["via_am"] = VIA_ACCOUNT_MANAGER
        memory["am"] = ACCOUNT_MANAGER

    taught = scenario != "untaught_control" and mode == "ideal"
    threshold = memory.get("threshold", 30) if taught else 30
    via_am = memory.get("via_am") if taught else None

    rows = client.get(f"/invoices?week={week}")
    sent = 0
    for row in rows:
        if row["days_overdue"] <= threshold:
            continue
        to = memory["am"] if (via_am and row["vendor"] == via_am) else row["contact"]
        client.post("/remind", {"to": to, "invoice_id": row["id"]})
        sent += 1
    return {"sent": sent}


def score(name: str, fixture: FixtureServer, **_: Any) -> ScenarioResult:
    week = 31 if name == "week_31_taught" else 32
    expected = expected_reminders(fixture.seed, week)
    got = only_recipients(fixture.recorder.all("remind"))

    card = Scorecard(name)
    card.check(
        "exact_recipients", got == expected, got=sorted(got), expected=sorted(expected)
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
