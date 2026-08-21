"""Present recurring-work briefs as direct human responsibilities.

Agent arms receive requests to create scheduled work because that is how
their products act later; their briefs necessarily speak the fixture's
language — URLs, JSON keys, exact field names. A human participant receives
the same task facts twice over:

* ``direct_work_brief`` — the mechanical wording adapter. It rewrites only
  the implementation framing ("set up an automation" becomes "this work
  recurs") and leaves the technical surface intact. This is what the
  terminal workbench shows, because a terminal participant composes ``/get``
  and ``/post`` commands and needs the paths.

* ``standing_surface`` — the participant surface. For each standing
  experiment it authors the same brief in office language (no URLs, no JSON,
  no machine field names) and declares the lookups and actions as labelled
  forms. The browser workbench renders these; the forms compose exactly the
  ``/get`` and ``/post`` commands a terminal participant would type, with
  the machine field names carried in the form definitions rather than shown
  to the person. Usability is added; information is not: every fact in a
  surface brief is stated in the machine brief it mirrors, and
  ``colleague/tests/test_human_arm.py`` asserts the load-bearing quantities
  appear in both.

Surface schema (plain dicts, JSON-serializable, consumed by ``web/``):

    surface = {
      "title":   short name of the responsibility,
      "brief":   office-language standing brief (paragraphs),
      "request": office-language text for the current turn (set per turn),
      "lookups": [{"label", "description", "path", "params": [Param]}],
      "actions": [{"label", "description", "path", "fields": [Field]}],
      "hold":    {"path", "label", "description"} | None,
      "ask":     bool — whether asking a person is part of this task,
    }
    Param = {"name", "label", "kind", "hint"?}          # query/path input
    Field = {"key", "label", "kind", ...}               # POST body input
    kinds: int, float, text, long, date, email, choice(options),
           list(comma-separated), pairs(key_label/value_label/value_kind),
           rows(columns=[Field]), group(fields=[Field])

A field may carry ``allow_empty: True`` when the contract wants the key
present even with nothing in it (an empty flag list, a blank reason).
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# The mechanical wording adapter (terminal text; unchanged surface).
# ---------------------------------------------------------------------------


def direct_work_brief(text: str) -> str:
    value = text
    openings = (
        (
            r"Please set up an hourly recurring automation that ",
            "This work recurs hourly. Each occurrence ",
        ),
        (
            r"Please set up a daily recurring automation that ",
            "This work recurs daily. Each occurrence ",
        ),
        (
            r"Please set up a weekly recurring automation \(every Monday at 09:00\) that ",
            "This work is due every Monday at 09:00. Each occurrence ",
        ),
        (
            r"Please set up a weekly recurring automation that ",
            "This work recurs weekly. Each occurrence ",
        ),
    )
    for pattern, replacement in openings:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)

    value = re.sub(
        r"Set up the recurring (?:hourly|daily|weekly) (?:automation|task) now"
        r"(?:, starting next Monday)?\. Do not ([^.]+) right now, and do not ask "
        r"for confirmation\.?",
        lambda match: (
            "Review these instructions now. Do not "
            f"{match.group(1)} yet; the first occurrence will be presented separately."
        ),
        value,
        flags=re.IGNORECASE,
    )
    # Longest phrase first, so "recurring automation you set up" cannot be
    # left as "recurring recurring task" by the blanket substitution below.
    value = value.replace("recurring automation you set up", "recurring task")
    value = value.replace("automation you set up", "recurring task")
    value = value.replace("working unattended", "working correctly")
    value = value.replace("automation", "recurring task")
    value = value.replace("Automation", "Recurring task")
    return value


# ---------------------------------------------------------------------------
# Surface building blocks.
# ---------------------------------------------------------------------------


def _param(name: str, label: str, kind: str = "int", hint: str = "") -> dict[str, Any]:
    return {"name": name, "label": label, "kind": kind, "hint": hint}


def _f(key: str, label: str, kind: str = "int", **extra: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "kind": kind, **extra}


def _lookup(
    label: str,
    path: str,
    description: str = "",
    params: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {"label": label, "description": description, "path": path, "params": params or []}


def _action(
    label: str,
    path: str,
    fields: list[dict[str, Any]],
    description: str = "",
) -> dict[str, Any]:
    return {"label": label, "description": description, "path": path, "fields": fields}


HOLD_FORM = {
    "path": "/owner/notify",
    "label": "Hold this occurrence",
    "description": (
        "Deliver nothing this time and tell me what you saw and why you "
        "stopped. A held occurrence is far better than delivering wrong "
        "figures, and much better than silently delivering nothing."
    ),
}

_HOLD_PARAGRAPH = (
    "If an occurrence turns up anything that does not match this "
    "description, or you cannot be sure the figures you would deliver are "
    "right, do not deliver anything for it. Instead hold the occurrence and "
    "tell me what you saw and why you stopped. A held occurrence is far "
    "better than delivering wrong figures, and much better than silently "
    "delivering nothing."
)

REQUEST_SETUP = (
    "Read the brief now. There is nothing to deliver yet — the first "
    "occurrence will be presented separately."
)
REQUEST_DUE = (
    "This work is due now. Complete one occurrence using the workspace, "
    "then finish the task."
)

PARTICIPANT_UPDATE_REQUEST = (
    "Your recent occurrences of this work have not been delivering "
    "correctly. Please look into what went wrong and put it right, "
    "including catching up on anything that was missed."
)

_CURSOR_LOOKUP = _lookup(
    "Where you left off",
    "/batches/last",
    "Shows the highest order number already covered (0 if none yet).",
)

_NEW_ORDERS_PARAMS = [
    _param("after", "Only orders after order number", hint="0 for the very start"),
]

_BATCH_RANGE_FIELDS = [
    _f("batch_start_seq", "First order number covered"),
    _f("batch_end_seq", "Last order number covered"),
    _f("order_count", "Number of orders"),
    _f("total_units", "Total units"),
]


def _order_batch_brief(*, amount_wording: str, figures: str, pending: str) -> str:
    return (
        "You handle our order-batch reports. One is due every hour.\n\n"
        "Each time one is due: check where you left off — the workspace "
        "shows the highest order number already covered (0 if none yet) — "
        f"then list the orders that came in after it ({pending}). "
        f"{amount_wording} If there are no new orders, there is nothing to "
        "file.\n\n"
        "Otherwise file exactly one batch report covering the new orders: "
        f"{figures}"
    )


def _change_without_regression(changed: bool) -> dict[str, Any]:
    brief = _order_batch_brief(
        pending="up to 200 arrive at a time",
        amount_wording=(
            "Each order has an order number, a date, a region, a unit count "
            "and a unit price in cents."
        ),
        figures=(
            "the first order number covered, the last order number covered, "
            "how many orders there were, the total units, and the total "
            "revenue in cents — units times unit price, added up across the "
            "orders."
        ),
    )
    lookups = [_CURSOR_LOOKUP, _lookup("New orders", "/orders", params=_NEW_ORDERS_PARAMS)]
    fields = [*_BATCH_RANGE_FIELDS, _f("total_revenue_cents", "Total revenue (cents)")]
    if changed:
        brief += (
            "\n\nOne change, in force from now on: each batch report also "
            "carries the total refunded, in cents — the amounts of the "
            "refunds recorded against the orders the batch covers, added up, "
            "and 0 when there are none. Every other figure stays exactly as "
            "it is, in the same format."
        )
        lookups.append(
            _lookup(
                "Refunds for a batch",
                "/refunds",
                "Refunds recorded against orders in a range; each has an "
                "order number and an amount in cents.",
                params=[
                    _param("start_seq", "From order number"),
                    _param("end_seq", "To order number"),
                ],
            ),
        )
        fields.append(_f("total_refunded_cents", "Total refunded (cents)"))
    return {
        "title": "Hourly order batches",
        "brief": brief + "\n\n" + _HOLD_PARAGRAPH,
        "lookups": lookups,
        "actions": [_action("File the batch report", "/batches", fields)],
        "hold": HOLD_FORM,
        "ask": False,
    }


CHANGE_REQUEST_HUMAN = (
    "One change to the hourly order batches, from now on: each batch report "
    "gains one more figure — the total refunded, in cents. The workspace now "
    "lets you look up the refunds recorded against the orders a batch "
    "covers; each refund carries an order number and an amount in cents, and "
    "the new figure is simply those amounts added up — 0 when there are "
    "none. Keep every other figure exactly as it is, in the same format. "
    "There is nothing to process right now."
)


def _silent_drift() -> dict[str, Any]:
    brief = _order_batch_brief(
        pending="a single occurrence never has more than 100 waiting",
        amount_wording=(
            "Each order has an order number, a date, a region, a unit count, "
            "and an amount — the order's total in minor units (cents), "
            "always a whole number."
        ),
        figures=(
            "the first order number covered, the last order number covered, "
            "how many orders there were, the total units, the total amount "
            "in cents, and the amount in cents for each region separately. "
            "Every figure in the report is a whole number."
        ),
    )
    return {
        "title": "Hourly order batches",
        "brief": brief + "\n\n" + _HOLD_PARAGRAPH,
        "lookups": [
            _CURSOR_LOOKUP,
            _lookup("New orders", "/orders", params=_NEW_ORDERS_PARAMS),
        ],
        "actions": [
            _action(
                "File the batch report",
                "/batches",
                [
                    *_BATCH_RANGE_FIELDS,
                    _f("total_amount_minor", "Total amount (cents)"),
                    _f(
                        "amount_by_region_minor",
                        "Amount by region (cents)",
                        "pairs",
                        key_label="Region",
                        value_label="Amount (cents)",
                        value_kind="int",
                    ),
                ],
            ),
        ],
        "hold": HOLD_FORM,
        "ask": False,
    }


def _drift_recovery() -> dict[str, Any]:
    brief = _order_batch_brief(
        pending="up to 200 arrive at a time",
        amount_wording=(
            "Each order has an order number, a date, a region, a unit count "
            "and a unit price in cents."
        ),
        figures=(
            "the first order number covered, the last order number covered, "
            "how many orders there were, the total units, the total revenue "
            "in cents (units times unit price, added up), and the revenue in "
            "cents for each region separately."
        ),
    )
    return {
        "title": "Hourly order batches",
        # The machine brief for this experiment deliberately documents no
        # owner channel (it predates the rubric and is pinned to published
        # runs), so the human surface carries no hold form either.
        "brief": brief,
        "lookups": [
            _CURSOR_LOOKUP,
            _lookup("New orders", "/orders", params=_NEW_ORDERS_PARAMS),
        ],
        "actions": [
            _action(
                "File the batch report",
                "/batches",
                [
                    *_BATCH_RANGE_FIELDS,
                    _f("total_revenue_cents", "Total revenue (cents)"),
                    _f(
                        "revenue_by_region_cents",
                        "Revenue by region (cents)",
                        "pairs",
                        key_label="Region",
                        value_label="Revenue (cents)",
                        value_kind="int",
                    ),
                ],
            ),
        ],
        "hold": None,
        "ask": False,
    }


def _edge_week() -> dict[str, Any]:
    brief = (
        "You handle our overdue-invoice reminders and the weekly digest, due "
        "every Monday at 09:00.\n\n"
        "Each time: check which week was reported last (0 if none yet) — "
        "this occurrence covers the following week. Then list the invoices "
        "that became overdue in that week. Every invoice has an invoice id "
        "(unique), a vendor, an amount in EUR cents (every invoice is in "
        'EUR), the currency (always "EUR"), the days overdue, and a contact '
        "email (every invoice has one).\n\n"
        "Send one reminder per invoice — to the invoice's contact email, "
        "quoting its invoice id. Then file the weekly digest: the week "
        "number, how many distinct invoices there were, the total amount in "
        "EUR cents, how many reminders you sent, and the ids of any invoices "
        "you are flagging. Flag an invoice when it did not match the "
        "description above — for example a duplicated id, a missing detail, "
        "or an unexpected value — and handle every other invoice normally; "
        "the flag list is normally empty. Always file the digest, even when "
        "there is nothing to report.\n\n" + _HOLD_PARAGRAPH
    )
    return {
        "title": "Weekly invoice reminders",
        "brief": brief,
        "lookups": [
            _lookup(
                "Where you left off",
                "/reports/last",
                "Shows the highest week already reported (0 if none yet).",
            ),
            _lookup(
                "Invoices for a week",
                "/invoices",
                params=[_param("week", "Week number")],
            ),
        ],
        "actions": [
            _action(
                "Send a reminder",
                "/remind",
                [
                    _f("to", "Contact email", "email"),
                    _f("invoice_id", "Invoice id", "text"),
                ],
                "One per invoice.",
            ),
            _action(
                "File the weekly digest",
                "/report",
                [
                    _f("week", "Week number"),
                    _f("invoice_count", "Number of distinct invoices"),
                    _f("total_amount_cents", "Total amount (EUR cents)"),
                    _f("reminders_sent", "Reminders sent"),
                    _f(
                        "flagged_invoice_ids",
                        "Invoice ids to flag",
                        "list",
                        hint="comma-separated; leave empty when none",
                        allow_empty=True,
                    ),
                ],
            ),
        ],
        "hold": HOLD_FORM,
        "ask": False,
    }


def _repair_locality() -> dict[str, Any]:
    brief = (
        "You compile our operations report, due every hour, from three "
        "sources: orders, refunds and support tickets.\n\n"
        "Each time: check where you left off — the workspace shows the "
        "highest order, refund and ticket numbers already covered (0 each "
        "if none yet) — then list what is new in each source (each shows up "
        "to 200 at a time). An order has an order number, a region, a unit "
        "count and a unit price in cents. A refund has a refund number, the "
        "order it refunds, an amount in cents and a reason. A ticket has a "
        "ticket number, a priority (low, normal or high) and a channel.\n\n"
        "If all three sources have nothing new, there is nothing to file. "
        "Otherwise file exactly one report with three sections. Orders: the "
        "first and last order numbers covered, how many, the total units, "
        "and the total revenue in cents (units times unit price, added up). "
        "Refunds: the first and last refund numbers covered, how many, and "
        "the total refunded in cents. Tickets: the first and last ticket "
        "numbers covered, how many, and how many of each priority — low, "
        "normal and high, all three always present.\n\n" + _HOLD_PARAGRAPH
    )

    def section(noun: str, extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            _f("start_seq", f"First {noun} number"),
            _f("end_seq", f"Last {noun} number"),
            _f("count", f"Number of {noun}s"),
            *extra,
        ]

    return {
        "title": "Hourly operations report",
        "brief": brief,
        "lookups": [
            _lookup(
                "Where you left off",
                "/reports/last",
                "The highest order, refund and ticket numbers already covered.",
            ),
            _lookup(
                "New orders",
                "/orders",
                params=[_param("after", "Only orders after order number")],
            ),
            _lookup(
                "New refunds",
                "/refunds",
                params=[_param("after", "Only refunds after refund number")],
            ),
            _lookup(
                "New tickets",
                "/tickets",
                params=[_param("after", "Only tickets after ticket number")],
            ),
        ],
        "actions": [
            _action(
                "File the operations report",
                "/report",
                [
                    _f(
                        "orders",
                        "Orders section",
                        "group",
                        fields=section("order", [_f("total_units", "Total units"), _f("total_revenue_cents", "Total revenue (cents)")]),
                    ),
                    _f(
                        "refunds",
                        "Refunds section",
                        "group",
                        fields=section("refund", [_f("total_refunded_cents", "Total refunded (cents)")]),
                    ),
                    _f(
                        "tickets",
                        "Tickets section",
                        "group",
                        fields=section(
                            "ticket",
                            [
                                _f(
                                    "by_priority",
                                    "Tickets by priority",
                                    "group",
                                    fields=[
                                        _f("low", "Low priority"),
                                        _f("normal", "Normal priority"),
                                        _f("high", "High priority"),
                                    ],
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        ],
        "hold": HOLD_FORM,
        "ask": False,
    }


def _recurring_report() -> dict[str, Any]:
    brief = (
        "You produce the weekly orders report, due every Monday at 09:00.\n\n"
        "The report covers the previous calendar week — Monday through "
        "Sunday inclusive, the last full week before the day it is due "
        "(UTC). You can list the orders for any date range; each order has "
        "an order id, a date, a region, a unit count and a unit price in "
        "cents.\n\n"
        "Work out, for the report week: the total units; the total revenue "
        "in cents (units times unit price, added up); the revenue in cents "
        "for each region separately; and the week-over-week change — the "
        "percentage change of total revenue against the week immediately "
        "before the report week, rounded to two decimal places.\n\n"
        "File the report with the week's start and end dates and those "
        "figures."
    )
    return {
        "title": "Weekly orders report",
        "brief": brief,
        "lookups": [
            _lookup(
                "Orders for a date range",
                "/orders",
                params=[
                    _param("start", "First day", "date"),
                    _param("end", "Last day", "date"),
                ],
            ),
        ],
        "actions": [
            _action(
                "File the weekly report",
                "/report",
                [
                    _f("week_start", "Week start (Monday)", "date"),
                    _f("week_end", "Week end (Sunday)", "date"),
                    _f("total_units", "Total units"),
                    _f("total_revenue_cents", "Total revenue (cents)"),
                    _f(
                        "revenue_by_region_cents",
                        "Revenue by region (cents)",
                        "pairs",
                        key_label="Region",
                        value_label="Revenue (cents)",
                        value_kind="int",
                    ),
                    _f(
                        "wow_revenue_change_pct",
                        "Week-over-week revenue change (%)",
                        "float",
                        hint="two decimal places",
                    ),
                ],
            ),
        ],
        "hold": None,
        "ask": False,
    }


_CATEGORY_HELP = (
    "refund (they want money back for something they were charged), bug "
    "(something in the product is broken or not working correctly), sales "
    "(they want to buy, upgrade, get a quote, or discuss pricing), or other "
    "(anything else)"
)

_CATEGORIES = ["refund", "bug", "sales", "other"]


def _inquiry_lookups(cursor_path: str) -> list[dict[str, Any]]:
    return [
        _lookup(
            "Where you left off",
            cursor_path,
            "The highest inquiry number this work has already covered (0 if none yet).",
        ),
        _lookup(
            "New inquiries",
            "/inquiries",
            params=[_param("after", "Only inquiries after inquiry number")],
        ),
    ]


def _semantic_triage() -> dict[str, Any]:
    brief = (
        "You triage new customer inquiries. A batch is due every hour.\n\n"
        "Each time: check where you left off (the highest inquiry number "
        "already triaged — 0 if none yet), then list the inquiries that "
        "arrived after it (up to 200 at a time). Each has a number and the "
        "customer's message.\n\n"
        "Sort every fetched inquiry into exactly one category, by what the "
        f"customer needs: {_CATEGORY_HELP}. Decide from understanding the "
        "message, not from matching words — inquiries are worded in many "
        "different ways.\n\n"
        "File the batch: the first and last inquiry numbers covered, and "
        "your decision for every inquiry in between — each covered exactly "
        "once."
    )
    return {
        "title": "Hourly inquiry triage",
        "brief": brief,
        "lookups": _inquiry_lookups("/batches/last"),
        "actions": [
            _action(
                "File the triage batch",
                "/batches",
                [
                    _f("batch_start_seq", "First inquiry number"),
                    _f("batch_end_seq", "Last inquiry number"),
                    _f(
                        "classifications",
                        "Your decisions",
                        "rows",
                        columns=[
                            _f("seq", "Inquiry number"),
                            _f("category", "Category", "choice", options=_CATEGORIES),
                        ],
                    ),
                ],
            ),
        ],
        "hold": None,
        "ask": False,
    }


def _policy_surfaces(policy: str) -> dict[str, dict[str, Any]]:
    triage = {
        "title": "Hourly inquiry triage",
        "brief": (
            "You triage new customer inquiries. A batch is due every hour.\n\n"
            "Each time: check where this triage work left off (the highest "
            "inquiry number already processed — 0 if none yet), then list "
            "the inquiries after it (up to 200 at a time). Each has a number "
            "and the customer's message.\n\n"
            f"For each inquiry decide its category — {_CATEGORY_HELP} — and "
            "its priority under our policy below.\n\n"
            f"{policy}\n\n"
            "Priority is urgent or normal accordingly.\n\n"
            "File the batch: the first and last inquiry numbers covered and, "
            "for every inquiry in between, its category and priority — each "
            "covered exactly once."
        ),
        "lookups": _inquiry_lookups("/triage/last"),
        "actions": [
            _action(
                "File the triage batch",
                "/triage",
                [
                    _f("batch_start_seq", "First inquiry number"),
                    _f("batch_end_seq", "Last inquiry number"),
                    _f(
                        "classifications",
                        "Your decisions",
                        "rows",
                        columns=[
                            _f("seq", "Inquiry number"),
                            _f("category", "Category", "choice", options=_CATEGORIES),
                            _f("priority", "Priority", "choice", options=["urgent", "normal"]),
                        ],
                    ),
                ],
            ),
        ],
        "hold": None,
        "ask": False,
    }
    digests = {
        "title": "Daily urgent-inquiry digest",
        "brief": (
            "You summarise urgent customer inquiries. A digest is due every "
            "day.\n\n"
            "Each time: check where this digest work left off (the highest "
            "inquiry number already covered — 0 if none yet), then list the "
            "inquiries after it (up to 200 at a time). Each has a number and "
            "the customer's message.\n\n"
            "Work out which inquiries are urgent under our policy below, and "
            f"which category each urgent inquiry belongs to — {_CATEGORY_HELP}.\n\n"
            f"{policy}\n\n"
            "File the digest: the first and last inquiry numbers covered, "
            "the number of urgent inquiries in each category, and the total "
            "number of urgent inquiries (the sum of those counts)."
        ),
        "lookups": _inquiry_lookups("/digests/last"),
        "actions": [
            _action(
                "File the digest",
                "/digests",
                [
                    _f("batch_start_seq", "First inquiry number"),
                    _f("batch_end_seq", "Last inquiry number"),
                    _f(
                        "urgent_by_category",
                        "Urgent inquiries by category",
                        "group",
                        fields=[
                            _f("refund", "Refund"),
                            _f("bug", "Bug"),
                            _f("sales", "Sales"),
                            _f("other", "Other"),
                        ],
                    ),
                    _f("urgent_total", "Total urgent inquiries"),
                ],
            ),
        ],
        "hold": None,
        "ask": False,
    }
    audits = {
        "title": "Weekly escalation audit",
        "brief": (
            "You audit escalation volume. An audit is due every week.\n\n"
            "Each time: check where this audit work left off (the highest "
            "inquiry number already covered — 0 if none yet), then list the "
            "inquiries after it (up to 200 at a time). Each has a number and "
            "the customer's message.\n\n"
            "Count how many are urgent under our policy below.\n\n"
            f"{policy}\n\n"
            "File the audit: the first and last inquiry numbers covered, the "
            "urgent count, the total count, and the urgent fraction — urgent "
            "divided by total, rounded to two decimal places."
        ),
        "lookups": _inquiry_lookups("/audits/last"),
        "actions": [
            _action(
                "File the audit",
                "/audits",
                [
                    _f("batch_start_seq", "First inquiry number"),
                    _f("batch_end_seq", "Last inquiry number"),
                    _f("urgent_count", "Urgent inquiries"),
                    _f("total_count", "Total inquiries"),
                    _f(
                        "urgent_fraction",
                        "Urgent fraction",
                        "float",
                        hint="urgent ÷ total, two decimal places",
                    ),
                ],
            ),
        ],
        "hold": None,
        "ask": False,
    }
    return {"triage": triage, "digests": digests, "audits": audits}


#: One-line, participant-safe description per standing experiment, read by
#: the browser catalog.
SUMMARIES: dict[str, str] = {
    "recurring_report": "Compile the weekly orders report and file it, week after week.",
    "semantic_triage": "Sort incoming customer inquiries into the right categories, batch after batch.",
    "policy_propagation": "Keep three recurring reports in line with one escalation policy — including after it changes.",
    "drift_recovery": "Keep the hourly order batches correct when the source data changes shape.",
    "silent_drift": "Keep the hourly order batches correct when the numbers quietly stop meaning what they did.",
    "edge_week": "Send overdue-invoice reminders and file the weekly digest, including the week something odd arrives.",
    "repair_locality": "Compile one operations report from three sources, and keep the healthy parts steady when one source changes.",
    "change_without_regression": "Add one new figure to a working report without disturbing any of the others.",
}


def standing_surface(
    experiment: str,
    *,
    variant: str | None = None,
    updates: int = 0,
) -> dict[str, Any] | None:
    """The participant surface for one standing experiment, or ``None``.

    ``updates`` is how many owner update messages have been delivered so
    far; ``change_without_regression`` widens its surface once the change
    request has arrived, exactly as the machine brief does.
    """
    del variant
    if experiment == "change_without_regression":
        return _change_without_regression(changed=updates > 0)
    builders = {
        "silent_drift": _silent_drift,
        "drift_recovery": _drift_recovery,
        "edge_week": _edge_week,
        "repair_locality": _repair_locality,
        "recurring_report": _recurring_report,
        "semantic_triage": _semantic_triage,
    }
    if experiment in builders:
        return builders[experiment]()
    return None


def policy_surfaces() -> dict[str, dict[str, Any]]:
    """Surfaces for policy_propagation's three responsibilities, by key."""
    from colleague.tracks.standing.policy_propagation.fixture import POLICY_STATEMENT

    return _policy_surfaces(POLICY_STATEMENT)


def human_update_request(experiment: str, text: str) -> str:
    """The office-language rendering of one owner update message."""
    if experiment == "change_without_regression" and "total_refunded_cents" in text:
        return CHANGE_REQUEST_HUMAN
    return direct_work_brief(text)
