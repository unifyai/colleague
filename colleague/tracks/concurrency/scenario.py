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
PRIYA = Participant(
    id="priya",
    name="Priya Raman",
    role="Chief of Staff",
    email="priya@northwind.example",
    standing="May ask you for things directly.",
)
BOB = Participant(
    id="bob",
    name="Bob Ferrall",
    role="contractor on the platform team",
    email="bob@ferrall-consulting.example",
    standing="May ask you for things directly.",
)

#: The scenario's full cast, for arms that maintain a real contact
#: store: the runner seeds these so the environment contains the
#: people the roster text describes.
PARTICIPANTS = [DANIEL, PRIYA, BOB]


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
                "Recipients are plain labels the digest service resolves on "
                "its own side — pass them as given, they are not email "
                "addresses for you to look up. You have everything you need; "
                "create all three now."
            ),
            "note": (
                "Corrections arrive after the first and second creations, "
                "naming digests the way a person would rather than by id."
            ),
        },
        {
            "name": "three_senders",
            "context": Transcript(participants=PARTICIPANTS).roster(),
            "request": (
                f"{api}\n\n"
                "Set up a sales digest, weekly, to daniel. Recipients are "
                "plain labels the digest service resolves — pass them as "
                "given. Create it now."
            ),
            "note": (
                "Two more people arrive with their own requests while the "
                "first is running, then each corrects *their own* digest "
                "with the word 'mine'. Routing needs the sender, not just "
                "the text."
            ),
        },
    ]


def turns(name: str) -> list[ScriptedTurn]:
    if name == "three_senders":
        return [
            ScriptedTurn(
                label="priya_request",
                sender="priya",
                text="Can you also set up a support digest for me — weekly, to priya?",
                waypoint="digest_created",
                nth=1,
                timeout=240,
            ),
            ScriptedTurn(
                label="bob_request",
                sender="bob",
                text="And a finance digest for me please, monthly, to bob.",
                waypoint="digest_created",
                nth=1,
                timeout=240,
            ),
            ScriptedTurn(
                label="priya_correction",
                sender="priya",
                text="Actually make mine daily, not weekly.",
                waypoint="digest_created",
                nth=3,
                timeout=240,
            ),
            ScriptedTurn(
                label="bob_correction",
                sender="bob",
                text="And mine should go to the board, not to me.",
                waypoint="digest_created",
                nth=3,
                timeout=240,
            ),
        ]
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
    *,
    scenario: str,
    mode: str,
    client,
    corrections,
    **_: Any,
) -> dict[str, Any]:
    import time

    if scenario == "three_senders":
        client.post(
            "/digests",
            {"name": "sales", "frequency": "weekly", "recipient": "daniel"},
        )
        time.sleep(0.8)
        # The other two requests have arrived by now.
        seen = [c for c in corrections if "digest" in c["text"].lower()]
        for c in seen:
            who = str(c.get("sender") or "")
            name = "support" if who == "priya" else "finance"
            client.post(
                "/digests",
                {
                    "name": name,
                    "frequency": "weekly" if who == "priya" else "monthly",
                    "recipient": who,
                },
            )
            time.sleep(0.8)
        fixes = [c for c in corrections if "mine" in c["text"].lower()]
        for c in fixes:
            who = str(c.get("sender") or "")
            if mode == "ideal":
                target = "support" if who == "priya" else "finance"
            else:
                # Sender ignored: "mine" lands on the most recent digest.
                target = "finance"
            if "daily" in c["text"].lower():
                client.post("/digests/update", {"name": target, "frequency": "daily"})
            if "board" in c["text"].lower():
                client.post("/digests/update", {"name": target, "recipient": "board"})
        return client.get("/digests")

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


def score(
    name: str,
    fixture: FixtureServer,
    *,
    record: dict[str, Any] | None = None,
    **_: Any,
) -> ScenarioResult:
    digests = fixture.state.get("digests", {})
    card = Scorecard(name)
    journal = (record or {}).get("interlocutor", []) or []

    if name == "route_corrections":
        # An arm with no way into a running turn was never offered either
        # correction; the digests it created are not a routing result.
        offered = [e for e in journal if e.get("delivered")]
        if journal and not offered:
            return ScenarioResult(
                name,
                Outcome.UNSUPPORTED,
                {"modes": sorted({str(e.get("mode")) for e in journal})},
                "no channel exists to reach work that has already started",
            )

    if name == "three_senders":
        undelivered = [e["label"] for e in journal if not e.get("delivered")]
        if any(l.endswith("_request") for l in undelivered):
            # A second person could not reach the assistant while it was
            # working, so no concurrent work ever existed to route into.
            return ScenarioResult(
                name,
                Outcome.UNSUPPORTED,
                {"undelivered": undelivered},
                "no channel for a second person to reach the running assistant",
            )
        card.check(
            "created_all_three",
            set(digests) == {"sales", "support", "finance"},
            got=sorted(digests),
        )
        support = digests.get("support") or {}
        finance = digests.get("finance") or {}
        sales = digests.get("sales") or {}
        card.check(
            "priya_correction_on_priyas",
            support.get("frequency") == "daily",
            support=support,
        )
        card.check(
            "bob_correction_on_bobs",
            str(finance.get("recipient", "")).lower().removeprefix("the ").strip()
            == "board",
            finance=finance,
        )
        card.check(
            "finance_frequency_unchanged",
            finance.get("frequency") == "monthly",
            finance=finance,
        )
        card.check(
            "support_recipient_unchanged",
            str(support.get("recipient", "")).startswith("priya"),
            support=support,
        )
        card.check(
            "sales_untouched",
            sales.get("frequency") == "weekly"
            and str(sales.get("recipient", "")).startswith("daniel"),
            sales=sales,
        )
        outcome = Outcome.PASS if card.passed else Outcome.FAIL
        return ScenarioResult(
            name,
            outcome,
            card.as_dict(),
            "" if card.passed else f"failed: {', '.join(card.failures)}",
        )

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
