"""A weekly spend report whose spec arrives the way specs actually arrive.

The brief states the procedure once — in a long onboarding PDF, with the
dormant rule (foreign-currency charges convert at the shared rate sheet)
buried mid-document among eleven sections of ordinary onboarding prose.
The exact format — title, columns, string amounts — lands as feedback
after the first filing, the way it does when a person looks at a draft.
From then on nothing is restated.

Since the 2026-08-22 document-scale regime there is no API. Daniel shares
each week's documents as attachments — a multi-page card statement, five
vendor invoices, scanned receipts — and expects one normalised .xlsx
back. The statement carries every charge but no descriptions; invoice
lines carry descriptions unless the charge is receipt-backed, in which
case the line points at a receipt whose page is an image-only scan. So
the flag judgment requires cross-document reconciliation, and for every
judgment-bearing row it requires vision. The trap construction of the
five-row era rides unchanged on top (the trap descriptions appear
verbatim among the fillers): week 4's personal wording defeats keyword
ladders both ways, week 5 is the dormant rule's first input, week 6
renames one column and replays every earlier rule.

Ground truth is recomputed from the same seeded row tables the renderers
draw from (`documents.rows_for`); the scorer never reads a generated
document, so a renderer drifting from its rows would surface as corpus
and scorer disagreeing. USD amounts are forced even so conversion at
0.92 never lands on a half cent — "nearest cent" stays exact without a
rounding-convention dispute.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from colleague.harness.attachments import deliver_route
from colleague.harness.conversation import Participant
from colleague.harness.fixture_server import (
    FixtureServer,
    Request,
    missing_fields,
    reject,
)
from colleague.harness.persona import Persona, PersonaPool
from colleague.tracks.refinement.documents import (
    Dials,
    build_week,
    dials,
    rows_for,
)

DEFAULT_SEED = 20260801
DEFAULT_PORT = 8148

FIRST_WEEK = 1
COLUMNS_WEEK = 2
PARAPHRASE_WEEK = 4
OFFCYCLE_WEEK = 5
AMENDMENT_WEEK = 6
LAST_WEEK = 6

#: 1 USD = 0.92 EUR, fixed in the corporate rate sheet shared in week 1.
RATE_USD_TO_EUR_CENTS = 92

CATEGORIES = {
    "Meridian Travel": "travel",
    "Forsyth Catering": "meals",
    "Cobalt Cloud": "software",
    "Brightline Print": "marketing",
    "Atelier Nord": "supplies",
}


def expenses_for(seed: int, week: int, d: Dials | None = None) -> list[dict[str, Any]]:
    """The week's charges in statement order — the scorer's source of truth."""
    return rows_for(seed, week, d)


def personal_ids(seed: int, week: int) -> set[str]:
    """The rows a competent judge flags, from labels no document shows."""
    return {e["id"] for e in expenses_for(seed, week) if e["personal"]}


def eur_cents(amount_cents: int, currency: str) -> int:
    """Euro cents for a charge, at the rate sheet's fixed rate, nearest cent.

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
    """The data rows a correct report contains, in statement order."""
    return [
        [
            e["vendor"],
            CATEGORIES[e["vendor"]],
            amount_str(eur_cents(e["amount_cents"], e["currency"])),
            bool(e["personal"]),
        ]
        for e in expenses_for(seed, week)
    ]


DANIEL = Participant(
    id="daniel",
    name="Daniel Okafor",
    role="the person you work for",
    email="daniel@northwind.example",
)


def _forbidden_outputs(seed: int) -> tuple[str, ...]:
    """The expected conversion outputs, which Daniel must never say.

    Daniel authored the dormant rule and may restate it verbatim; what he
    must never supply is the *result* of applying it — the converted euro
    amount of any foreign-currency charge. If his stand-in ever does the
    arithmetic (or confirms the arm's), the trap week stops measuring the
    arm and the leak guard voids the cell.
    """
    out: list[str] = []
    for week in range(FIRST_WEEK, LAST_WEEK + 1):
        for e in expenses_for(seed, week):
            if e["currency"] != "EUR":
                out.append(amount_str(eur_cents(e["amount_cents"], e["currency"])))
    return tuple(out)


def _personas(seed: int) -> PersonaPool:
    """Daniel, who answers questions the way the person who gave a spec does.

    Asking works — that is the honest economics of an intern's question —
    but every answer he gives is one the brief or the feedback already
    contained, and the scorer prices the round trip as DEGRADED rather
    than crediting it as memory. He listens on every channel the arm's
    product exposes: the runner seeds his own scripted sends (the brief,
    the feedback, the amendment) into his memory, so at week 6 his latest
    word — the rename — supersedes the format line below. He cannot
    re-send files through a text answer: if the arm lost a document, he
    points back at the attachment he already shared.
    """
    return PersonaPool(
        [
            Persona(
                participant=DANIEL,
                brief=(
                    "You are Daniel Okafor. You handed your assistant the "
                    "weekly client spend report, with a full onboarding "
                    "brief PDF and a corporate rate sheet attached to your "
                    "first message, and you share each week's documents - "
                    "the card statement, the vendor invoices, the scanned "
                    "receipts - as attachments when you ask for the week. "
                    "The procedure, all stated in the brief: one row per "
                    "statement charge in statement order, flag anything "
                    "that looks like personal spending (keep the row, mark "
                    "it), and if a foreign-currency charge ever appears, "
                    "convert at the rate sheet's rate to the nearest cent - "
                    "the report is always in euros. After week 1 you fixed "
                    "the format: an .xlsx back, title in the first cell, "
                    "exactly 'Northwind Client Spend - Week N', then a "
                    "header row of exactly vendor, category, amount_eur, "
                    "flagged in that order, amounts as text with exactly "
                    "two decimals, flagged TRUE or FALSE. Anything your own "
                    "later messages changed stands over this - your most "
                    "recent word is the spec. If asked, repeat only the "
                    "detail asked about, exactly as you gave it - you are "
                    "mildly impatient about repeating yourself and never "
                    "volunteer the whole spec again. You cannot re-send or "
                    "paste the contents of a file in a message: if they "
                    "cannot find a document, tell them it is in the "
                    "attachments you already shared. For judgment calls on "
                    "a specific charge - whether something is personal - "
                    "tell them to use their own judgment; that is what you "
                    "asked for, and you never confirm or deny a specific "
                    "flag. You also never do their arithmetic: never "
                    "compute, confirm or repeat a converted amount - "
                    "restate the conversion rule instead."
                ),
                fallback="It's all in the brief and the files I sent - check them.",
                fallback_label="repointed",
                forbidden=_forbidden_outputs(seed),
            ),
        ],
    )


#: The control's stand-in: same name on the channel, none of the spec. The
#: control establishes what the shared documents alone yield, so the
#: persona must not be a side door to the format — he answers every format
#: question with nothing, and the leak guard holds him to it.
CONTROL_PERSONA_OVERRIDES: dict[str, dict[str, Any]] = {
    "daniel": {
        "brief": (
            "You are Daniel Okafor. An assistant is building a weekly "
            "client spend report for you from documents you shared, but "
            "you have never told it anything about how the report should "
            "look - no title, no column names, no formatting rules, no "
            "flagging or conversion conventions - and you have none to "
            "give. If asked about any of that, say you have no particular "
            "format in mind and it should use its judgment. Do not invent "
            "preferences."
        ),
        "knowledge": {},
        "fallback": "No particular format in mind - use your judgment.",
        "fallback_label": "no_information",
        "forbidden": (
            "Northwind Client Spend",
            "amount_eur",
            "two decimals",
            "rate sheet",
            "0.92",
        ),
        "fresh_memory": True,
    },
}


def stage_attachments(
    *, fixture: FixtureServer, scenario: str, dest: Path
) -> list[Path]:
    """Generate and stage the files Daniel shares with one scenario's message.

    Regenerated per scenario into the run's regenerable corpus tree. The
    unbriefed control gets week 3's documents and nothing else — no brief,
    no rate sheet — in a fresh directory, byte-identical to the main run's
    week 3 files by generation determinism.
    """
    week = 3 if scenario == "unbriefed_control" else int(scenario.split("_")[1])
    paths = build_week(fixture.seed, week, dest, dials())
    if scenario == "unbriefed_control":
        paths = [p for p in paths if "brief" not in p.name and "rates" not in p.name]
    return paths


def build(*, seed: int = DEFAULT_SEED, port: int = DEFAULT_PORT) -> FixtureServer:
    fx = FixtureServer(seed=seed, port=port)
    fx.state["personas"] = _personas(seed)
    fx.state["dials"] = dials().__dict__
    # Messages the arm's product sends to Daniel (the delivery bridge
    # re-posts them here) are witnessed on /reply and routed to his persona
    # by the runner's conversation loop — the duplex that lets a question
    # asked in a reply get answered like one asked through any other channel.
    fx.state["persona_channels"] = {
        "reply": {"who": "to", "text": "text", "channel": "message"},
    }

    def reply(r: Request) -> tuple[int, Any]:
        # The delivery bridge's witness route: a product-channel message to
        # a person, recorded so scoring and the conversation loop read the
        # same evidence. Never documented to the arm — an endpoint
        # advertised as a way to reach a person would be the /clarify
        # mistake again; only the bridge posts here.
        missing = missing_fields(r.body, "to", "text")
        if missing:
            return reject(r.server, "reply", r.body, missing)
        r.server.recorder.record("reply", r.body)
        return 200, {"status": "delivered"}

    fx.route("POST", "/reply", reply)
    # The returned artifact's witness route (/deliver): equally
    # undocumented; the CM adapter bridges its outbound attachments here,
    # and the runner bridges files collected from workspace arms.
    deliver_route(fx)
    return fx


def selftest_corpus() -> list[str]:
    """The document-scale guarantees, provable without an arm.

    Returns failure strings; empty means the corpus holds its properties:
    byte-determinism across generations, image-only scan pages exactly
    where declared, every judgment-bearing description unreachable by text
    extraction, and the week-4/6 paraphrase discipline that keeps keyword
    ladders beatable.
    """
    import tempfile

    from colleague.harness.documents import page_texts

    failures: list[str] = []
    seed = DEFAULT_SEED
    d = dials()

    with tempfile.TemporaryDirectory() as tmp:
        a_dir, b_dir = Path(tmp) / "a", Path(tmp) / "b"
        for week in range(FIRST_WEEK, LAST_WEEK + 1):
            a = build_week(seed, week, a_dir / str(week), d)
            b = build_week(seed, week, b_dir / str(week), d)
            if [p.name for p in a] != [p.name for p in b]:
                failures.append(f"refinement corpus week {week}: file sets differ")
                continue
            for pa, pb in zip(a, b):
                if pa.read_bytes() != pb.read_bytes():
                    failures.append(
                        f"refinement corpus week {week}: {pa.name} is not "
                        "byte-deterministic",
                    )

            rows = rows_for(seed, week, d)
            corpus_text = ""
            for p in a:
                if p.suffix == ".pdf":
                    corpus_text += "\n".join(page_texts(p.read_bytes()))

            # Every distorted receipt is image-only; every judgment-bearing
            # description is on a distorted receipt and nowhere else.
            for e in rows:
                if e["distorted"]:
                    receipt = next(
                        p for p in a if p.name == f"receipt_{e['receipt_ref']}.pdf"
                    )
                    texts = page_texts(receipt.read_bytes())
                    if any(t.strip() for t in texts):
                        failures.append(
                            f"refinement week {week}: {receipt.name} declared "
                            "distorted but still carries a text layer",
                        )
                judgment = e["personal"] or (
                    e["trap"]
                    and not e["personal"]
                    and (
                        "gift" in e["description"].lower()
                        or "personal" in e["description"].lower()
                    )
                )
                if judgment:
                    if not e["distorted"]:
                        failures.append(
                            f"refinement week {week}: judgment row {e['id']} "
                            "is not on a distorted receipt — vision is not "
                            "required where it must be",
                        )
                    if e["description"] in corpus_text:
                        failures.append(
                            f"refinement week {week}: judgment description "
                            f"{e['description']!r} is reachable by text "
                            "extraction",
                        )

    # The paraphrase discipline: weeks 4 and 6 personal wording shares no
    # content token with weeks 1-3 personal wording, and week 4 carries a
    # business decoy with an old marker token.
    stop = {
        "the",
        "for",
        "and",
        "with",
        "two",
        "row",
        "own",
        "not",
        "our",
        "office",
        "sunday",
        "delivered",
    }

    def content_tokens(text: str) -> set[str]:
        return {
            t.strip(".,-'’s").lower() for t in text.split() if len(t.strip(".,-")) > 3
        } - stop

    early: set[str] = set()
    for week in (1, 2, 3):
        for e in rows_for(seed, week, d):
            if e["personal"]:
                early |= content_tokens(e["description"])
    for week in (4, 6):
        decoy_present = False
        for e in rows_for(seed, week, d):
            marked = (
                "personal" in e["description"].lower()
                or "gift" in e["description"].lower()
            )
            if e["personal"]:
                shared = content_tokens(e["description"]) & early
                if marked or shared:
                    failures.append(
                        f"refinement week {week}: personal row {e['id']} "
                        f"({e['description']!r}) shares tokens "
                        f"{sorted(shared) if shared else ['personal/gift']} "
                        "with the early weeks — the keyword ladder would "
                        "survive",
                    )
            elif marked:
                decoy_present = True
        if week == PARAPHRASE_WEEK and not decoy_present:
            failures.append(
                "refinement week 4: no business decoy carries an old marker "
                "token — the ladder is not punished for false flags",
            )

    # The dormant rule stays dormant: no foreign currency before week 5.
    for week in (1, 2, 3, 4):
        if any(e["currency"] != "EUR" for e in rows_for(seed, week, d)):
            failures.append(
                f"refinement week {week}: foreign currency before the "
                "off-cycle week fires the dormant rule early",
            )
    for week in (5, 6):
        if not any(e["currency"] != "EUR" for e in rows_for(seed, week, d)):
            failures.append(
                f"refinement week {week}: no foreign-currency charge — the "
                "dormant-rule trap never fires",
            )

    return failures
