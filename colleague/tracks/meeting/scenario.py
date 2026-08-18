"""Several people in a room, one assistant among them.

Speak when spoken to, stay quiet when two people are talking to each other,
answer before the moment has passed, and turn a request made in passing into
work. The people are role-players who carry each scene themselves; the
assistant's lines are the fixture's `/say` records; timing is recorder
sequence. Nothing about wording is judged.

This is the text-room v0 of a track written for voice. The scenes, the
checks and the roles are medium-agnostic; the transport is what changes when
the room becomes a call.
"""

from __future__ import annotations

import time
from typing import Any

from colleague.harness.capability import Outcome, ScenarioResult
from colleague.harness.conversation import Transcript
from colleague.harness.fixture_server import FixtureServer
from colleague.harness.roleplay import Beat, Scene
from colleague.harness.scoring import Scorecard, mentions_all, mentions_any
from colleague.tracks.meeting.fixture import (
    API_DOC,
    API_DOC_VOICE,
    BUDGET_MARKERS,
    DEPLOY_PARTS,
    DEPLOY_WINDOW,
    PARTICIPANTS,
    VENUE_BUDGET,
)

#: How the assistant is addressed in the beats. A scorer never reads this;
#: the mock plan does, standing in for an arm that knows its own name.
CALL_SIGN = "Assistant"


def _context() -> str:
    return (
        Transcript(participants=PARTICIPANTS).roster()
        + "\n\nThis is the offsite planning room. The people above are in it "
        "with you, mid-discussion."
    )


def _opening(base_url: str) -> str:
    return (
        f"{API_DOC.format(base_url=base_url)}\n\n"
        "Daniel added you to the offsite planning room. Read /notes for what "
        "you know. The conversation is already going."
    )


def _voice_opening(base_url: str) -> str:
    return (
        f"{API_DOC_VOICE.format(base_url=base_url)}\n\n"
        "Daniel added you to the offsite planning room's call. Read /notes "
        "for what you know; you are about to be connected and the "
        "conversation is already going."
    )


def scenarios(base_url: str) -> list[dict[str, Any]]:
    opening = _opening(base_url)
    voice_opening = _voice_opening(base_url)
    return [
        {
            "name": "addressed_by_name",
            "context": _context(),
            "request": opening,
            "voice_request": voice_opening,
            "sender": "daniel",
            "note": (
                "Two people talk venues; then one asks the assistant a "
                "question by name; then they carry on. Disclosure control: "
                "the answer must appear."
            ),
        },
        {
            "name": "humans_talking",
            "context": _context(),
            "request": opening,
            "voice_request": voice_opening,
            "sender": "daniel",
            "note": "Five lines among three people. Nobody addresses the assistant.",
        },
        {
            "name": "commanded_work",
            "context": _context(),
            "request": opening,
            "voice_request": voice_opening,
            "sender": "daniel",
            "note": (
                "A recurring request made in passing, and a second person's "
                "question a moment later."
            ),
        },
        {
            "name": "interrupted_mid_answer",
            "context": _context(),
            "request": opening,
            "voice_request": voice_opening,
            "sender": "daniel",
            "note": (
                "A question, then the asker changes it before (or just after) "
                "the answer. What comes after the change is what counts."
            ),
        },
        {
            "name": "answered_in_time",
            "context": _context(),
            "request": opening,
            "voice_request": voice_opening,
            "sender": "daniel",
            "voice_only": True,
            "note": (
                "A call tolerates seconds, not turns: the question's patience "
                "is a few seconds and the asker's colleague moves the room on. "
                "Voice-only for real arms; the mock runs it in text so the "
                "self-test proves the scorer."
            ),
        },
        {
            "name": "two_assistants",
            "context": _context(),
            "request": opening,
            "voice_request": voice_opening,
            "sender": "daniel",
            "voice_only": True,
            "assistant_identities": ("assistant", "assistant-2"),
            "note": (
                "Two assistants on the call; a question to 'the assistants'. "
                "At most one answers, and their audio never overlaps. The "
                "floor protocol between assistants is the mechanism under "
                "test. Voice-only for real arms."
            ),
        },
    ]


def scene(name: str) -> Scene:
    if name == "addressed_by_name":
        return Scene(
            beats=[
                Beat(
                    "daniel",
                    "Right — venue for the offsite. Priya, where did we get to?",
                ),
                Beat(
                    "priya",
                    "Three on the shortlist. Ashby House is my favourite but it's the priciest.",
                ),
                Beat(
                    "daniel",
                    f"{CALL_SIGN} — while I think of it, what's the deploy window this week?",
                    intent="You genuinely want the deploy window from the assistant.",
                    to_assistant=True,
                    patience=25,
                    expect=DEPLOY_PARTS,
                ),
                Beat(
                    "priya",
                    "Shall I book a walk-through at Ashby for Thursday morning?",
                ),
                Beat("daniel", "Yes, do."),
            ],
        )
    if name == "humans_talking":
        return Scene(
            beats=[
                Beat(
                    "daniel",
                    "Offsite: are we still looking at the second week of October?",
                ),
                Beat("priya", "Yes. I've held the dates with all three venues."),
                Beat(
                    "bob",
                    "Does the platform team need to be there for the whole thing?",
                ),
                Beat("daniel", "Day one at least. We can talk about day two."),
                Beat("priya", "I'll draft an agenda and send it round."),
            ],
        )
    if name == "commanded_work":
        return Scene(
            beats=[
                Beat("daniel", "Priya, where are we on the shortlist?"),
                Beat(
                    "priya",
                    f"{CALL_SIGN}, could you send me the venue shortlist every Monday "
                    "at 9, until we've booked?",
                    intent="You want a recurring Monday 09:00 reminder with the shortlist.",
                    to_assistant=True,
                    patience=25,
                ),
                Beat("daniel", "Good idea."),
                Beat(
                    "bob",
                    f"{CALL_SIGN}, is the deploy window still Thursday? I'm planning a migration.",
                    intent="You need to know the deploy window to avoid it.",
                    to_assistant=True,
                    patience=25,
                    expect=DEPLOY_PARTS,
                ),
                Beat("daniel", "Fine — let's move on."),
            ],
        )
    if name == "interrupted_mid_answer":
        return Scene(
            beats=[
                Beat(
                    "daniel",
                    f"{CALL_SIGN}, what's the venue budget again?",
                    intent="You ask, then almost immediately change your mind.",
                    to_assistant=True,
                    patience=4,
                ),
                Beat(
                    "daniel",
                    "Actually — never mind the budget. What's the deploy window?",
                    intent="You have changed the question; you want the deploy window now.",
                    to_assistant=True,
                    patience=25,
                    expect=DEPLOY_PARTS,
                ),
                Beat("priya", "I'll pencil Ashby for Thursday then."),
            ],
        )
    if name == "answered_in_time":
        # The same disclosure question as addressed_by_name, at a call's
        # tempo: a few seconds of patience, and the colleague's next line is
        # the moment after which the answer is late.
        return Scene(
            beats=[
                Beat(
                    "daniel",
                    "Quick one before we carry on — venues are close to done?",
                ),
                Beat(
                    "priya",
                    "Close. Ashby and The Wharf both work; I'm chasing Larkin.",
                ),
                Beat(
                    "daniel",
                    f"{CALL_SIGN} — what's the deploy window this week?",
                    intent="You want the deploy window now, while the room waits.",
                    to_assistant=True,
                    patience=8,
                    expect=DEPLOY_PARTS,
                ),
                Beat("priya", "And I'll circulate the walk-through times after this."),
                Beat("daniel", "Good. Keep going."),
            ],
        )
    if name == "two_assistants":
        return Scene(
            beats=[
                Beat("daniel", "Right — you're both on this call today, good."),
                Beat(
                    "daniel",
                    "Assistants — one of you, whoever has it: what's the "
                    "deploy window this week?",
                    intent=(
                        "You are asking the assistants collectively; you want "
                        "one answer, from one of them, not a chorus."
                    ),
                    to_assistant=True,
                    patience=25,
                    expect=DEPLOY_PARTS,
                ),
                Beat("priya", "Once we have it I'll plan the walk-through around it."),
                Beat("daniel", "Thanks. Moving on."),
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
    """A scripted arm in the room.

    `ideal` answers only when addressed by name, from /notes, and creates
    the schedule it was asked for. `naive` is a loop whose only output is a
    reply: it says something after every line, answers late, and treats a
    request for recurring work as something to acknowledge.
    """
    notes = client.get("/notes")["text"]
    handled = 0
    said = 0
    deadline = time.monotonic() + 120

    def answer(text: str) -> None:
        nonlocal said
        low = text.lower()
        if "deploy window" in low:
            client.post(
                "/say",
                {"text": f"The staging deploy window is {DEPLOY_WINDOW}."},
            )
            if mode == "naive" and scenario == "two_assistants":
                # The chorus: the second assistant answers over the first —
                # the plausible wrong thing when a question is addressed to
                # "the assistants" and nobody arbitrates the floor.
                client.post(
                    "/say",
                    {"text": f"Yes — deploy window is {DEPLOY_WINDOW}."},
                )
        elif "budget" in low:
            client.post("/say", {"text": f"The venue budget is {VENUE_BUDGET} all-in."})
        elif "every monday" in low or "shortlist every" in low:
            if mode == "ideal":
                client.post(
                    "/schedule",
                    {
                        "to": "priya",
                        "cadence": "weekly",
                        "weekday": "monday",
                        "time": "09:00",
                        "text": "Venue shortlist: "
                        + notes.split("shortlist:")[-1].strip(),
                    },
                )
                client.post("/say", {"text": "Done — every Monday at 09:00, Priya."})
            else:
                client.post("/say", {"text": "Sure, will do."})
        else:
            client.post("/say", {"text": "Noted."})
        said += 1

    last_asker: str | None = None
    last_ask_at = 0.0
    while time.monotonic() < deadline:
        while handled < len(corrections):
            line = corrections[handled]
            handled += 1
            text = str(line["text"])
            who = str(line.get("sender") or "")
            if mode == "ideal":
                # Addressed by name, or a quick follow-up from the person
                # who just addressed you — that is still for you.
                by_name = CALL_SIGN.lower() in text.lower()
                follow_up = (
                    who == last_asker
                    and time.monotonic() - last_ask_at < 8
                    and text.strip().endswith("?")
                )
                if by_name or follow_up:
                    last_asker, last_ask_at = who, time.monotonic()
                    answer(text)
            else:
                # The undifferentiated loop: every line gets a reply, and it
                # gets there a beat late.
                time.sleep(4.5)
                answer(text)
        if fixture.state.get("roleplay_done"):
            # Flush anything that arrived while finishing.
            if handled >= len(corrections):
                break
        time.sleep(0.2)
    return {"handled": handled, "said": said}


def _assistant_lines(fixture: FixtureServer) -> list[dict[str, Any]]:
    lines = []
    for e in fixture.recorder.all("say"):
        p = e.get("payload") or {}
        lines.append(
            {
                "seq": e["seq"],
                "text": str(p.get("text", "")),
                # Voice transport extras; absent in the text room.
                "who": str(p.get("who") or "assistant"),
                "spoken_at": p.get("spoken_at"),
                "ended_at": p.get("ended_at"),
            },
        )
    return lines


def _audio_overlaps(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pairs of assistant lines from different identities whose audio
    intervals intersect. Vacuously empty in the text room, where lines carry
    no transport timestamps."""
    from datetime import datetime

    timed = [
        (
            l,
            datetime.fromisoformat(l["spoken_at"]),
            datetime.fromisoformat(l["ended_at"]),
        )
        for l in lines
        if l.get("spoken_at") and l.get("ended_at")
    ]
    overlaps = []
    for i, (a, a0, a1) in enumerate(timed):
        for b, b0, b1 in timed[i + 1 :]:
            if a["who"] == b["who"]:
                continue
            if a0 < b1 and b0 < a1:
                overlaps.append({"a": a, "b": b})
    return overlaps


def _aimed(record: dict[str, Any] | None, index: int) -> dict[str, Any] | None:
    for entry in (record or {}).get("roleplay", []) or []:
        if entry.get("kind") == "beat" and entry.get("beat_index") == index:
            return entry
    return None


def score(
    name: str,
    fixture: FixtureServer,
    *,
    record: dict[str, Any] | None = None,
    **_: Any,
) -> ScenarioResult:
    lines = _assistant_lines(fixture)
    journal = (record or {}).get("roleplay", []) or []
    card = Scorecard(name)
    if not journal:
        return ScenarioResult(
            name,
            Outcome.ERROR,
            {"assistant_lines": lines},
            "the scene never played — no role-play journal was recorded",
        )
    # Lines that never reached the arm at all mean the scene did not happen
    # for it: an arm with no way for a second person to reach it is not
    # failing to keep quiet or to answer, it is not in the room.
    undelivered = [e for e in journal if not e.get("delivered")]
    if undelivered and len(undelivered) == len(journal):
        return ScenarioResult(
            name,
            Outcome.UNSUPPORTED,
            {"undelivered": len(undelivered)},
            "no channel for people in the room to reach the assistant",
        )

    # Every line reached this arm only as a later turn: it has no live channel
    # into the room, so "in time" is unreachable by construction. That is a
    # property of the arm's surface and is reported as such, the way
    # `interruption` reports a queued correction — DEGRADED, with the reason.
    queued = all(
        e.get("mode") in ("resumed_turn", "queued_followup")
        for e in journal
        if e.get("delivered")
    )
    late_why = (
        " — every line reached it as a later turn; this arm has no live channel into the room"
        if queued
        else ""
    )

    def answers_after(seq: int, parts: tuple[str, ...]) -> list[dict[str, Any]]:
        return [l for l in lines if l["seq"] > seq and mentions_all(l["text"], parts)]

    def in_time(beat: dict[str, Any], answers: list[dict[str, Any]]) -> bool:
        nxt = beat.get("next_seq")
        return bool(answers) and (nxt is None or answers[0]["seq"] < nxt)

    if name == "humans_talking":
        card.check("said_nothing", len(lines) == 0, assistant_lines=lines)
        outcome = Outcome.PASS if card.passed else Outcome.FAIL
        return ScenarioResult(
            name,
            outcome,
            card.as_dict(),
            "" if card.passed else "spoke when nobody asked",
        )

    if name == "addressed_by_name":
        ask = _aimed(record, 2)
        assert ask is not None
        answers = answers_after(ask["seq"], DEPLOY_PARTS)
        card.check("answered_the_question", bool(answers))
        card.check(
            "silent_until_addressed",
            not [l for l in lines if l["seq"] < ask["seq"]],
            early=[l for l in lines if l["seq"] < ask["seq"]],
        )
        timely = in_time(ask, answers)
        card.check("only_one_line", len(lines) == 1, assistant_lines=lines)
        card.evidence["in_time"] = timely
        if (
            card.checks["answered_the_question"]
            and card.checks["silent_until_addressed"]
        ):
            if timely and card.checks["only_one_line"]:
                return ScenarioResult(name, Outcome.PASS, card.as_dict(), "")
            return ScenarioResult(
                name,
                Outcome.DEGRADED,
                card.as_dict(),
                "answered, but "
                + (
                    "after the conversation had moved on" + late_why
                    if not timely
                    else "with extra lines"
                ),
            )
        return ScenarioResult(
            name,
            Outcome.FAIL,
            card.as_dict(),
            f"failed: {', '.join(card.failures)}",
        )

    if name == "commanded_work":
        ask_priya = _aimed(record, 1)
        ask_bob = _aimed(record, 3)
        assert ask_priya is not None and ask_bob is not None
        schedules = fixture.recorder.all("schedule")
        # The day may arrive in `weekday` or, from an arm that folds it into
        # the cadence, in `cadence`; the fixture guarantees cadence is one of
        # its two values, so "weekly" plus a Monday anywhere is the meaning.
        right = [
            s
            for s in schedules
            if str((s.get("payload") or {}).get("to", "")).lower().startswith("priya")
            and str((s.get("payload") or {}).get("cadence", "")).lower() == "weekly"
            and "mon"
            in (
                str((s.get("payload") or {}).get("weekday", ""))
                + " "
                + str((s.get("payload") or {}).get("cadence", ""))
            ).lower()
        ]
        card.check(
            "scheduled_for_priya_weekly_monday",
            bool(right),
            schedules=schedules,
        )
        bob_answers = answers_after(ask_bob["seq"], DEPLOY_PARTS)
        card.check("answered_bob", bool(bob_answers))
        card.check(
            "silent_until_addressed",
            not [l for l in lines if l["seq"] < ask_priya["seq"]],
        )
        timely = in_time(ask_bob, bob_answers)
        card.evidence["bob_in_time"] = timely
        if card.passed:
            return ScenarioResult(
                name,
                Outcome.PASS if timely else Outcome.DEGRADED,
                card.as_dict(),
                (
                    ""
                    if timely
                    else "Bob got his answer after the room had moved on" + late_why
                ),
            )
        return ScenarioResult(
            name,
            Outcome.FAIL,
            card.as_dict(),
            f"failed: {', '.join(card.failures)}",
        )

    if name == "answered_in_time":
        ask = _aimed(record, 2)
        assert ask is not None
        answers = answers_after(ask["seq"], DEPLOY_PARTS)
        card.check("answered_the_question", bool(answers))
        card.check(
            "silent_until_addressed",
            not [l for l in lines if l["seq"] < ask["seq"]],
            early=[l for l in lines if l["seq"] < ask["seq"]],
        )
        timely = in_time(ask, answers)
        card.evidence["in_time"] = timely
        card.check("only_one_line", len(lines) == 1, assistant_lines=lines)
        if (
            card.checks["answered_the_question"]
            and card.checks["silent_until_addressed"]
        ):
            if timely and card.checks["only_one_line"]:
                return ScenarioResult(name, Outcome.PASS, card.as_dict(), "")
            return ScenarioResult(
                name,
                Outcome.DEGRADED,
                card.as_dict(),
                "answered, but "
                + (
                    "after the caller's colleague had already moved the room on"
                    + late_why
                    if not timely
                    else "with extra lines"
                ),
            )
        return ScenarioResult(
            name,
            Outcome.FAIL,
            card.as_dict(),
            f"failed: {', '.join(card.failures)}",
        )

    if name == "two_assistants":
        ask = _aimed(record, 1)
        assert ask is not None
        answers = answers_after(ask["seq"], DEPLOY_PARTS)
        overlaps = _audio_overlaps(lines)
        answerers = sorted({a["who"] for a in answers})
        # Disclosure control: a silent pair passes every "did not" check and
        # fails this one.
        card.check("answered_the_question", bool(answers))
        card.check("one_answer", len(answers) == 1, answers=answers)
        card.check(
            "one_assistant_answered",
            len(answerers) <= 1,
            answerers=answerers,
        )
        card.check("no_assistant_overlap", not overlaps, overlaps=overlaps)
        card.check(
            "silent_until_addressed",
            not [l for l in lines if l["seq"] < ask["seq"]],
        )
        if card.passed:
            return ScenarioResult(name, Outcome.PASS, card.as_dict(), "")
        return ScenarioResult(
            name,
            Outcome.FAIL,
            card.as_dict(),
            f"failed: {', '.join(card.failures)}",
        )

    if name == "interrupted_mid_answer":
        change = _aimed(record, 1)
        first = _aimed(record, 0)
        assert change is not None and first is not None
        window = answers_after(change["seq"], DEPLOY_PARTS)
        budget_after = [
            l
            for l in lines
            if l["seq"] > change["seq"] and mentions_any(l["text"], BUDGET_MARKERS)
        ]
        card.check("gave_the_new_answer", bool(window))
        card.check(
            "dropped_the_old_question",
            not budget_after,
            budget_after=budget_after,
        )
        card.check(
            "silent_until_addressed",
            not [l for l in lines if l["seq"] < first["seq"]],
        )
        if card.passed:
            return ScenarioResult(name, Outcome.PASS, card.as_dict(), "")
        if card.checks["gave_the_new_answer"] and card.checks["silent_until_addressed"]:
            return ScenarioResult(
                name,
                Outcome.DEGRADED,
                card.as_dict(),
                "answered the new question, but finished the abandoned one first",
            )
        return ScenarioResult(
            name,
            Outcome.FAIL,
            card.as_dict(),
            f"failed: {', '.join(card.failures)}",
        )

    raise KeyError(f"unknown scenario {name!r}")
