"""Two corrections, three pieces of work, and no labels to help.

Neither correction names an id. Both name the digest the way a person would
— "the support one", "finance" — while the agent is in the middle of
creating a batch. Getting this right means holding several pieces of live
work distinctly enough to address one of them.

The failure this catches is not misunderstanding. It is an architecture where
in-flight work is a single undifferentiated thing, so a correction applies to
whatever the loop happens to be doing when it arrives.
"""

from __future__ import annotations

from typing import Any

from colleague.harness.capability import Outcome, ScenarioResult
from colleague.harness.conversation import Participant, Transcript
from colleague.harness.fixture_server import FixtureServer
from colleague.harness.interlocutor import ScriptedTurn
from colleague.harness.scoring import Scorecard
from colleague.tracks.concurrency.fixture import API_DOC

DANIEL = Participant(
    id="daniel",
    name="Daniel Okafor",
    role="the person you work for",
    email="daniel@northwind.example",
)


def scenarios(base_url: str) -> list[dict[str, Any]]:
    api = API_DOC.format(base_url=base_url)
    roster = Transcript(participants=[DANIEL]).roster()
    return [
        {
            "name": "route_corrections",
            "context": roster,
            "request": (
                f"{api}\n\n"
                "Set up three digests:\n"
                "  - sales, weekly, to daniel\n"
                "  - support, weekly, to daniel\n"
                "  - finance, monthly, to the cfo\n"
                "Create all three."
            ),
            "note": (
                "Corrections arrive after the first and second creations, "
                "naming digests the way a person would rather than by id."
            ),
        },
    ]


def turns(name: str) -> list[ScriptedTurn]:
    if name != "route_corrections":
        return []
    return [
        ScriptedTurn(
            label="fix_support",
            sender="daniel",
            text="Actually make the support one daily, not weekly.",
            waypoint="digest_created",
            nth=1,
            timeout=240,
        ),
        ScriptedTurn(
            label="fix_finance",
            sender="daniel",
            text="And finance should go to the board, not the cfo.",
            waypoint="digest_created",
            nth=2,
            timeout=240,
        ),
    ]


def mock_plan(
    *, scenario: str, mode: str, client, corrections, **_: Any
) -> dict[str, Any]:
    import time

    plan = [
        {"name": "sales", "frequency": "weekly", "recipient": "daniel"},
        {"name": "support", "frequency": "weekly", "recipient": "daniel"},
        {"name": "finance", "frequency": "monthly", "recipient": "cfo"},
    ]
    for spec in plan:
        client.post("/digests", spec)
        time.sleep(0.6)

    heard = " ".join(c["text"] for c in corrections).lower()
    if mode == "ideal":
        if "support one daily" in heard:
            client.post("/digests/update", {"name": "support", "frequency": "daily"})
        if "finance should go to the board" in heard:
            client.post("/digests/update", {"name": "finance", "recipient": "board"})
    elif heard:
        # The undifferentiated failure: corrections land on whatever was
        # most recently touched, rather than on the thing they name.
        client.post("/digests/update", {"name": "finance", "frequency": "daily"})
        client.post("/digests/update", {"name": "finance", "recipient": "board"})

    return client.get("/digests")


def score(name: str, fixture: FixtureServer, **_: Any) -> ScenarioResult:
    digests = fixture.state.get("digests", {})
    card = Scorecard(name)

    card.check(
        "created_all_three",
        set(digests) == {"sales", "support", "finance"},
        got=sorted(digests),
    )
    card.check(
        "support_now_daily",
        (digests.get("support") or {}).get("frequency") == "daily",
        support=digests.get("support"),
    )
    # The agent wrote "the board", echoing the correction's own wording.
    # Third identifier-form false negative after "daniel" and "carol nwosu";
    # the article is not a different recipient.
    finance_to = str((digests.get("finance") or {}).get("recipient", "")).lower()
    card.check(
        "finance_now_to_board",
        finance_to.removeprefix("the ").strip() == "board",
        finance=digests.get("finance"),
    )
    # The correction that was never made is as important as the ones that were.
    # "daniel" and "daniel@northwind.example" are the same recipient; the
    # roster gives the address and resolving to it is correct behaviour, not
    # a change to the digest.
    sales = digests.get("sales") or {}
    card.check(
        "sales_untouched",
        sales.get("frequency") == "weekly"
        and str(sales.get("recipient", "")).startswith("daniel"),
        sales=sales,
    )
    card.check(
        "finance_frequency_unchanged",
        (digests.get("finance") or {}).get("frequency") == "monthly",
        finance=digests.get("finance"),
    )

    outcome = Outcome.PASS if card.passed else Outcome.FAIL
    return ScenarioResult(
        name,
        outcome,
        card.as_dict(),
        "" if card.passed else f"failed: {', '.join(card.failures)}",
    )
