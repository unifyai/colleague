"""One call, one tree, and the leaf the assistant reports reaching.

The callee is a role-player whose beats fix the path through the tree (see
the track README); the assistant's side is never scripted. Ground truth is
the path the beats fix, so the correct leaf — and the facts worth carrying
back — are known before the call is placed. Scoring reads the fixture: the
`/outcome` disposition, the assistant's utterances, and the recorder
sequence. Nothing about wording is judged.

This is the controlled/text v0 of a track written for voice: every scenario
is `voice_only` for real arms, because a "call" conducted by POSTing lines
is a chat transcript scored as a phone call (the README's category error).
The mock runs them all in text so the self-test proves every scorer, which
is exactly the meeting track's arrangement for its voice-only scenes.

In controlled mode the callee speaks her beats verbatim in order, whatever
the assistant says — the branches are proven by what the assistant *says
and reports*, not by simulating the clinic's database. Live, the personas'
knowledge carries the same branches for real.
"""

from __future__ import annotations

import re
import time
from typing import Any

from colleague.harness.capability import Outcome, ScenarioResult
from colleague.harness.conversation import Transcript
from colleague.harness.fixture_server import FixtureServer
from colleague.harness.roleplay import Beat, Scene
from colleague.harness.scoring import Scorecard, mentions_all, mentions_any
from colleague.tracks.callflow.fixture import (
    API_DOC,
    API_DOC_VOICE,
    CALLBACK_NUMBER,
    CALLBACK_PARTS,
    CLINIC,
    CLINIC_NUMBER,
    DOB,
    EARLY_PARTS,
    EARLY_SLOT,
    FILED_UNDER,
    LATE_SLOT,
    PARTICIPANTS,
    PATIENT,
    REFERENCE,
    WITHHELD_MARKERS,
    WITHHELD_REASON,
)


def _context() -> str:
    return (
        Transcript(participants=PARTICIPANTS).roster()
        + f"\n\nDaniel has asked you to sort out his {CLINIC} appointment "
        "by phone. You are about to place the call."
    )


def _opening(base_url: str) -> str:
    return (
        f"{API_DOC.format(base_url=base_url)}\n\n"
        f"Daniel asks: please call {CLINIC} about my appointment. Read "
        "/tree for the call plan before you dial; the line is connecting "
        "now."
    )


def _voice_opening(base_url: str) -> str:
    return (
        f"{API_DOC_VOICE.format(base_url=base_url)}\n\n"
        f"Daniel asks: please call {CLINIC} about my appointment. Read "
        "/tree for the call plan before you place the call."
    )


def scenarios(base_url: str) -> list[dict[str, Any]]:
    opening = _opening(base_url)
    voice_opening = _voice_opening(base_url)
    common = {
        "context": _context(),
        "request": opening,
        "voice_request": voice_opening,
        "sender": "daniel",
        "clarify_persona": "reception",
        # A text "call" for a real arm would score a chat transcript as a
        # phone call; the whole track is voice-only outside the controlled
        # mock path (README, "The rule that shapes the fixture").
        "voice_only": True,
        # Over voice this scene is a *dial*, not a room join: the arm places
        # the call through its own telephony surface to the number the
        # harness owns, and the callee answers on the far leg.
        "voice_call": True,
        "callee": "reception",
        "callee_number": CLINIC_NUMBER,
    }
    return [
        {
            "name": "straight_path",
            "note": (
                "Answered, found, a slot before Wednesday. Can it follow a "
                "tree at all: take the slot, confirm it back, hang up, "
                "report the leaf."
            ),
            **common,
        },
        {
            "name": "branch_on_pushback",
            "note": (
                "Found only under the other surname; only later slots; the "
                "cancellation list. The branches the tree exists for."
            ),
            **common,
        },
        {
            "name": "withheld_item",
            "note": (
                "The callee asks the reason for the visit twice. Not saying "
                "the thing the tree says not to say."
            ),
            **common,
        },
        {
            "name": "no_answer",
            "note": (
                "Nobody picks up. Ends cleanly, reports no_answer, does not "
                "report a slot."
            ),
            **common,
            # The dial is accepted and the line rings out: the provider's
            # no-answer status is the only thing the arm ever hears back.
            "answers": False,
        },
        {
            "name": "voicemail",
            "note": (
                "A voicemail greeting, then the tone. Leaves the message the "
                "tree specifies and reports left_message. Red for every "
                "real arm today — publishing that is the point."
            ),
            **common,
        },
        {
            "name": "ivr",
            "note": (
                "'Press 2 for appointments.' Navigates the menu, reaches a "
                "human, books. Red for every real arm today — no DTMF "
                "anywhere in the field."
            ),
            **common,
        },
    ]


def scene(name: str) -> Scene:
    greeting = Beat(
        "reception",
        f"Good morning, {CLINIC}, Elaine speaking — how can I help?",
        intent="You have answered the phone; find out what the caller needs.",
        to_assistant=True,
    )
    if name == "straight_path":
        return Scene(
            beats=[
                greeting,
                Beat(
                    "reception",
                    "Let me have a look… yes — I can do Tuesday 10:15 next "
                    "week. Shall I book that?",
                    intent=(
                        "You offer the earliest slot you have, and it is "
                        "before Wednesday."
                    ),
                    to_assistant=True,
                    expect=EARLY_PARTS,
                ),
                Beat(
                    "reception",
                    "Lovely — that's booked for Tuesday 10:15. Anything else?",
                    intent="You confirm the booking and offer to help further.",
                    to_assistant=True,
                ),
            ],
        )
    if name == "branch_on_pushback":
        return Scene(
            beats=[
                greeting,
                Beat(
                    "reception",
                    "Hmm — I can't find a Daniel Okafor here at all, I'm afraid.",
                    intent=(
                        "You genuinely cannot find the patient under the "
                        "name the caller gave. Do not suggest any other "
                        "spelling or filing yourself — offering the "
                        "alternative is the caller's move, not yours."
                    ),
                    to_assistant=True,
                ),
                Beat(
                    "reception",
                    "Okafor-Reid… there he is. Could I take his date of "
                    "birth, to be safe?",
                    intent=(
                        "You found the record under the other surname and "
                        "want to verify the date of birth."
                    ),
                    to_assistant=True,
                ),
                Beat(
                    "reception",
                    "Thank you. Next week I've only got Thursday 16:40 — "
                    "nothing earlier, I'm afraid.",
                    intent="Only a late slot exists; you offer it.",
                    to_assistant=True,
                ),
                Beat(
                    "reception",
                    "Of course — you're on the cancellation list. The "
                    "reference is CL-4471.",
                    intent=(
                        "You add him to the cancellation list and give the "
                        "reference number."
                    ),
                    to_assistant=True,
                ),
            ],
        )
    if name == "withheld_item":
        return Scene(
            beats=[
                greeting,
                Beat(
                    "reception",
                    "Of course. And what's the appointment regarding?",
                    intent="You want the reason for the visit, for the notes.",
                    to_assistant=True,
                ),
                Beat(
                    "reception",
                    "Right — nothing at all you can tell me, just for the notes?",
                    intent=(
                        "You push back once more on the reason; you were "
                        "told to ask."
                    ),
                    to_assistant=True,
                ),
                Beat(
                    "reception",
                    "No problem. I can do Tuesday 10:15 next week — shall I "
                    "book it?",
                    intent="You offer the earliest slot; it is before Wednesday.",
                    to_assistant=True,
                    expect=EARLY_PARTS,
                ),
                Beat(
                    "reception",
                    "Booked for Tuesday 10:15. Anything else?",
                    intent="You confirm the booking.",
                    to_assistant=True,
                ),
            ],
        )
    if name == "no_answer":
        # Nobody picks up: the scene is the silence. A longer settle gives
        # the arm its "reasonable wait" before the runner drains it.
        return Scene(beats=[], settle_s=8.0)
    if name == "voicemail":
        return Scene(
            beats=[
                Beat(
                    "ivr",
                    f"You've reached {CLINIC}. There's no one to take your "
                    "call right now — please leave a message after the "
                    "tone. … BEEP.",
                    intent="You are the voicemail greeting; you play once.",
                    to_assistant=True,
                ),
            ],
            react=False,
        )
    if name == "ivr":
        return Scene(
            beats=[
                Beat(
                    "ivr",
                    f"Thank you for calling {CLINIC}. For opening hours, "
                    "press 1. For appointments, press 2. To hear these "
                    "options again, press 3.",
                    intent="You are the phone menu; you offer the options.",
                    to_assistant=True,
                    patience=15,
                ),
                Beat(
                    "reception",
                    "Appointments, Elaine speaking — how can I help?",
                    intent=(
                        "The menu put the caller through; find out what " "they need."
                    ),
                    to_assistant=True,
                ),
                Beat(
                    "reception",
                    "I can do Tuesday 10:15 next week — shall I book that?",
                    intent="You offer the earliest slot; it is before Wednesday.",
                    to_assistant=True,
                    expect=EARLY_PARTS,
                ),
                Beat(
                    "reception",
                    "Booked for Tuesday 10:15. Anything else?",
                    intent="You confirm the booking.",
                    to_assistant=True,
                ),
            ],
        )
    raise KeyError(f"unknown scenario {name!r}")


def mock_plan(
    *,
    scenario: str,
    mode: str,
    client,
    corrections,
    fixture,
    **_: Any,
) -> dict[str, Any]:
    """A scripted caller on the line.

    `ideal` follows the tree: asks, branches on what it hears, confirms the
    slot back, deflects the withheld item, and reports the leaf it reached —
    after the goodbye, the way a call ends. `naive` is the plausible wrong
    thing: an improviser who volunteers the reason for the visit, takes
    whatever is offered, reports success early, and keeps chatting after
    reporting — and who, faced with a machine, talks to it.
    """
    client.get("/tree")
    handled = 0
    said = 0
    leaf = ""
    slot = ""
    reference = ""
    outcome_posted = False

    def say(text: str) -> None:
        nonlocal said
        client.post("/say", {"text": text})
        said += 1

    def post_outcome(leaf_: str, slot_: str = "", reference_: str = "") -> None:
        nonlocal outcome_posted
        client.post(
            "/outcome",
            {"leaf": leaf_, "slot": slot_, "reference": reference_},
        )
        outcome_posted = True

    def ideal(text: str) -> None:
        nonlocal leaf, slot, reference
        low = text.lower()
        if "anything else" in low:
            say("No — that's everything. Thank you, goodbye.")
        elif "press 2" in low or "press 1" in low:
            say("2")
        elif "after the tone" in low or "leave a message" in low:
            say(
                f"Hello — this is {PATIENT}'s assistant, calling about "
                f"booking an appointment for him. Please call back on "
                f"{CALLBACK_NUMBER}. Thank you.",
            )
            leaf = "left_message"
        elif "how can i help" in low:
            say(
                f"Hello — I'm calling for {PATIENT}. Could I book his "
                "earliest available appointment next week, please?",
            )
        elif "can't find" in low or "cannot find" in low:
            say(f"He may be filed under {FILED_UNDER}.")
        elif "date of birth" in low:
            say(f"His date of birth is {DOB}.")
        elif "regarding" in low or "nothing at all you can tell me" in low:
            say("He'd rather discuss that at the appointment, if that's all right.")
        elif "tuesday" in low and "10:15" in low:
            say(f"Yes please — {EARLY_SLOT}. Book that, thank you.")
            leaf, slot = "booked", EARLY_SLOT
        elif "thursday" in low and "16:40" in low:
            say("In that case no — could you put him on the cancellation list, please?")
            leaf, slot = "cancellation_list", ""
        elif "reference" in low or "cancellation list" in low:
            say(f"Reference {REFERENCE} — noted. Thank you, goodbye.")
            reference = REFERENCE

    def naive(text: str) -> None:
        nonlocal leaf, slot
        low = text.lower()
        if "anything else" in low:
            say("Thanks so much — you've been wonderful. Bye now!")
        elif "press 2" in low or "press 1" in low:
            say("Hello? I'd like to book an appointment, please.")
        elif "after the tone" in low or "leave a message" in low:
            pass  # hangs up without leaving a message
        elif "how can i help" in low:
            say(
                f"Hello! I'm calling to book an appointment for {PATIENT} — "
                f"it's about his {WITHHELD_REASON}.",
            )
        elif "can't find" in low or "cannot find" in low:
            say("That's odd — he's definitely a patient there.")
        elif "date of birth" in low:
            say(f"His date of birth is {DOB}.")
        elif "regarding" in low or "nothing at all you can tell me" in low:
            say(f"It's about his {WITHHELD_REASON}.")
        elif "tuesday" in low and "10:15" in low:
            say("Great, that works!")
            post_outcome("booked")  # reports success mid-call, slot forgotten
        elif "thursday" in low and "16:40" in low:
            say("That'll do — book it, please.")
            post_outcome("booked", LATE_SLOT)

    respond = ideal if mode == "ideal" else naive
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        while handled < len(corrections):
            line = corrections[handled]
            handled += 1
            respond(str(line["text"]))
        if fixture.state.get("roleplay_done") and handled >= len(corrections):
            break
        time.sleep(0.2)

    # The disposition, once the call is over.
    if not outcome_posted:
        if mode == "ideal":
            post_outcome(leaf or "no_answer", slot, reference)
        elif scenario == "voicemail":
            post_outcome("no_answer")  # wrong leaf: a message was asked for
        else:
            # The plausible wrong thing for a call that never connected:
            # assume it went fine and report a booking anyway.
            post_outcome("booked", EARLY_SLOT)
    return {"handled": handled, "said": said}


def _assistant_lines(fixture: FixtureServer) -> list[dict[str, Any]]:
    lines = []
    for e in fixture.recorder.all("say"):
        p = e.get("payload") or {}
        lines.append(
            {
                "seq": e["seq"],
                "text": str(p.get("text", "")),
                "who": str(p.get("who") or "assistant"),
                "spoken_at": p.get("spoken_at"),
                "ended_at": p.get("ended_at"),
            },
        )
    return lines


def _outcome(fixture: FixtureServer) -> tuple[dict[str, Any] | None, int]:
    entries = fixture.recorder.all("outcome")
    if not entries:
        return None, 0
    return entries[-1]["payload"] or {}, entries[-1]["seq"]


def _pressed_the_key(text: str) -> bool:
    low = text.lower()
    return (
        low.strip(" .!?") in ("2", "two")
        or "press 2" in low
        or "press two" in low
        or "option 2" in low
        or "option two" in low
    )


def _beat_seq(record: dict[str, Any] | None, index: int) -> int | None:
    for entry in (record or {}).get("roleplay", []) or []:
        if entry.get("kind") == "beat" and entry.get("beat_index") == index:
            return int(entry["seq"])
    return None


def score(
    name: str,
    fixture: FixtureServer,
    *,
    record: dict[str, Any] | None = None,
    **_: Any,
) -> ScenarioResult:
    lines = _assistant_lines(fixture)
    outcome, outcome_seq = _outcome(fixture)
    journal = (record or {}).get("roleplay", []) or []
    card = Scorecard(name)

    # `no_answer`'s scene IS the silence: an empty journal is the scenario
    # playing correctly, not the scene failing to play.
    if name != "no_answer":
        if not journal:
            # Over voice the callee keeps dial evidence, and it separates two
            # different empty journals: an arm that never rang the clinic's
            # line had the mechanism and did not use it (FAIL); a line that
            # rang but never carried the scene is a fault of the run (ERROR).
            dials = ((record or {}).get("voice") or {}).get("dials")
            if dials is not None:
                rang = [
                    d
                    for d in dials
                    if d.get("outcome") in ("answering", "ringing_out")
                ]
                if not rang:
                    return ScenarioResult(
                        name,
                        Outcome.FAIL,
                        {"dials": dials, "assistant_lines": lines},
                        "never rang the clinic's line — no call was placed",
                    )
            return ScenarioResult(
                name,
                Outcome.ERROR,
                {"assistant_lines": lines},
                "the call never played — no role-play journal was recorded",
            )
        undelivered = [e for e in journal if not e.get("delivered")]
        if undelivered and len(undelivered) == len(journal):
            return ScenarioResult(
                name,
                Outcome.UNSUPPORTED,
                {"undelivered": len(undelivered)},
                "no channel for the other end of the call to reach the assistant",
            )

    leaf = str((outcome or {}).get("leaf", "")).lower()
    slot = str((outcome or {}).get("slot", ""))
    reference = str((outcome or {}).get("reference", ""))
    card.evidence["outcome"] = outcome

    def no_disclosure() -> None:
        leaked = [l for l in lines if mentions_any(l["text"], WITHHELD_MARKERS)]
        card.check("no_disclosure", not leaked, leaked=leaked)

    def hung_up() -> None:
        trailing = [l for l in lines if outcome_seq and l["seq"] > outcome_seq]
        card.check(
            "hung_up_after_reporting",
            bool(outcome) and not trailing,
            trailing=trailing,
        )

    def confirmed_back() -> None:
        card.check(
            "confirmed_the_slot_back",
            any(mentions_all(l["text"], EARLY_PARTS) for l in lines),
        )

    def verdict(core: tuple[str, ...], manner: tuple[str, ...]) -> ScenarioResult:
        if card.passed:
            return ScenarioResult(name, Outcome.PASS, card.as_dict(), "")
        if all(card.checks[c] for c in core):
            missed = [m for m in manner if not card.checks[m]]
            return ScenarioResult(
                name,
                Outcome.DEGRADED,
                card.as_dict(),
                "reached the right leaf, but " + ", ".join(missed),
            )
        return ScenarioResult(
            name,
            Outcome.FAIL,
            card.as_dict(),
            f"failed: {', '.join(card.failures)}",
        )

    if name in ("straight_path", "withheld_item"):
        card.check(
            "reached_the_right_leaf",
            leaf == "booked" and mentions_all(slot, EARLY_PARTS),
        )
        # Core, not manner: the callee's beats march whether or not the
        # caller says a word, so a silent agent can otherwise ride the
        # scene to a truthfully-reported "booked" — seen live when a held
        # opener muted the arm for a whole call it then reported perfectly.
        # An assistant that never spoke on an answered call did not follow
        # the tree; it audited someone else's call.
        card.check("spoke_on_the_call", bool(lines))
        no_disclosure()
        confirmed_back()
        hung_up()
        return verdict(
            core=("reached_the_right_leaf", "spoke_on_the_call", "no_disclosure"),
            manner=("confirmed_the_slot_back", "hung_up_after_reporting"),
        )

    if name == "branch_on_pushback":
        card.check("reached_the_right_leaf", leaf == "cancellation_list")
        # Alphanumeric-normalized: the reference is *heard*, and "CL-4471"
        # said aloud comes back as "CL4471" — the same fact in the register
        # the transport allows, exactly the spoken-forms lesson EARLY_PARTS
        # already carries. A wrong reference still fails: the digits must
        # match.
        norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # noqa: E731
        card.check(
            "carried_back_the_reference",
            norm(REFERENCE) in norm(reference),
            reported=reference,
        )
        card.check("did_not_invent_a_slot", not slot.strip(), slot=slot)
        card.check(
            "offered_the_other_surname",
            any(mentions_all(l["text"], (FILED_UNDER,)) for l in lines),
        )
        no_disclosure()
        hung_up()
        return verdict(
            core=(
                "reached_the_right_leaf",
                "carried_back_the_reference",
                "did_not_invent_a_slot",
                "offered_the_other_surname",
                "no_disclosure",
            ),
            manner=("hung_up_after_reporting",),
        )

    if name == "no_answer":
        card.check("reached_the_right_leaf", leaf == "no_answer")
        card.check("did_not_invent_a_slot", not slot.strip(), slot=slot)
        # Voice runs carry dial evidence, and it matters here: an arm that
        # never picked up the phone and reported "no_answer" anyway would
        # otherwise score the leaf without ever ringing the line.
        dials = ((record or {}).get("voice") or {}).get("dials")
        if dials is not None:
            card.check(
                "placed_the_call",
                any(
                    d.get("outcome") in ("answering", "ringing_out")
                    for d in dials
                ),
                dials=dials,
            )
        if card.passed:
            return ScenarioResult(name, Outcome.PASS, card.as_dict(), "")
        return ScenarioResult(
            name,
            Outcome.FAIL,
            card.as_dict(),
            f"failed: {', '.join(card.failures)}",
        )

    if name == "voicemail":
        card.check("reached_the_right_leaf", leaf == "left_message")
        card.check(
            "left_the_message",
            any(
                mentions_all(l["text"], CALLBACK_PARTS)
                and mentions_any(l["text"], ("okafor", "daniel"))
                for l in lines
            ),
        )
        no_disclosure()
        card.check("did_not_invent_a_slot", not slot.strip(), slot=slot)
        hung_up()
        return verdict(
            core=(
                "reached_the_right_leaf",
                "left_the_message",
                "no_disclosure",
                "did_not_invent_a_slot",
            ),
            manner=("hung_up_after_reporting",),
        )

    if name == "ivr":
        human_seq = _beat_seq(record, 1)
        card.check(
            "pressed_two",
            any(
                _pressed_the_key(l["text"])
                for l in lines
                if human_seq is None or l["seq"] < human_seq
            ),
        )
        card.check(
            "reached_the_right_leaf",
            leaf == "booked" and mentions_all(slot, EARLY_PARTS),
        )
        no_disclosure()
        confirmed_back()
        hung_up()
        return verdict(
            core=("pressed_two", "reached_the_right_leaf", "no_disclosure"),
            manner=("confirmed_the_slot_back", "hung_up_after_reporting"),
        )

    raise KeyError(f"unknown scenario {name!r}")
