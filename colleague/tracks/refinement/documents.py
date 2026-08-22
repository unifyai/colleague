"""The refinement track's corpus: a week of real documents from one seed.

The workload the 2026-08-22 regime demands: Daniel shares a weekly batch
of documents — a multi-page card statement, five vendor invoices, a stack
of phone-scanned receipts, and (week 1 only) a long onboarding brief plus
a corporate rate sheet — and expects one normalised spreadsheet back. The
questions the track has always asked ride unchanged on top: the trap
descriptions from the five-row era appear verbatim among the filler rows,
the dormant conversion rule now hides mid-way through the brief PDF, and
the flag call still separates judgment from keyword ladders.

Division of labour with `fixture.py`: the fixture owns the source of
truth (`rows_for` and the tables here are called from it) and recomputes
expected outputs from it; this module turns those rows into files. The
scorer never reads a generated document — if a renderer drifted from its
rows, the corpus and the ground truth would visibly disagree.

Three properties are engineered, and `selftest` asserts each:

**Reconciliation is required.** The statement lists every charge but no
descriptions; descriptions live on invoice lines. So the flag column can
only be filled by joining documents on the receipt/line reference.

**Vision is required.** Receipts are scan-distorted image-only pages, and
every personal-judgment row (and the week-4 decoy) is receipt-backed with
its invoice line reading "Card purchase — see receipt R-…". Text
extraction alone cannot reach the descriptions the flag checks score.

**Determinism is byte-level.** Same seed, same dials → identical files,
across processes. That is what keeps exact recomputed ground truth
possible at this scale.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from colleague.harness.documents import (
    DocStyle,
    DocumentPdf,
    ScanSpec,
    scan_pages,
    write_workbook,
)
from colleague.harness.fixture_server import stable_hash

# ---------------------------------------------------------------- dials


@dataclass(frozen=True)
class Dials:
    """Per-track scale dials — the axes the crossover measurement sweeps."""

    rows_per_week: int = 40
    receipt_fraction: float = 0.5
    """Fraction of rows that are receipt-backed (personal-judgment rows and
    the decoy are always receipt-backed on top of this)."""

    distort_fraction: float = 1.0
    """Fraction of receipts rendered as scans. Judgment-bearing receipts
    are always in the distorted set — the vision guarantee — so this dial
    thins only the ordinary ones."""


def dials() -> Dials:
    """Dials from the environment, defaults recorded in `Dials`."""
    return Dials(
        rows_per_week=int(os.environ.get("REFINEMENT_ROWS_PER_WEEK", "40")),
        receipt_fraction=float(os.environ.get("REFINEMENT_RECEIPT_FRACTION", "0.5")),
        distort_fraction=float(os.environ.get("REFINEMENT_DISTORT_FRACTION", "1.0")),
    )


# ------------------------------------------------------- description pools

#: Business filler templates per vendor. None may carry the marker tokens
#: ("personal", "gift") — those belong to the labelled pools below, and a
#: business filler carrying one would train the very ladder week 4 breaks.
_BUSINESS: dict[str, tuple[str, ...]] = {
    "Meridian Travel": (
        "Rail tickets - {city} client visit",
        "Hotel - {city} audit visit",
        "Flights - {city} partner workshop",
        "Airport transfer - {city} arrival",
        "Travel package - {city} conference",
    ),
    "Forsyth Catering": (
        "Catering - weekly team briefing",
        "Client lunch - {account} account review",
        "Coffee service restock",
        "Working dinner - project {code}",
        "Breakfast trays - board meeting",
    ),
    "Cobalt Cloud": (
        "Server hosting renewal",
        "Data pipeline add-on - monthly",
        "Object storage overage",
        "Compute credits top-up",
        "Monitoring plan - monthly",
    ),
    "Brightline Print": (
        "Letterhead reorder",
        "Product brochure print run",
        "Trade fair banner reprint",
        "Business cards - sales team",
        "Poster run - campaign {code}",
    ),
    "Atelier Nord": (
        "Office chairs restock",
        "Desk lamp replacements",
        "Whiteboard supplies reorder",
        "Stationery order - monthly",
        "Meeting room supplies",
    ),
}

_CITIES = ("Rotterdam", "Vienna", "Lyon", "Porto", "Malmo", "Basel")
_ACCOUNTS = ("Halden", "Verdane", "Ostrell", "Kepler")
_CODES = ("A7", "B3", "C9", "D4")

#: Personal filler wording for weeks 1-3 and 5: the obvious register, so a
#: lexical rule *appears* to work — exactly as the original five-row weeks
#: were written.
_PERSONAL_EARLY = (
    "Personal - {item} for home",
    "Birthday gift for {relation} - {item2}",
    "Personal top-up - {item}",
)

#: Personal filler wording for weeks 4 and 6: paraphrases sharing no
#: content token with any earlier personal description. The selftest
#: enforces the disjointness programmatically, so a new template cannot
#: quietly re-arm the keyword ladder.
_PERSONAL_LATE = (
    "Weekend at the lakeside cabin with the kids",
    "Anniversary flowers delivered to Amara",
    "Noise-cancelling earbuds for my commute",
    "Season seats, row F - the two of us",
)

_ITEMS = ("espresso machine", "bookshelf", "desk fan", "kettle")
_ITEMS2 = ("engraved watch", "fountain pen", "silk scarf")
_RELATIONS = ("my wife", "my son", "my sister")

#: The five-row era's scripted rows, verbatim — the traps live here.
#: (vendor, description, personal, currency) per week; see the track
#: README for what each week's rows are engineered to catch.
TRAP_ROWS: dict[int, tuple[tuple[str, str, bool, str], ...]] = {
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

#: Weeks whose personal wording must defeat a ladder learned from 1-3.
PARAPHRASE_WEEKS = (4, 6)

VENDORS = tuple(_BUSINESS)

#: Monday of each benchmark week, for statement dates. Fixed calendar —
#: the corpus describes a specific six weeks of a specific spring.
_WEEK_MONDAY = {
    1: (2026, 4, 6),
    2: (2026, 4, 13),
    3: (2026, 4, 20),
    4: (2026, 4, 27),
    5: (2026, 5, 4),
    6: (2026, 5, 11),
}


def _fill(template: str, rng: random.Random) -> str:
    return template.format(
        city=rng.choice(_CITIES),
        account=rng.choice(_ACCOUNTS),
        code=rng.choice(_CODES),
        item=rng.choice(_ITEMS),
        item2=rng.choice(_ITEMS2),
        relation=rng.choice(_RELATIONS),
    )


def _amount_cents(seed: int, week: int, vendor: str, index: int, currency: str) -> int:
    h = stable_hash(seed, "expense", week, vendor, index)
    cents = 700 + h % 480000
    if currency != "EUR":
        cents -= cents % 2  # even, so 0.92 conversion never hits a half cent
    return cents


def rows_for(seed: int, week: int, d: Dials | None = None) -> list[dict[str, Any]]:
    """The week's expenses, in statement order — the source of truth.

    Trap rows ride verbatim among seeded fillers; every field any document
    shows (and every field the scorer recomputes) derives from this list.
    Personal-judgment rows and the week-4 decoy are always receipt-backed;
    their receipts are always in the distorted set.
    """
    d = d or dials()
    rng = random.Random(stable_hash(seed, "corpus", week))

    entries: list[dict[str, Any]] = []
    for vendor, description, personal, currency in TRAP_ROWS[week]:
        entries.append(
            {
                "vendor": vendor,
                "description": description,
                "personal": personal,
                "currency": currency,
                "trap": True,
            },
        )

    n_fillers = max(0, d.rows_per_week - len(entries))
    personal_pool = _PERSONAL_LATE if week in PARAPHRASE_WEEKS else _PERSONAL_EARLY
    # One or two personal fillers per week reads like a real card; the rest
    # is ordinary business spend.
    n_personal = min(rng.randint(1, 2), n_fillers)
    for i in range(n_fillers):
        if i < n_personal:
            vendor = rng.choice(VENDORS)
            description = _fill(rng.choice(list(personal_pool)), rng)
            personal = True
        else:
            vendor = rng.choice(VENDORS)
            description = _fill(rng.choice(list(_BUSINESS[vendor])), rng)
            personal = False
        entries.append(
            {
                "vendor": vendor,
                "description": description,
                "personal": personal,
                "currency": "EUR",
                "trap": False,
            },
        )

    rng.shuffle(entries)

    receipts_needed = round(len(entries) * d.receipt_fraction)
    ordinary_receipt_slots = [
        i
        for i, e in enumerate(entries)
        if not e["personal"]
        and not (e["trap"] and week == 4 and "gift" in e["description"].lower())
    ]
    rng.shuffle(ordinary_receipt_slots)

    monday = _WEEK_MONDAY[week]
    receipt_no = 0
    for i, e in enumerate(entries):
        e["id"] = f"EXP-{week}-{i + 1}"
        e["ref"] = f"TXN-{week:02d}{i + 1:03d}"
        e["date"] = f"{monday[0]}-{monday[1]:02d}-{monday[2] + rng.randint(0, 4):02d}"
        e["amount_cents"] = _amount_cents(seed, week, e["vendor"], i, e["currency"])
        # Judgment-bearing rows are always receipt-backed: personal rows,
        # and the week-4 decoy whose wording carries the old marker.
        decoy = (
            e["trap"]
            and not e["personal"]
            and (
                "gift" in e["description"].lower()
                or "personal" in e["description"].lower()
            )
        )
        e["receipt"] = bool(e["personal"] or decoy)
    for i in ordinary_receipt_slots:
        if sum(1 for e in entries if e["receipt"]) >= receipts_needed:
            break
        entries[i]["receipt"] = True
    for e in entries:
        if e["receipt"]:
            receipt_no += 1
            e["receipt_ref"] = f"R-{week:02d}-{receipt_no:02d}"
        else:
            e["receipt_ref"] = ""

    # The distortion dial thins only the ordinary receipts; judgment-bearing
    # ones stay scans, or vision would stop being required exactly where it
    # matters.
    ordinary = [
        e
        for e in entries
        if e["receipt"]
        and not e["personal"]
        and not (
            e["trap"]
            and (
                "gift" in e["description"].lower()
                or "personal" in e["description"].lower()
            )
        )
    ]
    rng.shuffle(ordinary)
    n_distort = round(len(ordinary) * d.distort_fraction)
    distorted_refs = {e["receipt_ref"] for e in ordinary[:n_distort]}
    for e in entries:
        judgment = e["personal"] or (
            e["trap"]
            and (
                "gift" in e["description"].lower()
                or "personal" in e["description"].lower()
            )
        )
        e["distorted"] = bool(
            e["receipt"] and (judgment or e["receipt_ref"] in distorted_refs)
        )
    return entries


# ------------------------------------------------------------- renderers


def _vendor_style(seed: int, vendor: str) -> DocStyle:
    return DocStyle.derive(stable_hash(seed, "style", vendor))


_VENDOR_ADDRESS = {
    "Meridian Travel": "48 Quai des Grands Augustins, 75006 Paris",
    "Forsyth Catering": "Herengracht 210, 1016 BS Amsterdam",
    "Cobalt Cloud": "Invalidenstrasse 91, 10115 Berlin",
    "Brightline Print": "17 Cross Street, Manchester M2 4JF",
    "Atelier Nord": "Bredgade 30, 1260 Copenhagen",
}


def render_statement(seed: int, week: int, rows: list[dict[str, Any]]) -> bytes:
    """The card statement: every charge, no descriptions, category included.

    The merchant-category column is what keeps `category` a piece of data
    the arm holds every week — as the retired API's field was — so the
    things only week 1 teaches stay exactly the format and the rules.
    """
    from colleague.tracks.refinement.fixture import CATEGORIES

    doc = DocumentPdf(DocStyle.derive(stable_hash(seed, "style", "bank")))
    doc.page().heading("VERIDIAN COMMERCIAL BANK")
    doc.para("Corporate card statement - Northwind Trading GmbH")
    doc.kv(
        [
            ("Account", "DE44 5001 0517 5407 3249 31"),
            ("Card", "**** **** **** 4417 (D. Okafor)"),
            ("Statement week", f"Week {week}, {rows[0]['date'][:7]}"),
            ("Charges", str(len(rows))),
        ],
    )
    doc.para(
        "Charges are listed in posting order. Merchant category descriptions "
        "are supplied by the card network. Foreign-currency charges show the "
        "charged currency; no conversion is applied by the bank.",
    )
    doc.table(
        ["Ref", "Date", "Merchant", "Category", "Amount", "Currency"],
        [
            [
                e["ref"],
                e["date"],
                e["vendor"],
                CATEGORIES[e["vendor"]],
                f"{e['amount_cents'] // 100}.{e['amount_cents'] % 100:02d}",
                e["currency"],
            ]
            for e in rows
        ],
        widths=[0.15, 0.15, 0.25, 0.15, 0.16, 0.14],
        align=["L", "L", "L", "L", "R", "C"],
    )
    doc.para(
        "End of statement. Queries within 60 days to your account manager.",
        size=8,
    )
    return doc.bytes()


def render_invoice(
    seed: int,
    week: int,
    vendor: str,
    rows: list[dict[str, Any]],
) -> bytes:
    """One vendor's weekly invoice: descriptions live here — unless the
    charge is receipt-backed, in which case the line points at the receipt
    and the description exists only on the (distorted) receipt page."""
    style = _vendor_style(seed, vendor)
    doc = DocumentPdf(style)
    doc.page().heading(vendor.upper())
    doc.para(_VENDOR_ADDRESS[vendor])
    h = stable_hash(seed, "invoice", week, vendor)
    doc.kv(
        [
            ("Invoice", f"INV-{week:02d}-{h % 9000 + 1000}"),
            ("Bill to", "Northwind Trading GmbH, Accounts Payable"),
            ("Period", f"Week {week}"),
        ],
    )
    body = []
    for e in rows:
        description = (
            f"Card purchase - see receipt {e['receipt_ref']}"
            if e["receipt"]
            else e["description"]
        )
        body.append(
            [
                e["ref"],
                e["date"],
                description,
                f"{e['amount_cents'] // 100}.{e['amount_cents'] % 100:02d}",
                e["currency"],
            ],
        )
    doc.table(
        ["Ref", "Date", "Description", "Amount", "Currency"],
        body,
        widths=[0.14, 0.13, 0.47, 0.14, 0.12],
        align=["L", "L", "L", "R", "C"],
    )
    totals: dict[str, int] = {}
    for e in rows:
        totals[e["currency"]] = totals.get(e["currency"], 0) + e["amount_cents"]
    doc.kv(
        [
            (f"Total {cur}", f"{cents // 100}.{cents % 100:02d}")
            for cur, cents in sorted(totals.items())
        ],
    )
    doc.page().subheading("Terms and conditions of supply")
    doc.para(
        "Payment is due within 30 days of the invoice date. Charges settled "
        "by corporate card appear on this invoice for reconciliation only "
        "and are not due again; the reference on each line matches the "
        "reference your card statement carries for the same charge.",
    )
    doc.para(
        "Disputes must reference the line Ref and be raised within 14 days "
        "of the invoice date. Credit notes are issued against the original "
        "invoice number and appear on the following week's account summary. "
        "Where a delivery is short or damaged, the line is still invoiced "
        "and corrected by credit note once the return is processed.",
    )
    doc.para(
        "Late payment accrues interest at the statutory rate. Ownership of "
        "goods passes on payment in full; risk passes on delivery. Nothing "
        "in these terms limits liability that cannot be limited by law. "
        "This document is generated from our billing system and is valid "
        "without a signature.",
    )
    doc.rule()
    doc.para(
        "Registered office as shown on the letterhead. VAT registered in "
        "the country of supply. Queries to accounts, quoting the invoice "
        "number and week.",
        size=8,
    )
    return doc.bytes()


def render_receipt(seed: int, e: dict[str, Any]) -> bytes:
    """One charge's till receipt — where a receipt-backed description lives."""
    style = _vendor_style(seed, e["vendor"])
    doc = DocumentPdf(
        DocStyle(
            face=style.face,
            base_size=10.0,
            heading_size=13.0,
            margin_mm=30.0,
            table_rule=0.0,
            shaded_header=False,
        ),
    )
    doc.page().heading(e["vendor"])
    doc.para(_VENDOR_ADDRESS[e["vendor"]])
    doc.rule()
    doc.kv(
        [
            ("Receipt", e["receipt_ref"]),
            ("Date", e["date"]),
            ("Card", "**** 4417"),
        ],
    )
    doc.gap(2)
    doc.subheading(e["description"])
    doc.kv(
        [
            (
                "Amount",
                f"{e['amount_cents'] // 100}.{e['amount_cents'] % 100:02d} "
                f"{e['currency']}",
            ),
        ],
    )
    doc.rule()
    doc.para("Thank you for your business. Keep this receipt for your records.")
    return doc.bytes()


BRIEF_TITLE = "Northwind Trading - Assistant Onboarding Brief"

#: The operative sections are 7 (the report procedure, with the flag
#: judgment) and 9 (the dormant conversion rule). Everything else is the
#: realistic burying material an onboarding pack actually carries.
_BRIEF_SECTIONS: tuple[tuple[str, str], ...] = (
    (
        "1. Welcome",
        "Welcome aboard. This pack collects everything the assistant role "
        "touches at Northwind Trading: who we are, how the office runs, and "
        "the recurring work you will take over from Daniel Okafor. Read it "
        "once, keep it to hand, and ask Daniel when something here is "
        "genuinely ambiguous - though he will expect you to have read it.",
    ),
    (
        "2. The company",
        "Northwind Trading GmbH is a distribution and client-services firm "
        "operating across the EU, with the Hamburg office as headquarters "
        "and client engagements running from Lisbon to Vienna. Around sixty "
        "people work here. The client-facing teams travel often, the back "
        "office keeps them moving, and a small set of trusted vendors covers "
        "travel, catering, cloud infrastructure, print and office supplies.",
    ),
    (
        "3. Office logistics",
        "The office opens at 07:30 and closes at 20:00; badge access "
        "applies outside those hours. Meeting rooms are booked through the "
        "front desk. Deliveries arrive at the loading entrance on Wandsbeker "
        "Strasse. Visitors sign in at reception and must be accompanied on "
        "the second floor, where client records are kept.",
    ),
    (
        "4. Systems and accounts",
        "You will receive accounts for the document store, the messaging "
        "workspace and the shared calendar. Files shared with you by "
        "colleagues arrive as attachments on whatever channel they use to "
        "reach you; produced work goes back the same way. Do not mail "
        "client documents to personal addresses, and do not re-share a "
        "document outside the thread it arrived on without asking its owner.",
    ),
    (
        "5. Communication habits",
        "Daniel reads messages between meetings and answers briefly. If he "
        "has already answered something, expect him to say so rather than "
        "repeat himself. Colleagues will assume anything they sent you has "
        "been read within the day. When a request is ambiguous, a specific "
        "question beats a general one; when it is a judgment call inside "
        "work you own, make the call.",
    ),
    (
        "6. Expense policy - overview",
        "The corporate card is used by senior staff for both company spend "
        "and, occasionally and against policy, items that are really "
        "private purchases. Finance does not police the card at source; "
        "the weekly reporting described in the next section is where "
        "private items are caught. The card statement arrives weekly from "
        "Veridian Commercial Bank; vendors invoice weekly for their lines, "
        "and till receipts back individual card purchases.",
    ),
    (
        "7. The weekly client spend report",
        "This is the recurring deliverable you own. Each week Daniel "
        "shares the week's documents: the card statement, the vendor "
        "invoices, and the scanned receipts. Build one spreadsheet from "
        "them and send it back to him: one row per statement charge, in "
        "statement order. Amounts arrive in whatever the charge's currency "
        "was; the report is always in euros. The one thing Daniel really "
        "cares about: anything that looks like personal spending on the "
        "company card gets flagged - finance wants it marked, not dropped. "
        "Keep the row, mark it flagged. Use your judgment on the "
        "descriptions; they are free text and people word these however "
        "they like, and the descriptions for card purchases are often only "
        "on the till receipt the invoice line points at.",
    ),
    (
        "8. Records and retention",
        "Weekly documents and produced reports are retained for seven "
        "years. Nothing is deleted without written confirmation from "
        "finance. If a document arrives damaged or a page is unreadable, "
        "note it in your reply rather than guessing at the contents.",
    ),
    (
        "9. Foreign currency",
        "Client work is almost entirely eurozone, so expect euro charges. "
        "If a foreign-currency charge ever appears on the statement, "
        "convert it at the rate in the corporate rate sheet (shared with "
        "this brief as a spreadsheet), to the nearest cent. The report is "
        "always in euros. The rate sheet is updated by finance when rates "
        "move; use the sheet you were most recently given.",
    ),
    (
        "10. Working with vendors",
        "The five standing vendors are long-term relationships: Meridian "
        "Travel, Forsyth Catering, Cobalt Cloud, Brightline Print and "
        "Atelier Nord. Escalations go through Daniel, never directly to a "
        "vendor's finance team. Vendor invoices reconcile against the card "
        "statement by line reference; discrepancies within sixty days go "
        "to the bank, not the vendor.",
    ),
    (
        "11. Out-of-office and cover",
        "When Daniel travels, the weekly cadence does not pause. Documents "
        "may arrive a day late; the report is still expected for the week "
        "they cover. If you will be unavailable, say so before the week "
        "starts so cover can be arranged - silent gaps are the one thing "
        "the office does not forgive.",
    ),
    (
        "12. Closing note",
        "Most of this pack you will internalise in a week. The report in "
        "section 7 you will do every week for as long as you are here: it "
        "is the piece of your work finance sees, and the piece Daniel is "
        "judged on in turn. Take it seriously, keep hold of what he tells "
        "you about it, and improve quietly wherever the documents let you.",
    ),
)


def render_brief(seed: int) -> bytes:
    """The onboarding brief: one operative page in twelve, rule buried mid-doc."""
    doc = DocumentPdf(DocStyle.derive(stable_hash(seed, "style", "brief")))
    doc.page().heading(BRIEF_TITLE)
    doc.para(
        "Prepared for the incoming assistant. Internal - do not circulate "
        "outside Northwind Trading.",
    )
    doc.gap(4)
    doc.subheading("Contents")
    for title, _body in _BRIEF_SECTIONS:
        doc.para(title, size=9.5)
    for title, body in _BRIEF_SECTIONS:
        doc.page().subheading(title)
        doc.para(body)
    return doc.bytes()


#: 1 USD = 0.92 EUR — the same fixed rate the fixture recomputes with.
#: The other rows are realistic dressing no charge ever uses.
RATE_ROWS: tuple[tuple[str, float], ...] = (
    ("USD", 0.92),
    ("GBP", 1.15),
    ("CHF", 1.04),
    ("SEK", 0.088),
    ("JPY", 0.0061),
)


def render_rates(path: Path) -> None:
    write_workbook(
        path,
        {
            "Rates": [
                ["Corporate rate sheet - euros per unit of currency"],
                ["currency", "eur_per_unit"],
                *[[cur, rate] for cur, rate in RATE_ROWS],
            ],
        },
    )


# ------------------------------------------------------------- assembly


def build_week(seed: int, week: int, dest: Path, d: Dials | None = None) -> list[Path]:
    """Generate one week's corpus into ``dest``; returns paths in share order."""
    d = d or dials()
    dest.mkdir(parents=True, exist_ok=True)
    rows = rows_for(seed, week, d)
    out: list[Path] = []

    if week == 1:
        brief = dest / "northwind_assistant_brief.pdf"
        brief.write_bytes(render_brief(seed))
        out.append(brief)
        rates = dest / "corporate_fx_rates.xlsx"
        render_rates(rates)
        out.append(rates)

    statement = dest / f"card_statement_week_{week}.pdf"
    statement.write_bytes(render_statement(seed, week, rows))
    out.append(statement)

    for vendor in VENDORS:
        vendor_rows = [e for e in rows if e["vendor"] == vendor]
        if not vendor_rows:
            continue
        slug = vendor.lower().replace(" ", "_")
        invoice = dest / f"invoice_{slug}_week_{week}.pdf"
        invoice.write_bytes(render_invoice(seed, week, vendor, vendor_rows))
        out.append(invoice)

    for e in rows:
        if not e["receipt"]:
            continue
        receipt = render_receipt(seed, e)
        if e["distorted"]:
            receipt = scan_pages(
                receipt,
                None,
                seed=stable_hash(seed, "scan", e["receipt_ref"]),
                spec=ScanSpec(),
            )
        path = dest / f"receipt_{e['receipt_ref']}.pdf"
        path.write_bytes(receipt)
        out.append(path)

    return out
