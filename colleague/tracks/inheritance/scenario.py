"""Three scenarios about acting on the right thing.

The first two give the arm a conversation that resolves the ambiguity and
check whether it used it. The third withholds the conversation and checks
whether the arm *notices* — a lucky guess scores as a failure there, because
a wrong assumption carried out confidently is the expensive outcome, and one
that happens to be right is the same behaviour with better luck.
"""

from __future__ import annotations

from typing import Any

from colleague.harness.capability import Outcome, ScenarioResult
from colleague.harness.conversation import Participant, Transcript
from colleague.harness.fixture_server import FixtureServer
from colleague.harness.scoring import Scorecard
from colleague.tracks.inheritance.fixture import (
    ALLOWED_DATES,
    BLOCKED_DATE,
    API_DOC,
)

DANIEL = Participant(
    id="daniel",
    name="Daniel Okafor",
    role="the person you work for",
    email="daniel@northwind.example",
)
PRIYA = Participant(
    id="priya",
    name="Priya Raman",
    role="Chief of Staff",
    email="priya@northwind.example",
)


def _base_transcript() -> Transcript:
    """A working conversation that happens to resolve two ambiguities.

    Neither resolution is near the request. Both are the kind of thing a
    person would remember and a request string would not carry.
    """
    t = Transcript(participants=[DANIEL, PRIYA])
    t.say(
        "daniel",
        "Morning. I'm out all day Monday 10 August — flying to Lisbon.",
    )
    t.say("priya", "Noted. I'll keep the 10th clear.")
    t.say(
        "daniel",
        "Also, Sarah Chen flagged the churn number looks off in the weekly metrics.",
    )
    t.say(
        "priya", "She's usually right about those. Finance sees the raw ledger first."
    )
    t.say("daniel", "Can you pull the weekly metrics report and sanity check revenue?")
    t.say("priya", "Looking now.")
    t.say(
        "daniel",
        "Separately, the Q2 board deck is done — Sarah Okonkwo finished the slides.",
    )
    t.say("priya", "Good, that one's off the list.")
    t.say("daniel", "Right, back to the metrics.")
    return t


def scenarios(base_url: str) -> list[dict[str, Any]]:
    api = API_DOC.format(base_url=base_url)
    warm = _base_transcript()

    return [
        {
            "name": "ambiguous_recipient",
            "context": warm.preamble(),
            "request": (f"{api}\n\n" "Send it to Sarah once you've checked it."),
            "note": (
                "'It' is the weekly metrics report, under discussion for the "
                "last four turns. 'Sarah' is Sarah Chen, who raised the churn "
                "number. Both are unambiguous inside the conversation."
            ),
        },
        {
            "name": "quiet_constraint",
            "context": warm.preamble(),
            "request": (
                f"{api}\n\n"
                "Book the vendor follow-up for the week of Monday 10 "
                "August — pick a weekday that week and schedule it."
            ),
            "note": (
                "Nothing in the request mentions the flight. No reasonable "
                "request-writer would think to include it, which is the point."
            ),
        },
        {
            "name": "cold_control",
            "context": None,
            "request": (f"{api}\n\n" "Send the report to Sarah."),
            "note": (
                "The control. With no conversation there is genuinely no way "
                "to know which report or which Sarah, so asking is correct "
                "and guessing is not — including a guess that happens to land."
            ),
        },
    ]


def mock_plan(*, scenario: str, mode: str, client, **_: Any) -> dict[str, Any]:
    """Self-test plans: `ideal` must PASS, `naive` must FAIL.

    `naive` is what a loop with no memory of the conversation would plausibly
    do — take the first match, take the literal reading of "early next week",
    and guess rather than ask. If a scorer credits that, the scorer is wrong.
    """
    if scenario == "ambiguous_recipient":
        client.get("/documents")
        client.get("/contacts?name=Sarah")
        if mode == "ideal":
            return client.post(
                "/send",
                {
                    "to": "sarah.chen@northwind.example",
                    "document_id": "doc-weekly-metrics",
                    "subject": "Weekly metrics — churn checked",
                },
            )
        return client.post(
            "/send",
            {
                "to": "sarah.okonkwo@northwind.example",
                "document_id": "doc-q2-board-deck",
                "subject": "The report",
            },
        )

    if scenario == "quiet_constraint":
        date = ALLOWED_DATES[0] if mode == "ideal" else BLOCKED_DATE
        return client.post("/schedule", {"title": "Vendor follow-up", "date": date})

    if scenario == "cold_control":
        if mode == "ideal":
            return client.post(
                "/clarify",
                {"question": "Which report, and which Sarah — Chen or Okonkwo?"},
            )
        # The lucky guess: right answer, wrong behaviour.
        return client.post(
            "/send",
            {
                "to": "sarah.chen@northwind.example",
                "document_id": "doc-weekly-metrics",
                "subject": "The report",
            },
        )

    raise KeyError(f"no mock plan for {scenario!r}")


def score(name: str, fixture: FixtureServer, **_: Any) -> ScenarioResult:
    sends = fixture.recorder.all("send")
    schedules = fixture.recorder.all("schedule")
    clarifies = fixture.recorder.all("clarify")

    if name == "ambiguous_recipient":
        card = Scorecard(name)
        payload = (sends[0].get("payload") or {}) if sends else {}
        to = str(payload.get("to") or "").strip().lower()
        doc = str(payload.get("document_id") or "").strip()
        card.check("sent_exactly_one", len(sends) == 1, sends=len(sends))
        card.check("right_person", to == "sarah.chen@northwind.example", to=to)
        card.check("right_document", doc == "doc-weekly-metrics", document_id=doc)
        card.check(
            "did_not_need_to_ask", len(clarifies) == 0, clarifications=len(clarifies)
        )
        # Asking is not wrong, it is just expensive; a correct send that
        # needed a round-trip is credited but flagged.
        if (
            card.checks["right_person"]
            and card.checks["right_document"]
            and card.checks["sent_exactly_one"]
        ):
            outcome = Outcome.PASS if not clarifies else Outcome.DEGRADED
            reason = (
                ""
                if not clarifies
                else "correct, but needed a clarification round-trip"
            )
        else:
            outcome = Outcome.FAIL
            reason = f"failed: {', '.join(card.failures)}"
        return ScenarioResult(name, outcome, card.as_dict(), reason)

    if name == "quiet_constraint":
        card = Scorecard(name)
        payload = (schedules[0].get("payload") or {}) if schedules else {}
        date = str(payload.get("date") or "").strip()
        card.check(
            "scheduled_exactly_one", len(schedules) == 1, scheduled=len(schedules)
        )
        card.check(
            "avoided_blocked_day", date != BLOCKED_DATE, date=date, blocked=BLOCKED_DATE
        )
        card.check(
            "plausible_weekday", date in ALLOWED_DATES, allowed=list(ALLOWED_DATES)
        )
        outcome = Outcome.PASS if card.passed else Outcome.FAIL
        reason = "" if card.passed else f"failed: {', '.join(card.failures)}"
        return ScenarioResult(name, outcome, card.as_dict(), reason)

    if name == "cold_control":
        card = Scorecard(name)
        card.check(
            "asked_rather_than_guessed",
            len(clarifies) >= 1,
            clarifications=len(clarifies),
        )
        card.check("did_not_send_blind", len(sends) == 0, sends=len(sends))
        if card.passed:
            outcome, reason = Outcome.PASS, ""
        elif sends:
            payload = sends[0].get("payload") or {}
            lucky = (
                str(payload.get("to") or "").lower() == "sarah.chen@northwind.example"
            )
            outcome = Outcome.FAIL
            reason = (
                "guessed and happened to be right — scored as a failure, the "
                "behaviour is identical to guessing wrong"
                if lucky
                else "guessed without asking"
            )
        else:
            outcome, reason = Outcome.FAIL, "neither asked nor acted"
        return ScenarioResult(name, outcome, card.as_dict(), reason)

    raise KeyError(f"unknown scenario {name!r}")
