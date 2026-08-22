"""Walk through it once, then ask for it again — and again, for six weeks.

Week 31 is taught: the walkthrough states both exceptions, and any arm that
follows instructions will get it right. Week 32 is the first measurement,
and the request deliberately restates nothing — "run the invoice chase for
week 32" is what a follow-up actually looks like.

An arm that kept the procedure applies both exceptions again. An arm that
did not will do the obvious thing: chase everyone over thirty days, directly,
including the vendor who is supposed to be handled through their account
manager. Both exceptions are absent from the API, so there is no way to
rediscover them.

Week 33 is `interruption` × `teaching`: a third rule arrives as a correction
after the first reminder has gone — don't chase anyone on a payment plan —
and week 34 measures it unprompted. Before week 35 one of the original rules
is amended in one sentence: the vendor's account manager has changed. The
threshold is not mentioned and must not move, which is what makes weeks 35
and 36 a regression test and not just a longer replay: the seed puts
invoices at 33 and 38 days in week 35 and at 34 and 35 in week 36, so an arm
that takes the amendment on board and drifts back to the obvious threshold
is caught in the same scorecard. Week 36 is unattended with all three rules
in force.

The walkthrough also asks for one thing that is scored on presence, not on
prose: show the first list before anything goes out, then never again. Week
31 must contain a preview raised through the arm's own channel before the
first send; the unattended weeks must raise nothing at all. Cost per week is
reported from the ledger and never scored.

The control is the honest one. It teaches nothing and asks for week 32 cold,
which establishes what the API alone gets you. If an arm scores the same on
`untaught_control` as on `week_32_replay`, its second-week success was not
retention.
"""

from __future__ import annotations

from typing import Any

from colleague.harness.capability import Outcome, ScenarioResult
from colleague.harness.conversation import Transcript
from colleague.harness.fixture_server import FixtureServer
from colleague.harness.interlocutor import ScriptedTurn
from colleague.harness.persona import asks as persona_asks
from colleague.harness.persona import attended
from colleague.harness.scoring import Scorecard, only_recipients
from colleague.tracks.teaching.fixture import (
    ACCOUNT_MANAGER,
    AMENDED_ACCOUNT_MANAGER,
    AMENDMENT_WEEK,
    API_DOC,
    CORRECTION_WEEK,
    DANIEL,
    LAST_WEEK,
    OVERDUE_THRESHOLD_DAYS,
    TAUGHT_WEEK,
    VIA_ACCOUNT_MANAGER,
    account_manager_for,
    expected_reminders,
    payment_plan_contacts,
)

SESSION_SCOPE = "track"

#: The scenario's full cast, for arms that maintain a real contact
#: store: the runner seeds these so the environment contains the
#: people the roster text describes.
PARTICIPANTS = [DANIEL]

WALKTHROUGH = f"""\
Let me show you how I do the weekly invoice chase, then you can take it over.

Pull the invoices for the week. Anything more than {OVERDUE_THRESHOLD_DAYS} \
days overdue gets a reminder — not thirty, we relaxed it last year because \
half our vendors bill on net-45 and it was generating noise.

One exception: {VIA_ACCOUNT_MANAGER}. Never chase them directly. Their AP \
inbox is a black hole and their account manager, {ACCOUNT_MANAGER}, actually \
answers. Anything of theirs goes to her instead.

Everything else goes to the contact on the invoice. One reminder per invoice.

The first time, show me who you are about to remind before you send \
anything and wait for my OK. After that just run it — I will not want to be \
asked again.\
"""

CORRECTION = (
    "Oh — one more thing, from now on: anyone on a payment plan (the "
    "invoice list shows who's on one) doesn't get chased at all. Skip them."
)

AMENDMENT = (
    f"Amanda has moved on — {VIA_ACCOUNT_MANAGER}'s account manager is now "
    f"Tomas Lindqvist, {AMENDED_ACCOUNT_MANAGER}; their reminders go to him "
    "from now on."
)

_NAMES = {
    TAUGHT_WEEK: "week_31_taught",
    TAUGHT_WEEK + 1: "week_32_replay",
    CORRECTION_WEEK: "week_33_corrected",
    CORRECTION_WEEK + 1: "week_34_replay_after_correction",
}


def _week_name(week: int) -> str:
    return _NAMES.get(week, f"week_{week}")


def _week_of(name: str) -> int:
    if name == "untaught_control":
        return TAUGHT_WEEK + 1
    return int(name.split("_")[1])


def scenarios(base_url: str) -> list[dict[str, Any]]:
    api = API_DOC.format(base_url=base_url)
    roster = Transcript(participants=[DANIEL]).roster()
    out: list[dict[str, Any]] = [
        {
            "name": "week_31_taught",
            "context": roster,
            "request": f"{api}\n\n{WALKTHROUGH}\n\nGo ahead and run it for week 31.",
            "persist": True,
            "sender": "daniel",
            "clarify_persona": "daniel",
            "note": (
                "Taught. Any arm following instructions should get this right, "
                "and should show the list once before sending."
            ),
        },
        {
            "name": "week_32_replay",
            "request": "Run the invoice chase for week 32.",
            "continue": True,
            "sender": "daniel",
            "note": (
                "The measurement. Nothing is restated — not the threshold, "
                "not the exception, not the API."
            ),
        },
        {
            "name": "week_33_corrected",
            "request": "Run the invoice chase for week 33.",
            "continue": True,
            "sender": "daniel",
            "note": (
                "A third rule arrives as a correction after the first reminder "
                "has gone: don't chase anyone on a payment plan. Progress kept, "
                "remainder corrected."
            ),
        },
        {
            "name": "week_34_replay_after_correction",
            "request": "Run the invoice chase for week 34.",
            "continue": True,
            "sender": "daniel",
            "note": (
                "The measurement for the correction: nothing restated. A "
                "colleague who was corrected last week does not need telling "
                "again."
            ),
        },
    ]
    for week in range(CORRECTION_WEEK + 2, LAST_WEEK + 1):
        request = f"Run the invoice chase for week {week}."
        note = "Unattended. Nothing restated, nothing should be asked."
        if week == AMENDMENT_WEEK:
            request = f"{AMENDMENT} Run the invoice chase for week {week}."
            note = (
                "One rule amended in one sentence; the threshold and the "
                "payment-plan rule are not mentioned and must not move."
            )
        out.append(
            {
                "name": _week_name(week),
                "request": request,
                "continue": True,
                "sender": "daniel",
                "note": note,
            },
        )
    out.append(
        {
            "name": "untaught_control",
            "request": (
                f"{api}\n\nRun the weekly invoice chase for week 32 — send "
                "reminders for the overdue invoices."
            ),
            "fresh_session": True,
            "note": (
                "The control: no walkthrough, ever, in a session that never "
                "saw one. It ran third in the shared session and passed by "
                "remembering, which made the taught result unreadable — a "
                "control contaminated by the thing it controls for is worse "
                "than no control."
            ),
        },
    )
    return out


def turns(name: str) -> list[ScriptedTurn]:
    if name != "week_33_corrected":
        return []
    return [
        ScriptedTurn(
            label="correction",
            sender="daniel",
            text=CORRECTION,
            waypoint="remind",
            nth=1,
            timeout=240,
        ),
    ]


def mock_plan(
    *,
    scenario: str,
    mode: str,
    client,
    memory,
    corrections,
    ask_user,
    **_: Any,
) -> dict[str, Any]:
    week = _week_of(scenario)
    if scenario == "week_31_taught":
        memory["threshold"] = OVERDUE_THRESHOLD_DAYS
        memory["via_am"] = VIA_ACCOUNT_MANAGER
        memory["am"] = ACCOUNT_MANAGER
        memory["preview_shown"] = False
    if week == AMENDMENT_WEEK and mode == "ideal":
        memory["am"] = AMENDED_ACCOUNT_MANAGER

    taught = scenario != "untaught_control" and mode == "ideal"
    threshold = memory.get("threshold", 30) if taught else 30
    via_am = memory.get("via_am") if taught else None
    # A correction heard last week stays learned — for the arm that keeps it.
    skip_pp = bool(memory.get("skip_payment_plan")) if mode == "ideal" else False

    rows = client.get(f"/invoices?week={week}")
    planned = []
    for row in rows:
        if row["days_overdue"] <= threshold:
            continue
        to = memory["am"] if (via_am and row["vendor"] == via_am) else row["contact"]
        planned.append((row, to))

    # The preview: once, before the first send, then never. The naive plan
    # asks every week — the harmless-looking habit the walkthrough ruled out.
    if scenario != "untaught_control" and (
        (mode == "ideal" and not memory.get("preview_shown")) or mode == "naive"
    ):
        ask_user(
            "About to send reminders to: "
            + ", ".join(sorted({to for _, to in planned}))
            + ". OK to send?",
            "daniel",
        )
        memory["preview_shown"] = True

    sent = 0
    for row, to in planned:
        # Mid-run: has the correction arrived? Only the ideal arm listens.
        if mode == "ideal" and any(
            "payment plan" in c["text"].lower() for c in corrections
        ):
            memory["skip_payment_plan"] = True
            skip_pp = True
        if skip_pp and row["payment_plan"]:
            continue
        client.post("/remind", {"to": to, "invoice_id": row["id"]})
        sent += 1
    return {"sent": sent}


def score(
    name: str,
    fixture: FixtureServer,
    *,
    record: dict[str, Any] | None = None,
    **_: Any,
) -> ScenarioResult:
    week = _week_of(name)
    reminders = fixture.recorder.all("remind")
    got = only_recipients(reminders)
    clarifications = (record or {}).get("clarifications") or []
    card = Scorecard(name)

    if name == "week_33_corrected":
        journal = (record or {}).get("interlocutor", []) or []
        entry = next((e for e in journal if e.get("label") == "correction"), None)
        mode = str((entry or {}).get("mode") or "")
        if mode == "unsupported":
            return ScenarioResult(
                name,
                Outcome.UNSUPPORTED,
                {"reminders": len(reminders)},
                "no channel exists to reach work that has already started",
            )
        if not entry or not entry.get("delivered"):
            return ScenarioResult(
                name,
                Outcome.ERROR,
                {
                    "reminders": len(reminders),
                    "delivery_mode": mode or "no journal entry",
                },
                "the correction was never offered — nothing about learning was measured",
            )
        correction_seq = int(entry.get("recorder_seq") or 0)
        pp = payment_plan_contacts(fixture.seed, week)
        after = [r for r in reminders if r["seq"] > correction_seq]
        pp_after = sorted(only_recipients(after) & pp)
        needed = expected_reminders(fixture.seed, week, skip_payment_plan=True)
        card.check(
            "no_payment_plan_reminder_after_correction",
            not pp_after,
            sent_after=pp_after,
        )
        card.check(
            "everyone_else_still_reached",
            needed <= got,
            missing=sorted(needed - got),
        )
        card.check(
            "nobody_reminded_twice",
            len(
                {
                    str((r.get("payload") or {}).get("to", "")).lower()
                    for r in reminders
                },
            )
            == len(reminders),
        )
        card.check(
            "used_the_account_manager_route",
            ACCOUNT_MANAGER in got or ACCOUNT_MANAGER not in needed,
        )
        card.evidence["correction_seq"] = correction_seq
        card.evidence["reminder_seqs"] = [r["seq"] for r in reminders]
        outcome = Outcome.PASS if card.passed else Outcome.FAIL
        return ScenarioResult(
            name,
            outcome,
            card.as_dict(),
            "" if card.passed else f"failed: {', '.join(card.failures)}",
        )

    expected = expected_reminders(fixture.seed, week)
    card.check(
        "exact_recipients",
        got == expected,
        got=sorted(got),
        expected=sorted(expected),
    )
    card.check(
        "used_the_account_manager_route",
        account_manager_for(week) in got or account_manager_for(week) not in expected,
    )
    card.evidence["reminders"] = len(reminders)
    card.evidence["clarifications"] = len(clarifications)

    if name == "week_31_taught":
        # The preview is scored on presence: a question raised through the
        # arm's own channel — the blocking hook, or an ordinary message
        # Daniel answered — that names someone it is about to remind. The
        # blocking form keeps "before the first send" by construction; the
        # message form is the same act on the product's own channel.
        questions = [str(c.get("question") or "") for c in clarifications] + [
            str(a.get("question") or "") for a in persona_asks(record)
        ]
        previewed = any(
            any(addr in question for addr in expected) for question in questions
        )
        card.check("previewed_before_first_send", previewed)
    elif name != "untaught_control":
        # Unattended means the arm needed nobody: no blocking question, no
        # message a person had to answer with content. A filed status update
        # Daniel read silently keeps the week unattended — reporting to your
        # boss is not needing your boss.
        card.check("unattended", not attended(record))
    if week >= AMENDMENT_WEEK and name != "untaught_control":
        card.check(
            "amendment_applied",
            AMENDED_ACCOUNT_MANAGER in got and ACCOUNT_MANAGER not in got,
        )
        card.check(
            "untouched_rules_kept",
            all(addr in expected for addr in got - {AMENDED_ACCOUNT_MANAGER}),
        )

    if name == "untaught_control":
        # This one is expected to fail for everybody. It is a calibration
        # point, not a test of the arm, so a miss is reported as UNSUPPORTED
        # of the information rather than as a failure of the harness.
        if card.passed:
            return ScenarioResult(
                name,
                Outcome.PASS,
                card.as_dict(),
                "guessed both exceptions from the API alone — week 32 cannot "
                "be read as retention for this arm",
            )
        return ScenarioResult(
            name,
            Outcome.UNSUPPORTED,
            card.as_dict(),
            "as designed: the exceptions are not discoverable without being told",
        )

    outcome = Outcome.PASS if card.passed else Outcome.FAIL
    return ScenarioResult(
        name,
        outcome,
        card.as_dict(),
        "" if card.passed else f"failed: {', '.join(card.failures)}",
    )
