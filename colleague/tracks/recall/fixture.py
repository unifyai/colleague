"""Eight days of ordinary messages, and what is true at the end of them.

Nothing here is served over HTTP. The facts arrive the way facts arrive at
work — in passing, in messages about other things, some of them replaced a
few days later. The fixture exists so the runner has a server to hold, and
so the ground truth lives in one place: which value is *current* for each
question, and which values it replaced.

Every value is a distinctive literal, so recall is a containment test and a
stale answer is a containment test too.
"""

from __future__ import annotations

from typing import Any

from colleague.harness.fixture_server import FixtureServer

DEFAULT_SEED = 20260801
DEFAULT_PORT = 8149

#: (question id) -> {"current": marker, "stale": [markers replaced]}
TRUTH: dict[str, dict[str, Any]] = {
    "offsite": {"current": "leeds", "stale": ["bristol", "cardiff"]},
    "trellis_contact": {"current": "ekdahl", "stale": ["lindqvist"]},
    "deploy_window": {"current": ("wednesday", "11:00"), "stale": ["thursday"]},
    "portal_manager": {"current": "varga", "stale": []},
    "travel_code": {"current": "2210", "stale": []},
    "priya_cover": {"current": "haddad", "stale": []},
    "board_and_bucket": {"current": ("brandt", "ledger-exports-7"), "stale": []},
}

#: Daniel's messages, one per working day. Facts are stated in passing.
DAYS: list[str] = [
    # day 1
    "Morning. Couple of things from yesterday: the vendor portal finally "
    "assigned us an account manager — Ines Varga, she'll be our contact "
    "there. And the Q3 offsite is going to be in Bristol, second week of "
    "October. Nothing to do on either yet.",
    # day 2
    "Finance asked me to remind everyone that the ledger export job writes "
    "to the nw-ledger-exports-7 bucket now, not the old one. Also our "
    "contact at Trellis Packaging is Marta Lindqvist if anything comes up "
    "on the packaging order. Quiet day otherwise.",
    # day 3
    "Board pack process: it goes to Helena Brandt first for a read-through "
    "before anyone else sees it. Separately, staging deploy window is "
    "Thursday 14:00 for the foreseeable. That's all.",
    # day 4
    "Change of plan on the offsite — Bristol fell through, it's Cardiff "
    "now, same week. New expense code for travel is TRV-2210, use that for "
    "anything offsite-related. Priya's sorting the venue.",
    # day 5
    "Marta Lindqvist has left Trellis. Our contact there is now Jonas "
    "Ekdahl; he's picking up the packaging order. Otherwise nothing new.",
    # day 6
    "Platform moved the staging deploy window: it's Wednesday 11:00 from "
    "next week, not Thursday. Please don't schedule anything over it.",
    # day 7
    "Last change on the offsite, promise: Cardiff venue double-booked us, "
    "so it's Leeds. Also Priya is away for a fortnight from Monday — Omar "
    "Haddad is covering for her while she's out.",
    # day 8
    "Nothing new today. Just closing out the week.",
]

QUESTIONS: dict[str, str] = {
    "offsite": "Remind me — where's the Q3 offsite now?",
    "trellis_contact": "Who's our contact at Trellis these days?",
    "deploy_window": "When's the staging deploy window at the moment?",
    "portal_manager": "Who's our account manager at the vendor portal?",
    "travel_code": "What expense code do I use for offsite travel?",
    "priya_cover": "Who's covering for Priya while she's away?",
    "board_and_bucket": (
        "Two things: who gets the board pack first, and which bucket does "
        "the ledger export write to?"
    ),
}


def build(*, seed: int = DEFAULT_SEED, port: int = DEFAULT_PORT) -> FixtureServer:
    return FixtureServer(seed=seed, port=port)
