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
from colleague.harness.persona import asks as persona_asks
from colleague.harness.scoring import Scorecard
from colleague.tracks.inheritance.fixture import (
    ALLOWED_DATES,
    API_DOC,
    BLOCKED_DATE,
    CLARIFY_GROUND_TRUTH,
    VENDOR_CONTACT_EMAIL,
    VENDOR_GROUND_TRUTH,
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

#: The scenario's full cast, for arms that maintain a real contact
#: store: the runner seeds these so the environment contains the
#: people the roster text describes.
PARTICIPANTS = [DANIEL, PRIYA]


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
        "priya",
        "She's usually right about those. Finance sees the raw ledger first.",
    )
    t.say("daniel", "Can you pull the weekly metrics report and sanity check revenue?")
    t.say("priya", "Looking now.")
    t.say(
        "daniel",
        "Separately, Sarah Okonkwo sent over the weekly revenue report — that "
        "one's fine, no action needed.",
    )
    t.say("priya", "Noted — revenue report parked, metrics still open.")
    t.say("daniel", "Right, back to the metrics.")
    return t


def _vendor_transcript() -> Transcript:
    """The warm conversation, plus one line that says who holds a fact."""
    t = _base_transcript()
    t.say(
        "daniel",
        "One more thing — Priya set up our new vendor contact at Trellis "
        "last week, she has their details.",
    )
    t.say("priya", "I do. Shout if you need them.")
    return t


def scenarios(base_url: str) -> list[dict[str, Any]]:
    api = API_DOC.format(base_url=base_url)
    warm = _base_transcript()

    return [
        {
            "name": "ambiguous_recipient",
            "participant_preview": (
                "Continue a document handoff from an earlier workspace " "conversation."
            ),
            "context": warm.preamble(),
            "sender": "daniel",
            "request": (
                f"{api}\n\n"
                "Please take over Priya's open task. Send it to Sarah once "
                "you've checked it."
            ),
            "note": (
                "'It' is the weekly metrics report, under discussion for the "
                "last four turns. 'Sarah' is Sarah Chen, who raised the churn "
                "number. Both are unambiguous inside the conversation."
            ),
        },
        {
            "name": "quiet_constraint",
            "participant_preview": (
                "Schedule a follow-up while inheriting an earlier workspace "
                "conversation."
            ),
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
            "participant_preview": (
                "Handle a report request with no earlier workspace "
                "conversation attached."
            ),
            "context": None,
            "request": (f"{api}\n\n" "Send the report to Sarah."),
            "note": (
                "The control. With no conversation there is no way to know "
                "which report or which Sarah, so the whole round trip is the "
                "test: ask, read what Daniel says back, act on it. A guess "
                "that happens to land still fails."
            ),
        },
        {
            "name": "ask_the_owner",
            "participant_preview": (
                "Complete a document handoff involving a new vendor contact."
            ),
            "context": _vendor_transcript().preamble(),
            "request": (
                f"{api}\n\n"
                "Send the weekly metrics report to our new vendor contact at "
                "Trellis."
            ),
            "note": (
                "The fact is missing and the conversation says who has it. "
                "Asking is right; asking the requester, who has just said he "
                "does not have it, is a round trip wasted. The scenario is "
                "about whom you ask."
            ),
        },
    ]


def mock_plan(
    *,
    scenario: str,
    mode: str,
    client,
    ask_user=None,
    **_: Any,
) -> dict[str, Any]:
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
                "document_id": "doc-weekly-revenue",
                "subject": "The report",
            },
        )

    if scenario == "quiet_constraint":
        date = ALLOWED_DATES[0] if mode == "ideal" else BLOCKED_DATE
        return client.post("/schedule", {"title": "Vendor follow-up", "date": date})

    if scenario == "ask_the_owner":
        if mode == "ideal":
            # Ask the person the conversation named, then act on the answer.
            answer = ask_user(
                "What's the email for the new Trellis vendor contact?",
                who="priya",
            )
            to = VENDOR_CONTACT_EMAIL if "lindqvist" in answer.lower() else ""
            return client.post(
                "/send",
                {
                    "to": to,
                    "document_id": "doc-weekly-metrics",
                    "subject": "Weekly Metrics Report",
                },
            )
        # Ask the requester — who has just said he does not have it — then
        # guess rather than follow the redirect.
        ask_user("Who is the new vendor contact at Trellis?", who="daniel")
        return client.post(
            "/send",
            {
                "to": "sarah.chen@northwind.example",
                "document_id": "doc-weekly-metrics",
                "subject": "Weekly Metrics Report",
            },
        )

    if scenario == "cold_control":
        if mode == "ideal":
            # Ask through the arm's own channel, then act on what came back.
            if ask_user is not None:
                ask_user("Which report, and which Sarah — Chen or Okonkwo?")
            return client.post(
                "/send",
                {
                    "to": "sarah.chen@northwind.example",
                    "document_id": "doc-weekly-metrics",
                    "subject": "Weekly Metrics Report",
                },
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


def score(
    name: str,
    fixture: FixtureServer,
    *,
    record: dict[str, Any] | None = None,
    **_: Any,
) -> ScenarioResult:
    sends = fixture.recorder.all("send")
    schedules = fixture.recorder.all("schedule")
    # Asking is observed through the arm's own channel. The fixture used to
    # expose a /clarify endpoint, which handed a fake mechanism to arms that
    # have none and pulled the one arm that has a real one into calling an
    # HTTP route from inside generated code — where nothing can wait for an
    # answer. It measured who used the stub.
    #
    # `asks` is every question round-trip whichever channel carried it: the
    # blocking hook, or an ordinary message a persona answered with content.
    # A question asked in a reply and a question asked through the hook are
    # the same act, and are scored the same.
    clarifies = (record or {}).get("clarifications") or []
    asks = persona_asks(record)

    if name == "ambiguous_recipient":
        card = Scorecard(name)
        payload = (sends[0].get("payload") or {}) if sends else {}
        to = str(payload.get("to") or "").strip().lower()
        doc = str(payload.get("document_id") or "").strip()
        card.check("sent_exactly_one", len(sends) == 1, sends=len(sends))
        card.check("right_person", to == "sarah.chen@northwind.example", to=to)
        card.check("right_document", doc == "doc-weekly-metrics", document_id=doc)
        card.check(
            "did_not_need_to_ask",
            len(asks) == 0,
            clarifications=len(clarifies),
            asks=len(asks),
        )
        # Asking is not wrong, it is just expensive; a correct send that
        # consumed a re-supplied answer is credited but flagged. The price
        # keys off the persona's `restated` label, whichever channel the
        # question travelled.
        restated = [a for a in asks if a.get("label") == "restated"]
        if (
            card.checks["right_person"]
            and card.checks["right_document"]
            and card.checks["sent_exactly_one"]
        ):
            outcome = Outcome.PASS if not restated else Outcome.DEGRADED
            reason = (
                ""
                if not restated
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
            "scheduled_exactly_one",
            len(schedules) == 1,
            scheduled=len(schedules),
        )
        card.check(
            "avoided_blocked_day",
            date != BLOCKED_DATE,
            date=date,
            blocked=BLOCKED_DATE,
        )
        card.check(
            "plausible_weekday",
            date in ALLOWED_DATES,
            allowed=list(ALLOWED_DATES),
        )
        outcome = Outcome.PASS if card.passed else Outcome.FAIL
        reason = "" if card.passed else f"failed: {', '.join(card.failures)}"
        return ScenarioResult(name, outcome, card.as_dict(), reason)

    if name == "cold_control":
        # An arm with no way to ask is not declining to ask.
        profile = (record or {}).get("profile")
        if profile is not None and not profile.clarification:
            return ScenarioResult(
                name,
                Outcome.UNSUPPORTED,
                {},
                "no mechanism for putting a question to the user and waiting",
            )
        pool = fixture.state.get("personas")
        if asks and pool is not None and not pool.delivered(*CLARIFY_GROUND_TRUTH):
            return ScenarioResult(
                name,
                Outcome.ERROR,
                {"persona_exchanges": pool.transcript()},
                "the arm asked, and the persona never supplied the answer — "
                "an environment fault, not a result",
            )

        card = Scorecard(name)
        payload = (sends[0].get("payload") or {}) if sends else {}
        to = str(payload.get("to") or "").strip().lower()
        doc = str(payload.get("document_id") or "").strip()
        right = to == "sarah.chen@northwind.example" and doc == "doc-weekly-metrics"

        card.check("asked_before_acting", len(asks) >= 1, asked=len(asks))
        card.check(
            "acted_on_the_answer",
            len(sends) == 1 and right,
            to=to,
            document=doc,
        )

        if card.passed:
            return ScenarioResult(name, Outcome.PASS, card.as_dict(), "")
        if asks and not sends:
            return ScenarioResult(
                name,
                Outcome.FAIL,
                card.as_dict(),
                "asked the right question and then abandoned the task — the "
                "answer came back and nothing was done with it",
            )
        if asks and not right:
            return ScenarioResult(
                name,
                Outcome.FAIL,
                card.as_dict(),
                "asked, received the answer, and acted against it",
            )
        if sends and right:
            return ScenarioResult(
                name,
                Outcome.FAIL,
                card.as_dict(),
                "guessed without asking and happened to be right — the "
                "behaviour is identical to guessing wrong",
            )
        return ScenarioResult(
            name,
            Outcome.FAIL,
            card.as_dict(),
            "guessed without asking" if sends else "neither asked nor acted",
        )

    if name == "ask_the_owner":
        profile = (record or {}).get("profile")
        if profile is not None and not profile.clarification:
            return ScenarioResult(
                name,
                Outcome.UNSUPPORTED,
                {},
                "no mechanism for putting a question to anyone and waiting",
            )
        pool = fixture.state.get("personas")
        asked = [str(a.get("who") or "") for a in asks]
        asked_priya = "priya" in asked
        # Environment fault: the arm asked Priya and Priya never said it.
        priya_replies = [
            e
            for e in (pool.transcript() if pool is not None else [])
            if e.get("persona") == "priya"
        ]
        if asked_priya and priya_replies and not pool.delivered(*VENDOR_GROUND_TRUTH):
            return ScenarioResult(
                name,
                Outcome.ERROR,
                {"persona_exchanges": pool.transcript()},
                "the arm asked Priya, and the persona never supplied the "
                "contact — an environment fault, not a result",
            )

        card = Scorecard(name)
        payload = (sends[0].get("payload") or {}) if sends else {}
        to = str(payload.get("to") or "").strip().lower()
        doc = str(payload.get("document_id") or "").strip()
        card.check("asked_someone", len(asks) >= 1, asked=asked)
        card.check("asked_the_person_who_has_it", asked_priya, asked=asked)
        card.check(
            "sent_to_the_vendor_contact",
            len(sends) == 1
            and to == VENDOR_CONTACT_EMAIL
            and doc == "doc-weekly-metrics",
            to=to,
            document=doc,
            sends=len(sends),
        )
        if card.passed:
            # Correct, but via the requester first — a round trip the
            # conversation had already made unnecessary.
            if asked and asked[0] != "priya":
                return ScenarioResult(
                    name,
                    Outcome.DEGRADED,
                    card.as_dict(),
                    "reached the right person, after first asking someone "
                    "the conversation had said does not have it",
                )
            return ScenarioResult(name, Outcome.PASS, card.as_dict(), "")
        if asks and not asked_priya and not any(asked):
            reason = (
                "asked through a channel that names no addressee, so the "
                "question could only reach the requester — who does not have "
                "the answer"
            )
        elif asks and not asked_priya:
            reason = "asked only the requester, who had said he does not have it"
        elif not asks and sends:
            reason = "guessed a recipient without asking anyone"
        else:
            reason = f"failed: {', '.join(card.failures)}"
        return ScenarioResult(name, Outcome.FAIL, card.as_dict(), reason)

    raise KeyError(f"unknown scenario {name!r}")
