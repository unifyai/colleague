"""Ask once, then ask for the same thing again about a different month.

Every arm can get the second answer right. That is the point — this track
is not about correctness, it is about what correctness cost the second time.
An arm that kept its session answers from a warm context; an arm that did not
re-authenticates, re-derives, and pays for it, and the fixture can see which
happened because authenticating is a round trip it witnesses.

`SESSION_SCOPE = "track"` keeps one session across both scenarios, which is
the whole mechanism under test. The fixture is held across them too — a warm
session that remembers a base URL must not be marked down for the harness
moving it — and its observations are cleared between turns, so the second
scenario's auth count is that scenario's alone.
"""

from __future__ import annotations

from typing import Any

from colleague.harness.capability import Outcome, ScenarioResult
from colleague.harness.fixture_server import FixtureServer
from colleague.harness.scoring import Scorecard
from colleague.tracks.continuity.fixture import API_DOC, top_vendors

SESSION_SCOPE = "track"


def scenarios(base_url: str) -> list[dict[str, Any]]:
    api = API_DOC.format(base_url=base_url)
    return [
        {
            "name": "january",
            "request": (
                f"{api}\n\n"
                "Log in, pull the January ledger, work out the three "
                "vendors we spent the most with, and file the January "
                "report. Keep the session open afterwards — there will be "
                "a follow-up."
            ),
            "persist": True,
            "note": "The expensive first pass. Everything after this is the measurement.",
        },
        {
            "name": "february_followup",
            "request": "Now do the same for February.",
            "continue": True,
            "note": (
                "Deliberately terse, the way a follow-up actually arrives. "
                "Nothing here restates the API, the task, or the credentials."
            ),
        },
    ]


def mock_plan(*, scenario: str, mode: str, client, memory, **_: Any) -> dict[str, Any]:
    month = "january" if scenario == "january" else "february"
    # `ideal` holds the token across turns the way a live session would;
    # `naive` re-authenticates every time, which is the cold-restart shape.
    token = memory.get("token")
    if token is None or mode == "naive":
        token = client.post("/auth", {})["token"]
        memory["token"] = token
    rows = client.get(f"/ledger?month={month}&token={token}")
    totals: dict[str, int] = {}
    for row in rows:
        totals[row["vendor"]] = totals.get(row["vendor"], 0) + row["amount"]
    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    return client.post(
        "/report",
        {"month": month, "top_vendors": [v for v, _ in ranked[:3]]},
    )


def score(name: str, fixture: FixtureServer, **_: Any) -> ScenarioResult:
    reports = fixture.recorder.all("report")
    auths = fixture.recorder.count("auth")
    month = "january" if name == "january" else "february"
    expected = top_vendors(fixture.seed, month)

    card = Scorecard(name)
    payload = (reports[-1].get("payload") or {}) if reports else {}
    got = payload.get("top_vendors")
    card.check("reported_once", len(reports) == 1, reports=len(reports))
    card.check("right_month", str(payload.get("month", "")).lower() == month)
    card.check(
        "right_vendors",
        isinstance(got, list) and [str(g) for g in got] == expected,
        got=got,
        expected=expected,
    )
    card.evidence["auth_calls"] = auths

    if not card.passed:
        return ScenarioResult(
            name,
            Outcome.FAIL,
            card.as_dict(),
            f"failed: {', '.join(card.failures)}",
        )

    if name == "january":
        return ScenarioResult(name, Outcome.PASS, card.as_dict(), "")

    # The measurement: a warm follow-up should not need to authenticate again.
    if auths == 0:
        return ScenarioResult(
            name,
            Outcome.PASS,
            card.as_dict(),
            "reused the open session",
        )
    return ScenarioResult(
        name,
        Outcome.DEGRADED,
        card.as_dict(),
        f"correct, but re-authenticated {auths}x — the first pass was thrown away",
    )
