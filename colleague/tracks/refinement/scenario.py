"""Brief once, refine once, then ask for it again — and watch what froze.

The track joins two halves the suite already had separately: drip-fed
teaching (`teaching`) and exact structural regression on a recurring
artifact (`standing/change_without_regression`). One recurring
deliverable — a weekly client spend report — gets its spec the way specs
actually arrive: a long onboarding brief (a PDF, with the dormant
foreign-currency rule buried mid-document), then format feedback on the
first draft, then nothing restated for four weeks, then a one-sentence
amendment.

Since the 2026-08-22 document-scale regime the work is real: each week
Daniel attaches a multi-page card statement, five vendor invoices and a
stack of scanned receipts, and expects one normalised .xlsx back. The
flag judgment requires reconciling statement lines to invoice lines to
image-only receipt scans — extraction, cross-document joining, vision,
judgment — and the scorer parses the returned workbook against ground
truth recomputed from the seeded source tables.

What the later weeks measure is calibration of the structure/judgment
boundary, not just retention. Week 4's personal-spend wording shares no
token with the earlier weeks' samples while a business decoy carries one
— a keyword ladder fails both ways. Week 5 is the first foreign-currency
week — a procedure frozen from the observed weeks silently mis-converts,
though the buried rule was stated on day one. Week 6 renames one column
and requires every other rule to hold in the same scorecard.

Asking again is priced, not forbidden: a correct week that needed a
clarification resolves DEGRADED — the answer was already given, and the
round trip is the cost the arm chose to pay. Cost per week is reported
from the ledger and never scored; across the six weeks that ledger is
the drip-fed amortisation curve this track exists to produce — and at
document scale, the curve the whole regime change was made to measure.

The control is the honest one: no brief, ever, in a session that never
saw one, over the same week-3 documents. The exact format is not
discoverable from the documents, so it resolves UNSUPPORTED for
everybody, and an arm that passes it has told you its later weeks were
inference, not retention.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from colleague.harness.capability import Outcome, ScenarioResult
from colleague.harness.conversation import Transcript
from colleague.harness.documents import read_workbook, write_workbook
from colleague.harness.fixture_server import FixtureServer
from colleague.harness.scoring import Scorecard
from colleague.tracks.refinement.fixture import (
    CATEGORIES,
    CONTROL_PERSONA_OVERRIDES,
    DANIEL,
    amount_str,
    eur_cents,
    expected_columns,
    expected_rows,
    expected_title,
    expenses_for,
    personal_ids,
)
from colleague.tracks.refinement.human import surface_for

SESSION_SCOPE = "track"

#: The scenario's full cast, for arms that maintain a real contact store.
PARTICIPANTS = [DANIEL]

BRIEF = """\
Let me hand you the weekly client spend report.

I've attached the onboarding brief - everything about the role is in
there, including how this report works (section 7, but read the whole
thing once). The corporate rate sheet is attached too; file it wherever
you keep reference material. And this week's documents are attached: the
card statement, the vendor invoices, and the scanned receipts.

Build the week's report from the documents and send it back to me as a
spreadsheet. Week 1 first - I'll take a look at your draft.\
"""

COLUMNS_FEEDBACK = """\
Looked at week 1 — good start. Two things, and this is how I want it
every week from now on.

Send it as an .xlsx. First cell: the title, exactly "Northwind Client
Spend - Week 2" — same pattern every week, with the week number. Second
row: the column headers, exactly vendor, category, amount_eur, flagged,
in that order. Then one row per statement charge, in statement order.
category is the statement's category for the charge. amount_eur is text
in euros with exactly two decimals — "812.40", never 812.4. flagged is
TRUE or FALSE, your personal-spend call. Nothing else on the sheet.

This week's documents are attached. File week 2.\
"""

AMENDMENT = (
    'One change from finance: the amount column is called "amount" now, '
    'not "amount_eur" — still euros, same format. Everything else stays '
    "exactly as it is. This week's documents are attached. File week 6."
)

CONTROL_REQUEST = (
    "The documents for week 3 of the client spend report are attached - "
    "the card statement, the vendor invoices, the receipts. Build the "
    "week's report from them and send it back to me as a spreadsheet."
)


def _file_week(week: int) -> str:
    return (
        f"This week's documents are attached. File the spend report for "
        f"week {week}."
    )


def _week_of(name: str) -> int:
    if name == "unbriefed_control":
        return 3
    return int(name.split("_")[1])


def _norm(text: Any) -> str:
    return " ".join(str(text or "").lower().split())


def scenarios(base_url: str) -> list[dict[str, Any]]:
    # Weeks arrive weeks apart, and no deployed system stays warm across
    # that gap: the CM retires its pod after ten idle minutes, a gateway
    # process exits, a laptop closes. Every week after the first therefore
    # declares `sleep` — the runner kills the process and boots a fresh one
    # over the same durable world (same stores, same on-disk session rows,
    # same workspace where week 1's rate sheet still sits), so what an arm
    # carries between weeks is exactly what it durably persisted, never a
    # trajectory that happened to stay warm in RAM.
    del base_url  # no API to document since the document-scale regime
    roster = Transcript(participants=[DANIEL]).roster()
    return [
        {
            "name": "week_1_briefed",
            "participant_title": "Week 1",
            "participant_preview": (
                "Take on a weekly client spend report and file its first week."
            ),
            "context": roster,
            "request": BRIEF,
            "attachments": True,
            "surface": surface_for(BRIEF),
            "persist": True,
            "sender": "daniel",
            "clarify_persona": "daniel",
            "note": (
                "The brief PDF, its dormant rule buried mid-document, plus "
                "the rate sheet and the week's documents. No format is fixed "
                "yet, so only returning a file is scored; the measurement is "
                "every later week."
            ),
        },
        {
            "name": "week_2_columns",
            "participant_title": "Week 2",
            "participant_preview": ("File the next week of the client spend report."),
            "request": COLUMNS_FEEDBACK,
            "attachments": True,
            "surface": surface_for(COLUMNS_FEEDBACK),
            "continue": True,
            "sleep": True,
            "sender": "daniel",
            "note": (
                "The format feedback on the first draft: exact title, exact "
                "columns in order, text amounts, TRUE/FALSE flags. In force "
                "from this round on."
            ),
        },
        {
            "name": "week_3_replay",
            "participant_title": "Week 3",
            "participant_preview": ("File another week of the client spend report."),
            "request": _file_week(3),
            "attachments": True,
            "surface": surface_for(_file_week(3)),
            "continue": True,
            "sleep": True,
            "sender": "daniel",
            "note": (
                "Nothing restated — not the columns, not the title, not "
                "the flag rule. The drip-fed spec is the procedure now."
            ),
        },
        {
            "name": "week_4_paraphrase",
            "participant_title": "Week 4",
            "participant_preview": ("File another week of the client spend report."),
            "request": _file_week(4),
            "attachments": True,
            "surface": surface_for(_file_week(4)),
            "continue": True,
            "sleep": True,
            "sender": "daniel",
            "note": (
                "The personal items stop sharing tokens with the earlier "
                "weeks' samples and a business item picks one up — on "
                "image-only receipt scans. A keyword ladder over extracted "
                "text fails every way at once."
            ),
        },
        {
            "name": "week_5_offcycle",
            "participant_title": "Week 5",
            "participant_preview": ("File another week of the client spend report."),
            "request": _file_week(5),
            "attachments": True,
            "surface": surface_for(_file_week(5)),
            "continue": True,
            "sleep": True,
            "sender": "daniel",
            "note": (
                "The dormant rule fires: the statement's first USD charges. "
                "A procedure frozen from the observed weeks silently "
                "mis-converts; the brief's buried rule was always sufficient."
            ),
        },
        {
            "name": "week_6_amendment",
            "participant_title": "Week 6",
            "participant_preview": ("File another week of the client spend report."),
            "request": AMENDMENT,
            "attachments": True,
            "surface": surface_for(AMENDMENT),
            "continue": True,
            "sleep": True,
            "sender": "daniel",
            "note": (
                "One column renamed in one sentence. The flags, the "
                "conversion, the order and the title are not mentioned "
                "and must not move — week 6's rows replay both traps."
            ),
        },
        {
            "name": "unbriefed_control",
            "participant_title": "Fresh Start",
            "participant_preview": (
                "File one week of a client spend report in a fresh workspace."
            ),
            "request": CONTROL_REQUEST,
            "attachments": True,
            "surface": surface_for(CONTROL_REQUEST),
            "fresh_session": True,
            # The persona boundary holds for the control by construction:
            # the Daniel this scenario meets never gave a brief, has no
            # format to restate on any channel, and the leak guard voids
            # the cell if his stand-in invents one. Without this, asking
            # him would be a side door to the spec the control exists to
            # prove undiscoverable. The staged documents likewise exclude
            # the brief and the rate sheet.
            "persona_overrides": CONTROL_PERSONA_OVERRIDES,
            "note": (
                "The control: no brief, ever, in a session that never saw "
                "one, over the same week-3 documents. Establishes what the "
                "documents alone yield."
            ),
        },
    ]


def mock_plan(
    *,
    scenario: str,
    mode: str,
    fixture,
    memory,
    workdir,
    **_: Any,
) -> dict[str, Any]:
    week = _week_of(scenario)
    ideal = mode == "ideal"
    if ideal:
        if scenario == "week_2_columns":
            memory["spec"] = "columns"
        if scenario == "week_6_amendment":
            memory["renamed"] = True

    rows = expenses_for(fixture.seed, week)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    if ideal and scenario != "unbriefed_control" and memory.get("spec") == "columns":
        # The taught arm: exact format from week 2's feedback, the dormant
        # conversion rule from the brief, and the flag call made from the
        # fixture's own labels — the scripted stand-in for live judgment
        # over the receipt scans, which is exactly what a keyword ladder
        # over extracted text is not.
        flagged = personal_ids(fixture.seed, week)
        amount_col = "amount" if memory.get("renamed") else "amount_eur"
        sheet = [
            [f"Northwind Client Spend - Week {week}"],
            ["vendor", "category", amount_col, "flagged"],
            *[
                [
                    e["vendor"],
                    CATEGORIES[e["vendor"]],
                    amount_str(eur_cents(e["amount_cents"], e["currency"])),
                    e["id"] in flagged,
                ]
                for e in rows
            ],
        ]
        path = workdir / f"client_spend_week_{week}.xlsx"
        write_workbook(path, {"report": sheet})
        return {"filed": week, "rows": len(rows), "deliverable": str(path)}

    # Week 1 (no format fixed yet) and every naive week: the obvious
    # spreadsheet — improvised title and columns, float amounts straight
    # off the statement with no conversion, and the flag call downgraded
    # to a keyword ladder over whatever text the documents would yield.
    sheet = [
        [f"Week {week} spend report"],
        ["vendor", "description", "amount", "flagged"],
        *[
            [
                e["vendor"],
                e["description"],
                e["amount_cents"] / 100,
                any(
                    token in e["description"].lower() for token in ("personal", "gift")
                ),
            ]
            for e in rows
        ],
    ]
    path = workdir / f"spend_report_week_{week}.xlsx"
    write_workbook(path, {"report": sheet})
    return {"filed": week, "improvised": True, "deliverable": str(path)}


def _parse_report(stored_path: str) -> dict[str, Any] | None:
    """The returned workbook's first sheet as title/columns/rows, or None.

    Container tolerance only: trailing empty cells are trimmed per row,
    and value types are preserved exactly — whether an amount came back
    as the text "812.40" or the number 812.4 is scored, not smoothed.
    """
    try:
        sheets = read_workbook(stored_path)
    except Exception:  # noqa: BLE001 - unparseable is a scored fact
        return None
    if not sheets:
        return None
    rows = next(iter(sheets.values()))

    def trim(row: list[Any]) -> list[Any]:
        out = list(row)
        while out and out[-1] is None:
            out.pop()
        return out

    trimmed = [trim(r) for r in rows]
    return {
        "title": (trimmed[0][0] if trimmed and trimmed[0] else None),
        "columns": trimmed[1] if len(trimmed) > 1 else [],
        "rows": [r for r in trimmed[2:]],
    }


def _normalize_flag(value: Any, *, accept_strings: bool = True) -> Any:
    """The declared flag tolerance: booleans, or the words TRUE/FALSE.

    In a spreadsheet a boolean cell and a text cell reading "TRUE" are
    indistinguishable to the person the feedback was written for, so both
    are accepted; anything else is returned untouched and fails equality.
    `selftest` sweeps `accept_strings` to prove no verdict depends on it.
    """
    if accept_strings and isinstance(value, str):
        folded = value.strip().upper()
        if folded == "TRUE":
            return True
        if folded == "FALSE":
            return False
    return value


def score(
    name: str,
    fixture: FixtureServer,
    *,
    record: dict[str, Any] | None = None,
    accept_flag_strings: bool = True,
    amount_eps: float | None = None,
    **_: Any,
) -> ScenarioResult:
    """Parse the returned artifact against recomputed ground truth.

    The tolerance policy, declared: the title folds case and whitespace;
    flags accept booleans or the words TRUE/FALSE; amounts are exact text
    (`amount_eps` exists only for the selftest sweep, which proves the
    verdicts do not move as it varies — the fixture must never measure
    its own threshold).
    """
    week = _week_of(name)
    deliveries = fixture.recorder.all("deliver")
    clarifications = (record or {}).get("clarifications") or []
    # The DEGRADED trigger reads the persona's own labels, not the channel:
    # Daniel re-supplying the spec over the product's message channel costs
    # exactly what re-supplying it through the clarification hook does.
    restated = [
        e for e in (record or {}).get("persona") or [] if e.get("label") == "restated"
    ]
    card = Scorecard(name)
    card.evidence["deliveries"] = len(deliveries)
    card.evidence["clarifications"] = len(clarifications)
    card.evidence["restated_answers"] = len(restated)
    if deliveries:
        card.evidence["delivered_via"] = [
            (d.get("payload") or {}).get("via") for d in deliveries
        ]

    if name == "week_1_briefed":
        # No format has been fixed yet, so the draft's shape is free; the
        # feedback that fixes it is the next scenario. Scored on a file
        # coming back at all.
        card.check("report_returned", bool(deliveries))
        outcome = Outcome.PASS if card.passed else Outcome.FAIL
        return ScenarioResult(
            name,
            outcome,
            card.as_dict(),
            "" if card.passed else f"failed: {', '.join(card.failures)}",
        )

    cols = expected_columns(week)
    want = expected_rows(fixture.seed, week)
    payload = (deliveries[-1].get("payload") or {}) if deliveries else {}
    parsed = _parse_report(payload.get("stored_path") or "") if payload else None

    card.check("delivered_once", len(deliveries) == 1)
    card.check("parseable", parsed is not None, filename=payload.get("filename"))
    if parsed is None:
        return ScenarioResult(
            name,
            Outcome.UNSUPPORTED if name == "unbriefed_control" else Outcome.FAIL,
            card.as_dict(),
            (
                "as designed: the format was never given in this session"
                if name == "unbriefed_control"
                else f"failed: {', '.join(card.failures)}"
            ),
        )

    got_rows = [
        (
            [*r[:3], _normalize_flag(r[3], accept_strings=accept_flag_strings)]
            if len(r) >= 4
            else r
        )
        for r in parsed["rows"]
    ]

    def amounts_equal(got: Any, wanted: str) -> bool:
        if got == wanted:
            return True
        if amount_eps is not None:
            try:
                return abs(float(got) - float(wanted)) <= amount_eps
            except (TypeError, ValueError):
                return False
        return False

    card.check(
        "title_exact",
        _norm(parsed["title"]) == _norm(expected_title(week)),
        got_title=parsed["title"],
        expected_title=expected_title(week),
    )
    card.check(
        "columns_exact",
        parsed["columns"] == cols,
        got_columns=parsed["columns"],
        expected_columns=cols,
    )
    rows_exact = len(got_rows) == len(want) and all(
        len(g) == len(w)
        and g[0] == w[0]
        and g[1] == w[1]
        and amounts_equal(g[2], w[2])
        and g[3] is w[3]
        for g, w in zip(got_rows, want)
    )
    card.check("rows_exact", rows_exact, got_rows=got_rows, expected_rows=want)

    # When the table is aligned, name the two judgments the traps aim at, so
    # a week-4 flag miss and a week-5 silent mis-conversion are legible in
    # the scorecard rather than buried inside rows_exact.
    aligned = (
        parsed["columns"] == cols
        and len(got_rows) == len(want)
        and all(isinstance(r, list) and len(r) == len(cols) for r in got_rows)
    )
    if aligned:
        card.check(
            "flags_exact",
            [r[3] for r in got_rows] == [w[3] for w in want],
            got_flags=[r[3] for r in got_rows],
            expected_flags=[w[3] for w in want],
        )
        card.check(
            "amounts_exact",
            all(amounts_equal(r[2], w[2]) for r, w in zip(got_rows, want)),
            got_amounts=[r[2] for r in got_rows],
            expected_amounts=[w[2] for w in want],
        )

    if name == "unbriefed_control":
        # Expected to resolve UNSUPPORTED for everybody: the format is not
        # discoverable from the documents. An arm that passes has told you
        # its later weeks were inference, not retention.
        if card.passed:
            return ScenarioResult(
                name,
                Outcome.PASS,
                card.as_dict(),
                "guessed the exact format cold — the later weeks cannot be "
                "read as retention for this arm",
            )
        return ScenarioResult(
            name,
            Outcome.UNSUPPORTED,
            card.as_dict(),
            "as designed: the format was never given in this session",
        )

    if card.passed and restated:
        # The intern economics: asking works, and costs. A restated label
        # means Daniel re-supplied something the brief or the feedback
        # already contained — on whichever channel the arm asked.
        return ScenarioResult(
            name,
            Outcome.DEGRADED,
            card.as_dict(),
            f"correct, but Daniel re-supplied the spec {len(restated)}x — "
            "the answer was already given; the round trip is the price of "
            "not keeping it",
        )

    outcome = Outcome.PASS if card.passed else Outcome.FAIL
    return ScenarioResult(
        name,
        outcome,
        card.as_dict(),
        "" if card.passed else f"failed: {', '.join(card.failures)}",
    )


def selftest_extra() -> list[str]:
    """Document-scale selftest: corpus guarantees plus the tolerance sweep.

    The sweep runs the two scripted artifacts (ideal and naive) through
    the scorer under every tolerance variant the policy declares, and
    demands the verdicts hold still: the fixture must measure the work,
    never its own thresholds.
    """
    import tempfile

    from colleague.tracks.refinement import fixture as fixture_module

    failures = list(fixture_module.selftest_corpus())

    seed = fixture_module.DEFAULT_SEED
    week = 5  # the conversion week: amounts and flags both live here
    fx = fixture_module.build(seed=seed, port=0)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            fx.state["artifact_dir"] = tmp
            for mode in ("ideal", "naive"):
                memory = {"spec": "columns"}
                out = mock_plan(
                    scenario=f"week_{week}_offcycle",
                    mode=mode,
                    fixture=fx,
                    memory=memory,
                    workdir=Path(tmp) / mode,
                )
                fx.recorder.record(
                    "deliver",
                    {
                        "filename": Path(out["deliverable"]).name,
                        "via": "selftest",
                        "stored_path": out["deliverable"],
                    },
                )
                verdicts = set()
                for accept_flags in (True, False):
                    for eps in (None, 0.0, 0.004):
                        result = score(
                            f"week_{week}_offcycle",
                            fx,
                            record={},
                            accept_flag_strings=accept_flags,
                            amount_eps=eps,
                        )
                        verdicts.add(result.outcome)
                expected = Outcome.PASS if mode == "ideal" else Outcome.FAIL
                if verdicts != {expected}:
                    failures.append(
                        f"refinement tolerance sweep: {mode} verdicts moved "
                        f"across the declared tolerance range: "
                        f"{sorted(v.value for v in verdicts)}",
                    )
                fx.reset_observations()
    finally:
        fx.stop()

    return failures
