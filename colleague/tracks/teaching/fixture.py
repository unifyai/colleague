"""An invoice chase with two rules that are not guessable.

The procedure is ordinary except for two exceptions a person would mention
once while walking you through it and never write down: a vendor who is
chased through their account manager instead of directly, and a threshold
that is not the obvious one. Neither is discoverable from the API. An arm
that replays the procedure correctly on a later week did retain them; one
that improvises from the endpoint names cannot.

That is what makes the second week the measurement rather than the first.
"""

from __future__ import annotations

from typing import Any

from colleague.harness.fixture_server import (
    FixtureServer,
    Request,
    missing_fields,
    reject,
    stable_hash,
)

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
#: Not the obvious 30. Stated in the walkthrough, absent from the API.
OVERDUE_THRESHOLD_DAYS = 45
#: On a payment plan, which the API shows and the walkthrough never mentions.
#: The rule about it — don't chase them — arrives later, as a correction
#: mid-run, and is the thing `week_34_replay_after_correction` measures.
PAYMENT_PLAN_VENDOR = "Ostrava Metals"
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


def expected_reminders(seed: int, week: int, *, skip_payment_plan: bool = False) -> set[str]:
    """Who should be chased, recomputed rather than asserted."""
    out: set[str] = set()
    for row in invoices_for(seed, week):
        if row["days_overdue"] <= OVERDUE_THRESHOLD_DAYS:
            continue
        if skip_payment_plan and row["payment_plan"]:
            continue
        if row["vendor"] == VIA_ACCOUNT_MANAGER:
            out.add(ACCOUNT_MANAGER)
        else:
            out.add(row["contact"])
    return out


def payment_plan_contacts(seed: int, week: int) -> set[str]:
    return {r["contact"] for r in invoices_for(seed, week) if r["payment_plan"]}


def build(*, seed: int = DEFAULT_SEED, port: int = DEFAULT_PORT) -> FixtureServer:
    fx = FixtureServer(seed=seed, port=port)

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
