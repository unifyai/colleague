"""Watch someone do it on their screen, then do it on yours.

The request carries frames of Daniel's shared screen and says "do the same
on your board". It does not say what he did. An arm that cannot take images
resolves to UNSUPPORTED — its driver raises rather than guessing from text —
and an arm that can is scored on one thing: the final state of its own
board, against the state Daniel's demonstration produces. Nothing about the
frames is judged; nothing about the reply is judged.

A text control gives the same four steps in words. It establishes what the
API and the words alone yield, so the frame scenario can be read as "could
it see" rather than "could it use the API".

Two failure shapes are worth naming. Doing it on Daniel's board instead of
your own is the confusion the two-instance layout exists to catch, and it is
scored separately. Reproducing three of four steps is what an arm that read
the frames carelessly does, and the fourth step is the one with no new
ticket to anchor it.
"""

from __future__ import annotations

from typing import Any

from colleague.harness.capability import Outcome, ScenarioResult
from colleague.harness.conversation import Participant, Transcript
from colleague.harness.fixture_server import FixtureServer
from colleague.harness.scoring import Scorecard
from colleague.tracks.screenshare.fixture import (
    API_DOC,
    DEFAULT_SEED,
    DEMONSTRATION,
    FRAMES_PERSONA_OVERRIDES,
    INITIAL_TICKETS,
    NEW_TITLE,
    frames,
)

DANIEL = Participant(
    id="daniel",
    name="Daniel Okafor",
    role="the person you work for",
    email="daniel@northwind.example",
)
PARTICIPANTS = [DANIEL]


def scenarios(base_url: str) -> list[dict[str, Any]]:
    api = API_DOC.format(base_url=base_url)
    roster = Transcript(participants=PARTICIPANTS).roster()
    return [
        {
            "name": "follow_the_share",
            "context": roster,
            "request": (
                f"{api}\n\n"
                "I've just done a few things on my board while sharing my "
                "screen — the frames are what you saw, in order. Do the same "
                "on your board (/b); it starts in the same state mine did. "
                "Leave mine alone."
            ),
            "images": frames(DEFAULT_SEED),
            "sender": "daniel",
            # The steps exist only in the frames, so this scenario's Daniel
            # will not narrate them: asked what he did, he points back at
            # the share, and the leak guard voids the cell if his stand-in
            # types a step out — that would collapse the scenario into its
            # own text control.
            "persona_overrides": FRAMES_PERSONA_OVERRIDES,
            "note": (
                "The four steps exist only in the frames. Score is the final "
                "state of /b."
            ),
        },
        {
            "name": "follow_the_text",
            "context": roster,
            "request": (
                f"{api}\n\n"
                "On your board (/b), please: create a ticket 'Renew Halden "
                "contract' with priority high; assign it to meera; tag it "
                "'vendor'; and close the 'Old VAT query' ticket. Leave my "
                "board alone."
            ),
            "sender": "daniel",
            "note": ("Control: the same steps in words. What the API alone yields."),
        },
    ]


def mock_plan(
    *,
    scenario: str,
    mode: str,
    client,
    images=None,
    **_: Any,
) -> dict[str, Any]:
    if scenario == "follow_the_share" and not images:
        return {"error": "no frames received"}
    # The scripted arm 'sees' the demonstration by construction; the naive
    # plan does the work on the demonstrator's board and skips the step with
    # nothing new on screen to anchor it.
    inst = "b" if mode == "ideal" else "a"
    done = []
    for step in DEMONSTRATION:
        if mode == "naive" and step["action"] == "close":
            continue
        if step["action"] == "create":
            done.append(
                client.post(
                    f"/{inst}/tickets",
                    {"title": step["title"], "priority": step["priority"]},
                ),
            )
        elif step["action"] == "assign":
            done.append(
                client.post(
                    f"/{inst}/assign",
                    {"ticket": step["ticket"], "to": step["to"]},
                ),
            )
        elif step["action"] == "tag":
            done.append(
                client.post(
                    f"/{inst}/tag",
                    {"ticket": step["ticket"], "tag": step["tag"]},
                ),
            )
        elif step["action"] == "close":
            done.append(client.post(f"/{inst}/close", {"ticket": step["ticket"]}))
    return {"did": len(done), "on": inst}


def _by_id(tickets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {t["id"]: t for t in tickets}


def score(
    name: str,
    fixture: FixtureServer,
    *,
    record: dict[str, Any] | None = None,
    **_: Any,
) -> ScenarioResult:
    board_b = fixture.state["boards"]["b"]
    b = _by_id(board_b)
    initial = _by_id(INITIAL_TICKETS)
    card = Scorecard(name)

    new = [t for t in board_b if t["title"].strip().lower() == NEW_TITLE]
    ticket = new[0] if len(new) == 1 else {}
    card.check(
        "created_the_ticket_once",
        len(new) == 1 and ticket.get("priority") == "high",
        new=new,
    )
    card.check(
        "assigned_to_meera",
        ticket.get("assignee") == "meera",
        assignee=ticket.get("assignee"),
    )
    card.check(
        "tagged_vendor",
        "vendor" in (ticket.get("tags") or []),
        tags=ticket.get("tags"),
    )
    card.check(
        "closed_the_vat_query",
        (b.get("t-1") or {}).get("status") == "closed",
        t1=b.get("t-1"),
    )
    unchanged = (
        all(b.get(tid) == {**initial[tid]} for tid in ("t-2", "t-3"))
        and len(board_b) == len(INITIAL_TICKETS) + 1
    )
    card.check("nothing_else_changed", unchanged, board=board_b)
    a_mutations = [e for e in fixture.recorder.all() if e["kind"].startswith("a_")]
    card.check(
        "daniels_board_untouched",
        not a_mutations,
        mutations_on_a=len(a_mutations),
    )

    if card.passed:
        return ScenarioResult(name, Outcome.PASS, card.as_dict(), "")
    if a_mutations and not card.checks["created_the_ticket_once"]:
        reason = "did the work on the demonstrator's board instead of its own"
    else:
        reason = f"failed: {', '.join(card.failures)}"
    return ScenarioResult(name, Outcome.FAIL, card.as_dict(), reason)
