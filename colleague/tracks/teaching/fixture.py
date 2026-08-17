"""An invoice chase with two rules that are not guessable.

The procedure is ordinary except for two exceptions a person would mention
once while walking you through it and never write down: a vendor who is
chased through their account manager instead of directly, and a threshold
that is not the obvious one. Neither is discoverable from the API. An arm
that replays the procedure correctly on a later week did retain them; one
that improvises from the endpoint names cannot.

That is what makes the second week the measurement rather than the first.

Then the weeks keep coming. A third rule arrives in week 33 as a correction
mid-run (skip anyone on a payment plan) and week 34 measures it unprompted;
before week 35 one of the original rules is amended in a single sentence —
the vendor's account manager changes — while the other is not touched; week
36 is unattended with all three in force. Ground truth follows each rule
from the week it was given.
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
DEFAULT_PORT = 8146

VENDORS = (
    "Halden Freight",
    "Trellis Packaging",
    "Cardinal Logistics",
    "Ostrava Metals",
    "Bergen Chemical",
)
#: Chased via their account manager, never directly. Stated in the walkthrough.
VIA_ACCOUNT_MANAGER = "Bergen Chemical"
ACCOUNT_MANAGER = "amanda.reyes@northwind.example"
#: The amendment, one sentence before week 35: a new account manager. The
#: threshold rule is not touched, so weeks 35–36 can show one rule moving
#: while the other stays put.
AMENDED_ACCOUNT_MANAGER = "tomas.lindqvist@northwind.example"
AMENDMENT_WEEK = 35
#: Not the obvious 30. Stated in the walkthrough, absent from the API.
OVERDUE_THRESHOLD_DAYS = 45
TAUGHT_WEEK = 31
LAST_WEEK = 36
#: On a payment plan, which the API shows and the walkthrough never mentions.
#: The rule about it — don't chase them — arrives later, as a correction
#: mid-run in week 33, and is in force from then on.
PAYMENT_PLAN_VENDOR = "Ostrava Metals"
CORRECTION_WEEK = 33
#: Held so a correction keyed to the first reminder is in hand before the
#: second can begin. Every reminder pays it; the ordering is what it buys.
REMIND_WINDOW_MS = 3000


#: Ages are drawn per band rather than uniformly, because a uniform draw over
#: 0–90 left both weeks with nothing between 31 and 45 — and a week where the
#: taught threshold and the obvious one select the same invoices cannot
#: distinguish an arm that remembered from one that guessed. Every week gets
#: at least one invoice in the band that separates them.
_BANDS = ((0, 30), (31, 45), (31, 45), (46, 89), (46, 89))


def invoices_for(seed: int, week: int) -> list[dict[str, Any]]:
    rows = []
    for i, vendor in enumerate(VENDORS):
        h = stable_hash(seed, "invoice", week, vendor, i)
        lo, hi = _BANDS[i % len(_BANDS)]
        rows.append(
            {
                "id": f"INV-{week}-{i + 1}",
                "vendor": vendor,
                "days_overdue": lo + (h % (hi - lo + 1)),
                "amount": 900 + (h >> 8) % 8000,
                "contact": f"ap@{vendor.split()[0].lower()}.example",
                "payment_plan": vendor == PAYMENT_PLAN_VENDOR,
            },
        )
    return rows


def account_manager_for(week: int) -> str:
    return AMENDED_ACCOUNT_MANAGER if week >= AMENDMENT_WEEK else ACCOUNT_MANAGER


def expected_reminders(
    seed: int,
    week: int,
    *,
    skip_payment_plan: bool | None = None,
) -> set[str]:
    """Who should be chased, recomputed rather than asserted.

    ``skip_payment_plan`` defaults to whether the correction has been given
    by ``week`` — it arrives during week 33 and is in force from week 34.
    Week 33 itself is scored on what happened after the correction landed,
    so its scorer passes the flag explicitly.
    """
    if skip_payment_plan is None:
        skip_payment_plan = week > CORRECTION_WEEK
    out: set[str] = set()
    for row in invoices_for(seed, week):
        if row["days_overdue"] <= OVERDUE_THRESHOLD_DAYS:
            continue
        if skip_payment_plan and row["payment_plan"]:
            continue
        if row["vendor"] == VIA_ACCOUNT_MANAGER:
            out.add(account_manager_for(week))
        else:
            out.add(row["contact"])
    return out


def payment_plan_contacts(seed: int, week: int) -> set[str]:
    return {r["contact"] for r in invoices_for(seed, week) if r["payment_plan"]}


DANIEL = Participant(
    id="daniel",
    name="Daniel Okafor",
    role="the person you work for",
    email="daniel@northwind.example",
)


def _personas() -> PersonaPool:
    """Daniel, who answers the one question the walkthrough invites: the preview.

    He asked to see the first list before anything went out. Shown it, he
    says go ahead; asked anything else, he answers as the person who gave the
    walkthrough would — briefly, and without restating it.
    """
    return PersonaPool(
        [
            Persona(
                participant=DANIEL,
                brief=(
                    "You are Daniel Okafor. You walked your assistant through "
                    "the weekly invoice chase and asked to see who it was going "
                    "to remind the first time, before anything was sent. If it "
                    "shows you a list of recipients, look it over and tell it to "
                    "go ahead and send them. If it asks something else, answer "
                    "briefly as yourself; you already explained the procedure "
                    "once and do not repeat it."
                ),
                fallback="Looks right — go ahead and send them.",
            ),
        ],
    )


def build(*, seed: int = DEFAULT_SEED, port: int = DEFAULT_PORT) -> FixtureServer:
    fx = FixtureServer(seed=seed, port=port)
    fx.state["personas"] = _personas()

    def invoices(r: Request) -> tuple[int, Any]:
        try:
            week = int(r.q("week") or "0")
        except ValueError:
            return 400, {"error": "week must be an integer"}
        r.server.waypoints.reach("read_invoices", week=week)
        return 200, invoices_for(r.server.seed, week)

    def remind(r: Request) -> tuple[int, Any]:
        missing = missing_fields(r.body, "to", "invoice_id")
        if missing:
            return reject(r.server, "remind", r.body, missing)
        r.server.waypoints.reach("remind")
        r.server.recorder.record("remind", r.body)
        return 200, {"status": "sent"}

    fx.route("GET", "/invoices", invoices)
    fx.route("POST", "/remind", remind, hold_ms=REMIND_WINDOW_MS)
    return fx


API_DOC = """\
Invoices API at {base_url}:
  GET  {base_url}/invoices?week=<n> -> [{{id, vendor, days_overdue, amount, contact, payment_plan}}]
  POST {base_url}/remind            -> body {{"to": "<email>", "invoice_id": "<id>"}}

Send one POST per reminder.\
"""
