"""Facts told in passing over eight days, asked about on the ninth.

Three of the seven questions have answers that changed along the way — the
offsite moved twice, a contact left, a deploy window shifted — and the right
answer is the newest one, with the old ones gone. Four are stable and act as
retention controls: an arm that gets a superseded question wrong but the
stable ones right did not forget, it recalled the wrong version, which is
the failure this track is for.

Every arm answers Daniel through its own reply channel, so there is no
fixture endpoint to call and nothing to route. What is measured is what an
assistant says it knows after a week of ordinary messages, and — from the
per-turn ledger the arms already produce — what each answer cost.
"""

from __future__ import annotations

from typing import Any

from colleague.harness.capability import Outcome, ScenarioResult
from colleague.harness.conversation import Participant, Transcript
from colleague.harness.fixture_server import FixtureServer
from colleague.harness.scoring import Scorecard, mentions_all, mentions_any
from colleague.tracks.recall.fixture import DAYS, QUESTIONS, TRUTH

SESSION_SCOPE = "track"

DANIEL = Participant(
    id="daniel",
    name="Daniel Okafor",
    role="the person you work for",
    email="daniel@northwind.example",
    standing="Everything you know, you know on his behalf.",
)
PARTICIPANTS = [DANIEL]


def scenarios(base_url: str) -> list[dict[str, Any]]:
    del base_url
    roster = Transcript(participants=PARTICIPANTS).roster()
    out: list[dict[str, Any]] = []
    for i, text in enumerate(DAYS, start=1):
        out.append(
            {
                "name": f"day_{i}",
                "context": roster if i == 1 else None,
                "request": text,
                "persist": True,
                "continue": i > 1,
                "sender": "daniel",
                "note": "One day's messages. Nothing to do; something to remember.",
            },
        )
    for key, question in QUESTIONS.items():
        out.append(
            {
                "name": f"ask_{key}",
                "request": question,
                "continue": True,
                "sender": "daniel",
                "note": (
                    "Superseded twice; the newest value is the only right one."
                    if len(TRUTH[key]["stale"]) > 1
                    else (
                        "Superseded once; the newest value is the only right one."
                        if TRUTH[key]["stale"]
                        else "Stable fact — a retention control."
                    )
                ),
            },
        )
    out.append(
        {
            "name": "ask_after_restart",
            "request": (
                "I had to restart you — quick check that nothing was lost. "
                "One line each: " + " ".join(QUESTIONS.values())
            ),
            "restart": True,
            "continue": True,
            "sender": "daniel",
            "note": (
                "The same questions in a fresh process: only a durable store "
                "answers. The week must survive the arm, not the prompt."
            ),
        },
    )
    return out


#: What each day's message establishes, keyed by question id, in order.
_ESTABLISHES: dict[int, dict[str, str]] = {
    1: {"portal_manager": "Ines Varga", "offsite": "Bristol"},
    2: {
        "board_and_bucket:bucket": "nw-ledger-exports-7",
        "trellis_contact": "Marta Lindqvist",
    },
    3: {"board_and_bucket:board": "Helena Brandt", "deploy_window": "Thursday 14:00"},
    4: {"offsite": "Cardiff", "travel_code": "TRV-2210"},
    5: {"trellis_contact": "Jonas Ekdahl"},
    6: {"deploy_window": "Wednesday 11:00"},
    7: {"offsite": "Leeds", "priya_cover": "Omar Haddad"},
    8: {},
}


def mock_plan(*, scenario: str, mode: str, memory, **_: Any) -> dict[str, Any]:
    if scenario.startswith("day_"):
        day = int(scenario.split("_")[1])
        for key, value in _ESTABLISHES[day].items():
            if mode == "ideal":
                # Newest wins: the store supersedes.
                memory[key] = value
            else:
                # An append-only log answered from the first match: the store
                # never supersedes, so the first thing heard stays the answer.
                memory.setdefault(key, value)
        return {"noted": sorted(_ESTABLISHES[day])}

    if scenario == "ask_after_restart":
        # A durable store answers the whole week in one breath; a store
        # that died with the process has nothing but apologies.
        lines = [
            f"{key}: {memory.get(key, 'I lost that.')}"
            for key in (
                "offsite",
                "trellis_contact",
                "deploy_window",
                "portal_manager",
                "travel_code",
                "priya_cover",
            )
        ]
        lines.append(
            f"board pack: {memory.get('board_and_bucket:board', 'I lost that.')}; "
            f"exports: {memory.get('board_and_bucket:bucket', 'I lost that.')}",
        )
        return {"answer": " | ".join(lines)}

    key = scenario.removeprefix("ask_")
    if key == "board_and_bucket":
        answer = (
            f"{memory.get('board_and_bucket:board', '?')} first; exports go to "
            f"{memory.get('board_and_bucket:bucket', '?')}."
        )
    else:
        answer = memory.get(key, "I don't have that.")
    return {"answer": answer}


def score(
    name: str,
    fixture: FixtureServer,
    *,
    record: dict[str, Any] | None = None,
    **_: Any,
) -> ScenarioResult:
    del fixture
    reply = (record or {}).get("reply") or {}
    text = str(reply.get("text") or "")
    card = Scorecard(name)

    if name.startswith("day_"):
        card.check("turn_completed", bool(reply.get("ok", False)))
        outcome = Outcome.PASS if card.passed else Outcome.FAIL
        return ScenarioResult(
            name,
            outcome,
            card.as_dict(),
            "" if card.passed else "turn failed",
        )

    if name == "ask_after_restart":
        # The single-ask logic, across every question at once: each current
        # value contained, and no stale value standing in for a missing one.
        for key, truth in TRUTH.items():
            current = truth["current"]
            parts = current if isinstance(current, tuple) else (current,)
            card.check(
                f"recalled_{key}",
                mentions_all(text, parts),
                wanted=list(parts),
            )
            stale = mentions_any(text, truth["stale"])
            card.check(
                f"not_stale_{key}",
                not (stale and not card.checks[f"recalled_{key}"]),
                stale_markers=stale,
            )
        card.evidence["reply_text"] = text[:600]
        outcome = Outcome.PASS if card.passed else Outcome.FAIL
        return ScenarioResult(
            name,
            outcome,
            card.as_dict(),
            "" if card.passed else f"failed: {', '.join(card.failures)}",
        )

    key = name.removeprefix("ask_")
    truth = TRUTH[key]
    current = truth["current"]
    parts = current if isinstance(current, tuple) else (current,)
    card.check(
        "recalled_the_current_value",
        mentions_all(text, parts),
        wanted=list(parts),
    )
    stale = mentions_any(text, truth["stale"])
    # A stale value *instead of* the current one is the failure. A reply that
    # gives the current value and names what it replaced ("Ekdahl — he took
    # over after Lindqvist left") is correct, and a containment test cannot
    # tell explanation from confusion, so the old names are recorded as
    # evidence rather than scored.
    card.check(
        "not_a_stale_value_instead",
        not (stale and not card.checks["recalled_the_current_value"]),
        stale_markers=stale,
    )
    card.evidence["reply_text"] = text[:400]
    card.evidence["mentioned_replaced_values"] = stale
    if card.passed:
        return ScenarioResult(name, Outcome.PASS, card.as_dict(), "")
    if stale:
        reason = "recalled a value that had since been replaced"
    else:
        reason = "did not recall the value"
    return ScenarioResult(name, Outcome.FAIL, card.as_dict(), reason)
