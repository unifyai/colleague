"""Brief once, refine once, then ask for it again — and watch what froze.

The track joins two halves the suite already had separately: drip-fed
teaching (`teaching`) and exact structural regression on a recurring
artifact (`standing/change_without_regression`). One recurring deliverable
— a weekly client spend report — gets its spec the way specs actually
arrive: a prose brief, then format feedback on the first draft, then
nothing restated for four weeks, then a one-sentence amendment.

What the later weeks measure is calibration of the structure/judgment
boundary, not just retention. Week 4's personal-spend items are paraphrases
sharing no token with the earlier weeks' samples, and a business item
carries one of the old tokens — an arm that distilled the flag rule into a
keyword ladder fails in both directions, an arm that kept it a judgment
does not. Week 5 is the first week the brief's dormant foreign-currency
rule fires — an arm that froze its procedure from the observed weeks
(every row EUR so far) silently mis-converts, though the rule was stated
on day one. Week 6 renames one column and requires every other rule to
hold in the same scorecard.

Asking again is priced, not forbidden: a correct week that needed a
clarification resolves DEGRADED — the answer was already given, and the
round trip is the cost the arm chose to pay (`inheritance` set the
precedent). Cost per week is reported from the ledger and never scored;
across the six weeks that ledger is the drip-fed amortisation curve this
track exists to produce.

The control is the honest one: no brief, ever, in a session that never saw
one. The exact format is not discoverable from the API, so it resolves
UNSUPPORTED for everybody, and an arm that passes it has told you its
later weeks were inference, not retention.
"""

from __future__ import annotations

from typing import Any

from colleague.harness.capability import Outcome, ScenarioResult
from colleague.harness.conversation import Transcript
from colleague.harness.fixture_server import FixtureServer
from colleague.harness.scoring import Scorecard
from colleague.tracks.refinement.fixture import (
    API_DOC,
    DANIEL,
    expected_columns,
    expected_rows,
    expected_title,
    personal_ids,
)
from colleague.tracks.refinement.human import surface_for

SESSION_SCOPE = "track"

#: The scenario's full cast, for arms that maintain a real contact store.
PARTICIPANTS = [DANIEL]

BRIEF = """\
Let me hand you the weekly client spend report.

Every week, pull that week's expenses and file the report through the API
— one row per expense, in the order the API returns them. Amounts arrive
in cents; the report shows euros. Everything is EUR at the moment, but if
a foreign-currency expense ever turns up, convert it at the rate from the
rates endpoint, to the nearest cent. The report is always in euros.

The one thing I really care about: anything that looks like personal
spending on the company card gets flagged — finance wants it marked, not
dropped. Keep the row, mark it flagged. Use your judgment on the
descriptions; they're free text and people word these however they like.

File week 1 and I'll take a look.\
"""

COLUMNS_FEEDBACK = """\
Looked at week 1 — good start. Two things, and this is how I want it
every week from now on.

Title it exactly "Northwind Client Spend - Week 2" — same pattern every
week, with the week number.

Use exactly these columns, in this order: vendor, category, amount_eur,
flagged. category comes straight off the expense row. amount_eur is a
string in euros with exactly two decimals — "812.40", never 812.4.
flagged is a JSON boolean, your personal-spend call. One row per expense,
API order, each row a list in column order.

File week 2.\
"""

AMENDMENT = (
    'One change from finance: the amount column is called "amount" now, '
    'not "amount_eur" — still euros, same format. Everything else stays '
    "exactly as it is. File week 6."
)

CONTROL_REQUEST = (
    "File the weekly client spend report for week 3 "
    "— pull the expenses and file it through the API."
)


def _file_week(week: int) -> str:
    return f"File the spend report for week {week}."


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
    # over the same durable world (same stores, same on-disk session rows),
    # so what an arm carries between weeks is exactly what it durably
    # persisted, never a trajectory that happened to stay warm in RAM.
    # Without this, one open in-process session across six "weeks" let
    # in-context memory stand in for the retention the track measures.
    api = API_DOC.format(base_url=base_url)
    roster = Transcript(participants=[DANIEL]).roster()
    return [
        {
            "name": "week_1_briefed",
            "participant_title": "Week 1",
            "participant_preview": (
                "Take on a weekly client spend report and file its first week."
            ),
            "context": roster,
            "request": f"{api}\n\n{BRIEF}",
            "surface": surface_for(BRIEF),
            "persist": True,
            "sender": "daniel",
            "clarify_persona": "daniel",
            "note": (
                "The brief, including one dormant rule nothing exercises "
                "for four weeks. No format is fixed yet, so only filing is "
                "scored; the measurement is every later week."
            ),
        },
        {
            "name": "week_2_columns",
            "participant_title": "Week 2",
            "participant_preview": (
                "File the next week of the client spend report."
            ),
            "request": COLUMNS_FEEDBACK,
            "surface": surface_for(COLUMNS_FEEDBACK),
            "continue": True,
            "sleep": True,
            "sender": "daniel",
            "note": (
                "The format feedback on the first draft: exact title, "
                "exact columns in order, string amounts. In force from "
                "this round on."
            ),
        },
        {
            "name": "week_3_replay",
            "participant_title": "Week 3",
            "participant_preview": (
                "File another week of the client spend report."
            ),
            "request": _file_week(3),
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
            "participant_preview": (
                "File another week of the client spend report."
            ),
            "request": _file_week(4),
            "surface": surface_for(_file_week(4)),
            "continue": True,
            "sleep": True,
            "sender": "daniel",
            "note": (
                "The personal items stop sharing tokens with the earlier "
                "weeks' samples and a business item picks one up. A keyword "
                "ladder distilled from the samples fails both ways."
            ),
        },
        {
            "name": "week_5_offcycle",
            "participant_title": "Week 5",
            "participant_preview": (
                "File another week of the client spend report."
            ),
            "request": _file_week(5),
            "surface": surface_for(_file_week(5)),
            "continue": True,
            "sleep": True,
            "sender": "daniel",
            "note": (
                "The dormant rule fires: the first foreign-currency rows. "
                "A procedure frozen from the observed weeks silently "
                "mis-converts; the brief's rule was always sufficient."
            ),
        },
        {
            "name": "week_6_amendment",
            "participant_title": "Week 6",
            "participant_preview": (
                "File another week of the client spend report."
            ),
            "request": AMENDMENT,
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
            "request": f"{api}\n\n{CONTROL_REQUEST}",
            "surface": surface_for(CONTROL_REQUEST),
            "fresh_session": True,
            "note": (
                "The control: no brief, ever, in a session that never saw "
                "one. Establishes what the API alone yields."
            ),
        },
    ]


def mock_plan(
    *,
    scenario: str,
    mode: str,
    client,
    memory,
    **_: Any,
) -> dict[str, Any]:
    week = _week_of(scenario)
    ideal = mode == "ideal"
    if ideal:
        if scenario == "week_2_columns":
            memory["spec"] = "columns"
        if scenario == "week_6_amendment":
            memory["renamed"] = True

    rows = client.get(f"/expenses?week={week}")

    if ideal and scenario != "unbriefed_control" and memory.get("spec") == "columns":
        # The taught arm: exact format from week 2's feedback, the dormant
        # conversion rule from the brief, and the flag call made from the
        # fixture's own labels — the scripted stand-in for live judgment,
        # which is exactly what a keyword ladder is not.
        rates = client.get("/rates")
        flagged = personal_ids(week)
        amount_col = "amount" if memory.get("renamed") else "amount_eur"
        out_rows = []
        for row in rows:
            cents = row["amount_cents"]
            if row["currency"] != "EUR":
                cents = round(cents * rates[row["currency"]])
            out_rows.append(
                [
                    row["vendor"],
                    row["category"],
                    f"{cents // 100}.{cents % 100:02d}",
                    row["id"] in flagged,
                ],
            )
        client.post(
            "/report",
            {
                "week": week,
                "title": f"Northwind Client Spend - Week {week}",
                "columns": ["vendor", "category", amount_col, "flagged"],
                "rows": out_rows,
            },
        )
        return {"filed": week, "rows": len(out_rows)}

    # Week 1 (no format fixed yet) and every naive week: the obvious report —
    # default columns, cents over a hundred, and the flag call downgraded to
    # the keyword ladder the descriptions eventually defeat.
    client.post(
        "/report",
        {
            "week": week,
            "title": f"Week {week} spend report",
            "columns": ["vendor", "description", "amount", "flagged"],
            "rows": [
                [
                    r["vendor"],
                    r["description"],
                    r["amount_cents"] / 100,
                    any(
                        token in r["description"].lower()
                        for token in ("personal", "gift")
                    ),
                ]
                for r in rows
            ],
        },
    )
    return {"filed": week, "improvised": True}


def score(
    name: str,
    fixture: FixtureServer,
    *,
    record: dict[str, Any] | None = None,
    **_: Any,
) -> ScenarioResult:
    week = _week_of(name)
    filings = fixture.recorder.all("report")
    mine = [f for f in filings if (f.get("payload") or {}).get("week") == week]
    clarifications = (record or {}).get("clarifications") or []
    card = Scorecard(name)
    card.evidence["filings"] = len(filings)
    card.evidence["clarifications"] = len(clarifications)

    if name == "week_1_briefed":
        # No format has been fixed yet, so the draft's shape is free; the
        # feedback that fixes it is the next scenario. Scored on filing only.
        card.check("report_filed", bool(mine))
        outcome = Outcome.PASS if card.passed else Outcome.FAIL
        return ScenarioResult(
            name,
            outcome,
            card.as_dict(),
            "" if card.passed else f"failed: {', '.join(card.failures)}",
        )

    cols = expected_columns(week)
    want = expected_rows(fixture.seed, week)
    payload = (mine[-1].get("payload") or {}) if mine else {}
    got_rows = payload.get("rows") or []

    card.check("filed_once", len(mine) == 1)
    card.check(
        "title_exact",
        _norm(payload.get("title")) == _norm(expected_title(week)),
        got_title=payload.get("title"),
        expected_title=expected_title(week),
    )
    card.check(
        "columns_exact",
        payload.get("columns") == cols,
        got_columns=payload.get("columns"),
        expected_columns=cols,
    )
    card.check("rows_exact", got_rows == want, got_rows=got_rows, expected_rows=want)

    # When the table is aligned, name the two judgments the traps aim at, so
    # a week-4 keyword miss and a week-5 silent mis-conversion are legible in
    # the scorecard rather than buried inside rows_exact.
    aligned = (
        payload.get("columns") == cols
        and isinstance(got_rows, list)
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
            [r[2] for r in got_rows] == [w[2] for w in want],
            got_amounts=[r[2] for r in got_rows],
            expected_amounts=[w[2] for w in want],
        )

    if name == "unbriefed_control":
        # Expected to resolve UNSUPPORTED for everybody: the format is not
        # discoverable from the API. An arm that passes has told you its
        # later weeks were inference, not retention.
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

    if card.passed and clarifications:
        # The intern economics: asking works, and costs. Every answer the
        # persona gives is one the brief or the feedback already contained.
        return ScenarioResult(
            name,
            Outcome.DEGRADED,
            card.as_dict(),
            f"correct, but asked {len(clarifications)}x — the answer was "
            "already given; the round trip is the price of not keeping it",
        )

    outcome = Outcome.PASS if card.passed else Outcome.FAIL
    return ScenarioResult(
        name,
        outcome,
        card.as_dict(),
        "" if card.passed else f"failed: {', '.join(card.failures)}",
    )
