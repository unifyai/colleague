"""A weekly spend report whose spec arrives the way specs actually arrive.

The brief states the procedure once, in prose, including one rule nothing
will exercise for four weeks (foreign-currency rows convert at the rates
endpoint). The exact format — title, columns, string amounts — lands as
feedback after the first filing, the way it does when a person looks at a
draft. From then on nothing is restated.

Two later weeks are built to catch the two ways of automating this badly.
Week 4's personal-spend items stop sharing any token with the earlier
weeks' ("personal", "gift"), and a business item picks one of those tokens
up — so a keyword ladder distilled from the observed samples misses both
ways, while the judgment the brief actually asked for does not. Week 5 is
the first week a foreign-currency row appears: a procedure frozen from the
observed weeks (where every row was EUR) silently mis-converts, though the
brief's rule was sufficient all along. Week 6 renames one column in one
sentence and requires everything else — flags, conversion, order, title —
byte-identical in spirit and exact in fact.

Ground truth is recomputed from the tables below. The personal/business
label never appears in the API; descriptions are written so the call is
unambiguous to any competent judge and unreachable by lexical rules learned
from the earlier weeks.

USD amounts are forced even so conversion at 0.92 never lands on a half
cent — "nearest cent" stays exact without a rounding-convention dispute.
"""

from __future__ import annotations

from typing import Any

from colleague.harness.conversation import Participant
from colleague.harness.fixture_server import (
    FixtureServer,
    Request,
    missing_fields,
    reject,
    stable_hash,
)
from colleague.harness.persona import Persona, PersonaPool

DEFAULT_SEED = 20260801
DEFAULT_PORT = 8148

FIRST_WEEK = 1
COLUMNS_WEEK = 2
PARAPHRASE_WEEK = 4
OFFCYCLE_WEEK = 5
AMENDMENT_WEEK = 6
LAST_WEEK = 6

#: 1 USD = 0.92 EUR, held fixed by the fixture and served at GET /rates.
RATE_USD_TO_EUR_CENTS = 92

CATEGORIES = {
    "Meridian Travel": "travel",
    "Forsyth Catering": "meals",
    "Cobalt Cloud": "software",
    "Brightline Print": "marketing",
    "Atelier Nord": "supplies",
}

#: (vendor, description, personal, currency) per row, per week. Weeks 1–3
#: word personal spending the obvious way — "personal", "gift" — so a
#: lexical rule *appears* to work. Week 4 breaks it in both directions;
#: weeks 5–6 exercise the dormant currency rule; week 6 also replays one
#: paraphrased personal item so the amendment week is a regression test
#: for every earlier rule at once.
_WEEKS: dict[int, tuple[tuple[str, str, bool, str], ...]] = {
    1: (
        ("Cobalt Cloud", "Quarterly server hosting renewal", False, "EUR"),
        ("Forsyth Catering", "Client dinner - Halden contract renewal", False, "EUR"),
        (
            "Meridian Travel",
            "Personal trip add-on - two extra hotel nights in Lisbon",
            True,
            "EUR",
        ),
        ("Brightline Print", "Print run for the trade fair stand", False, "EUR"),
        ("Atelier Nord", "Birthday gift for my wife - engraved watch", True, "EUR"),
    ),
    2: (
        ("Cobalt Cloud", "Data pipeline add-on - monthly", False, "EUR"),
        ("Meridian Travel", "Flights to the Rotterdam client workshop", False, "EUR"),
        ("Atelier Nord", "Personal - new headphones for home", True, "EUR"),
        ("Forsyth Catering", "Team lunch after the release", False, "EUR"),
        ("Brightline Print", "Business cards for the sales team", False, "EUR"),
    ),
    3: (
        ("Meridian Travel", "Hotel for the Vienna audit visit", False, "EUR"),
        ("Atelier Nord", "Gift for my son's graduation - personal", True, "EUR"),
        ("Cobalt Cloud", "Server hosting renewal", False, "EUR"),
        ("Forsyth Catering", "Catering for the partner briefing", False, "EUR"),
        ("Brightline Print", "Trade fair banner reprint", False, "EUR"),
    ),
    4: (
        ("Meridian Travel", "Weekend spa stay with the family in Baden", True, "EUR"),
        (
            "Atelier Nord",
            "Client gift baskets - holiday campaign, approved budget",
            False,
            "EUR",
        ),
        (
            "Forsyth Catering",
            "Wedding anniversary dinner for two at La Rotonde",
            True,
            "EUR",
        ),
        ("Cobalt Cloud", "Server hosting renewal", False, "EUR"),
        ("Brightline Print", "Product brochure print run", False, "EUR"),
    ),
    5: (
        ("Meridian Travel", "Hotel block for the Chicago expo", False, "USD"),
        ("Cobalt Cloud", "Server hosting renewal", False, "EUR"),
        (
            "Brightline Print",
            "Expo flyers - rush order, Chicago printer",
            False,
            "USD",
        ),
        ("Forsyth Catering", "Catering for the quarterly review", False, "EUR"),
        (
            "Atelier Nord",
            "Personal - spare charger for my own laptop",
            True,
            "EUR",
        ),
    ),
    6: (
        ("Meridian Travel", "Return flight from the Chicago expo", False, "USD"),
        ("Forsyth Catering", "Family brunch on Sunday - my treat", True, "EUR"),
        ("Cobalt Cloud", "Server hosting renewal", False, "EUR"),
        ("Brightline Print", "Letterhead reorder", False, "EUR"),
        ("Atelier Nord", "Ergonomic chairs for the office", False, "EUR"),
    ),
}


def expenses_for(seed: int, week: int) -> list[dict[str, Any]]:
    rows = []
    for i, (vendor, description, _personal, currency) in enumerate(_WEEKS[week]):
        h = stable_hash(seed, "expense", week, vendor, i)
        cents = 700 + h % 480000
        if currency != "EUR":
            cents -= cents % 2  # even, so 0.92 conversion never hits a half cent
        rows.append(
            {
                "id": f"EXP-{week}-{i + 1}",
                "vendor": vendor,
                "category": CATEGORIES[vendor],
                "description": description,
                "amount_cents": cents,
                "currency": currency,
            },
        )
    return rows


def personal_ids(week: int) -> set[str]:
    """The rows a competent judge flags, from the labels the API never shows."""
    return {
        f"EXP-{week}-{i + 1}"
        for i, (_v, _d, personal, _c) in enumerate(_WEEKS[week])
        if personal
    }


def eur_cents(amount_cents: int, currency: str) -> int:
    """Euro cents for a row, at the fixture's fixed rate, nearest cent.

    USD amounts are even by construction, so ``* 92`` is never ``…50`` and
    nearest-cent is unambiguous.
    """
    if currency == "EUR":
        return amount_cents
    return (amount_cents * RATE_USD_TO_EUR_CENTS + 50) // 100


def amount_str(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def expected_title(week: int) -> str:
    return f"Northwind Client Spend - Week {week}"


def expected_columns(week: int) -> list[str]:
    amount = "amount" if week >= AMENDMENT_WEEK else "amount_eur"
    return ["vendor", "category", amount, "flagged"]


def expected_rows(seed: int, week: int) -> list[list[Any]]:
    """The filed rows a correct report contains, in API order."""
    flagged = personal_ids(week)
    return [
        [
            row["vendor"],
            row["category"],
            amount_str(eur_cents(row["amount_cents"], row["currency"])),
            row["id"] in flagged,
        ]
        for row in expenses_for(seed, week)
    ]


DANIEL = Participant(
    id="daniel",
    name="Daniel Okafor",
    role="the person you work for",
    email="daniel@northwind.example",
)


def _forbidden_outputs(seed: int) -> tuple[str, ...]:
    """The fixture's expected conversion outputs, which Daniel must never say.

    Daniel authored the dormant rule and may restate it verbatim; what he
    must never supply is the *result* of applying it — the converted euro
    amount of any foreign-currency row. If his stand-in ever does the
    arithmetic (or confirms the arm's), the trap week stops measuring the
    arm and the leak guard voids the cell.
    """
    out: list[str] = []
    for week in _WEEKS:
        for row in expenses_for(seed, week):
            if row["currency"] != "EUR":
                out.append(amount_str(eur_cents(row["amount_cents"], row["currency"])))
    return tuple(out)


def _personas(seed: int) -> PersonaPool:
    """Daniel, who answers questions the way the person who gave a spec does.

    Asking works — that is the honest economics of an intern's question —
    but every answer he gives is one the brief or the feedback already
    contained, and the scorer prices the round trip as DEGRADED rather
    than crediting it as memory. He listens on every channel the arm's
    product exposes: the runner seeds his own scripted sends (the brief,
    the feedback, the amendment) into his memory, so at week 6 his latest
    word — the rename — supersedes the format line below.
    """
    return PersonaPool(
        [
            Persona(
                participant=DANIEL,
                brief=(
                    "You are Daniel Okafor. You handed your assistant the "
                    "weekly client spend report: pull the week's expenses, "
                    "one row per expense in API order, flag anything that "
                    "looks like personal spending, and if a foreign-currency "
                    "expense ever appears, convert it at the rate from the "
                    "rates endpoint to the nearest cent — the report is "
                    "always in euros. After week 1 you fixed the format: "
                    "title exactly 'Northwind Client Spend - Week N', "
                    "columns exactly vendor, category, amount_eur, flagged "
                    "in that order, amounts as euro strings with exactly "
                    "two decimals, flagged a JSON boolean. Anything your own "
                    "later messages changed stands over this — your most "
                    "recent word is the spec. If asked, repeat only the "
                    "detail asked about, exactly as you gave it — you are "
                    "mildly impatient about repeating yourself and never "
                    "volunteer the whole spec again. For judgment calls on "
                    "a specific expense — whether something is personal — "
                    "tell them to use their own judgment; that is what you "
                    "asked for, and you never confirm or deny a specific "
                    "flag. You also never do their arithmetic: never "
                    "compute, confirm or repeat a converted amount — "
                    "restate the conversion rule instead."
                ),
                fallback="It's all in what I told you — check the brief.",
                fallback_label="repointed",
                forbidden=_forbidden_outputs(seed),
            ),
        ],
    )


#: The control's stand-in: same name on the channel, none of the spec. The
#: control establishes what the API alone yields, so the persona must not be
#: a side door to the format — he answers every format question with nothing,
#: and the leak guard holds him to it.
CONTROL_PERSONA_OVERRIDES: dict[str, dict[str, Any]] = {
    "daniel": {
        "brief": (
            "You are Daniel Okafor. An assistant is filing a weekly client "
            "spend report for you, but you have never told it anything "
            "about how the report should look — no title, no column names, "
            "no formatting rules, no flagging or conversion conventions — "
            "and you have none to give. If asked about any of that, say "
            "you have no particular format in mind and it should use its "
            "judgment. Do not invent preferences."
        ),
        "knowledge": {},
        "fallback": "No particular format in mind - use your judgment.",
        "fallback_label": "no_information",
        "forbidden": (
            "Northwind Client Spend",
            "amount_eur",
            "two decimals",
            "rates endpoint",
            "0.92",
        ),
        "fresh_memory": True,
    },
}


def build(*, seed: int = DEFAULT_SEED, port: int = DEFAULT_PORT) -> FixtureServer:
    fx = FixtureServer(seed=seed, port=port)
    fx.state["personas"] = _personas(seed)
    # Messages the arm's product sends to Daniel (the delivery bridge
    # re-posts them here) are witnessed on /reply and routed to his persona
    # by the runner's conversation loop — the duplex that lets a question
    # asked in a reply get answered like one asked through any other channel.
    fx.state["persona_channels"] = {
        "reply": {"who": "to", "text": "text", "channel": "message"},
    }

    def expenses(r: Request) -> tuple[int, Any]:
        try:
            week = int(r.q("week") or "0")
        except ValueError:
            return 400, {"error": "week must be an integer"}
        if week not in _WEEKS:
            return 404, {"error": f"no expenses for week {week}"}
        r.server.waypoints.reach("read_expenses", week=week)
        return 200, expenses_for(r.server.seed, week)

    def rates(r: Request) -> tuple[int, Any]:
        r.server.waypoints.reach("read_rates")
        return 200, {"base": "EUR", "USD": RATE_USD_TO_EUR_CENTS / 100}

    def report(r: Request) -> tuple[int, Any]:
        missing = missing_fields(r.body, "week", "title", "columns", "rows")
        if missing:
            return reject(r.server, "report", r.body, missing)
        r.server.waypoints.reach("report")
        r.server.recorder.record("report", r.body)
        return 200, {"status": "filed"}

    def reply(r: Request) -> tuple[int, Any]:
        # The delivery bridge's witness route: a product-channel message to
        # a person, recorded so scoring and the conversation loop read the
        # same evidence. Deliberately absent from API_DOC — an endpoint
        # advertised as a way to reach a person would be the /clarify
        # mistake again; only the bridge posts here.
        missing = missing_fields(r.body, "to", "text")
        if missing:
            return reject(r.server, "reply", r.body, missing)
        r.server.recorder.record("reply", r.body)
        return 200, {"status": "delivered"}

    fx.route("GET", "/expenses", expenses)
    fx.route("GET", "/rates", rates)
    fx.route("POST", "/report", report)
    fx.route("POST", "/reply", reply)
    return fx


API_DOC = """\
Expenses API at {base_url}:
  GET  {base_url}/expenses?week=<n> -> [{{id, vendor, category, description, amount_cents, currency}}]
  GET  {base_url}/rates             -> {{"base": "EUR", "USD": <euros per US dollar>}}
  POST {base_url}/report            -> body {{"week": <n>, "title": "<title>", "columns": ["<name>", ...], "rows": [[<cell>, ...], ...]}}

File one report per week; rows are lists in column order.\
"""
