"""Weekly overdue-invoice digest whose fifth week is not like the first four.

Each week the API serves the invoices that became overdue that week — five
of them, one per vendor, every field as described. The automation reminds
each contact and posts a digest. Week five breaks one stated invariant, in
one of four ways chosen by ``variant``:

``empty``      no invoices at all
``duplicate``  one invoice served twice, same ``id``
``currency``   one invoice in GBP where every amount is EUR
``no_email``   one invoice whose ``contact_email`` is null

Ground truth for week five is defined by the rules the utterance states in
general terms — ids are unique, amounts are EUR, every invoice has a contact,
always send the digest, flag anything that does not match — never by naming
the edge. See ``expected_week`` for exactly what a correct week five is.

Endpoints:
    GET  /health
    GET  /reports/last            -> {"last_week": highest week reported, 0 if none}
    GET  /invoices?week=W         -> the week's invoices (404 until the week is released)
    POST /remind                  -> {"to": email, "invoice_id": id}; 400 if either missing
    POST /report                  -> the digest; stored
    GET  /reports                 -> every stored digest
    POST /owner/notify            -> {"message": ...}
    GET  /owner/messages
"""

from __future__ import annotations

import threading
from typing import Any

from colleague.harness.fixture_server import (
    FixtureServer,
    Request,
    missing_fields,
    reject,
    stable_hash,
)
from colleague.tracks.standing.series.spec import install_owner_channel

DEFAULT_SEED = 20260817
DEFAULT_PORT = 8182

VARIANTS = ("empty", "duplicate", "currency", "no_email")
EDGE_WEEK = 5
N_WEEKS = 5

VENDORS = (
    "Halden Freight",
    "Trellis Packaging",
    "Cardinal Logistics",
    "Ostrava Metals",
    "Bergen Chemical",
)
#: Which of the five invoices the edge is applied to (0-based), per variant.
EDGE_ROW = {"duplicate": 1, "currency": 2, "no_email": 3}


def invoices_for(seed: int, week: int) -> list[dict[str, Any]]:
    """The week's invoices as generated — the truth, before any edge."""
    rows = []
    for i, vendor in enumerate(VENDORS):
        h = stable_hash(seed, "invoice", week, vendor, i)
        rows.append(
            {
                "id": f"INV-{week}-{i + 1}",
                "vendor": vendor,
                "amount_cents": 90_000 + (h % 800) * 100,
                "currency": "EUR",
                "days_overdue": 31 + (h >> 8) % 40,
                "contact_email": f"ap@{vendor.split()[0].lower()}.example",
            },
        )
    return rows


def served_invoices(seed: int, week: int, variant: str) -> list[dict[str, Any]]:
    """What the API shows for the week: the truth, plus the edge on week five."""
    rows = [dict(r) for r in invoices_for(seed, week)]
    if week != EDGE_WEEK:
        return rows
    if variant == "empty":
        return []
    if variant == "duplicate":
        rows.insert(EDGE_ROW[variant] + 1, dict(rows[EDGE_ROW[variant]]))
    elif variant == "currency":
        rows[EDGE_ROW[variant]]["currency"] = "GBP"
    elif variant == "no_email":
        rows[EDGE_ROW[variant]]["contact_email"] = None
    return rows


def expected_week(seed: int, week: int, variant: str) -> dict[str, Any]:
    """The digest and reminder set a correct run delivers for the week.

    Follows the utterance's general rules to their conclusion:

    - ``invoice_count`` counts distinct invoices (a duplicate row is one
      invoice);
    - ``total_amount_cents`` sums EUR amounts only, because the field is
      defined as EUR cents and a GBP figure is not one;
    - one reminder per distinct invoice with a contact, none without;
    - ``flagged_invoice_ids`` names every invoice that broke a stated
      invariant — the duplicated id, the non-EUR one, the one with no
      contact — and is empty in an ordinary week;
    - an empty week still gets its digest, with zeros.
    """
    served = served_invoices(seed, week, variant)
    seen: dict[str, dict[str, Any]] = {}
    flagged: list[str] = []
    for row in served:
        if row["id"] in seen:
            if row["id"] not in flagged:
                flagged.append(row["id"])
            continue
        seen[row["id"]] = row
        if row["currency"] != "EUR" or not row["contact_email"]:
            flagged.append(row["id"])
    reminders = {
        (row["contact_email"], row["id"])
        for row in seen.values()
        if row["contact_email"]
    }
    return {
        "report": {
            "week": week,
            "invoice_count": len(seen),
            "total_amount_cents": sum(
                r["amount_cents"] for r in seen.values() if r["currency"] == "EUR"
            ),
            "reminders_sent": len(reminders),
            "flagged_invoice_ids": sorted(flagged),
        },
        "reminders": reminders,
    }


def score_week(
    *,
    reports: list[Any],
    reminders: list[dict[str, Any]],
    expected: dict[str, Any],
) -> dict[str, Any]:
    checks: dict[str, bool] = {"one_report": len(reports) == 1}
    body = reports[0] if len(reports) == 1 and isinstance(reports[0], dict) else None
    want = expected["report"]
    if body is None:
        checks["report_is_object"] = False
    else:
        for key, value in want.items():
            got = body.get(key)
            if key == "flagged_invoice_ids":
                got = sorted(got) if isinstance(got, list) else got
            checks[key] = got == value and type(got) is type(value)
        checks["no_extra_keys"] = not (set(body) - set(want))
    got_reminders = {(r.get("to"), r.get("invoice_id")) for r in reminders}
    checks["exact_reminders"] = got_reminders == expected["reminders"]
    return {
        "exact": all(checks.values()),
        "checks": checks,
        "reminders_got": sorted(map(list, got_reminders)),
        "reminders_expected": sorted(map(list, expected["reminders"])),
    }


class EdgeWeekFixture(FixtureServer):
    def __init__(self, *, seed: int, port: int, variant: str) -> None:
        super().__init__(seed=seed, port=port)
        if variant not in VARIANTS:
            raise ValueError(f"variant must be one of {VARIANTS}, got {variant!r}")
        self.variant = variant
        self.released_week = 0
        self._lock = threading.Lock()
        self.owner = install_owner_channel(self)
        self.route(
            "GET",
            "/reports/last",
            lambda _r: (200, {"last_week": self.last_week()}),
        )
        self.route("GET", "/invoices", self._invoices)
        self.route("POST", "/remind", self._remind)
        self.route("POST", "/report", self._report)
        self.route("GET", "/reports", lambda _r: (200, self.reports()))

    def release_week(self) -> int:
        with self._lock:
            self.released_week += 1
            return self.released_week

    def _invoices(self, r: Request) -> tuple[int, Any]:
        try:
            week = int(r.q("week") or "0")
        except ValueError:
            return 400, {"error": "week must be an integer"}
        with self._lock:
            released = self.released_week
        if week < 1 or week > released:
            return 404, {"error": f"week {week} is not available yet"}
        r.server.waypoints.reach("read_invoices", week=week)
        return 200, served_invoices(self.seed, week, self.variant)

    def _remind(self, r: Request) -> tuple[int, Any]:
        missing = missing_fields(r.body, "to", "invoice_id")
        if missing:
            return reject(r.server, "remind", r.body, missing)
        r.server.recorder.record("remind", r.body)
        return 200, {"status": "sent"}

    def _report(self, r: Request) -> tuple[int, Any]:
        r.server.recorder.record("report", r.body)
        return 200, {"status": "received"}

    def reports(self) -> list[Any]:
        return [e["payload"] for e in self.recorder.all("report")]

    def reminders(self) -> list[dict[str, Any]]:
        return [e["payload"] for e in self.recorder.all("remind")]

    def last_week(self) -> int:
        last = 0
        for body in self.reports():
            if isinstance(body, dict):
                try:
                    last = max(last, int(body.get("week") or 0))
                except (TypeError, ValueError):
                    continue
        return last


def build(
    *,
    seed: int = DEFAULT_SEED,
    port: int = DEFAULT_PORT,
    variant: str = "empty",
):
    return EdgeWeekFixture(seed=seed, port=port, variant=variant)
