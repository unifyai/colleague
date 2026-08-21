"""Participant surface for the refinement track's browser runs.

This track's spec is deliberately drip-fed: Daniel states the procedure
once, fixes the format once as feedback on the first draft, and never
restates either. A participant surface here must add mechanics without
adding memory — so the browser gets the *same* forms every week, and the
forms never state the title, the column names, the amount format or the
flag rule. Those live only in Daniel's messages, and keeping hold of them
is the thing being measured.

What the forms do add is the one thing the browser's generic contract
parser cannot compose: the report's nested ``rows`` payload. Rows are
entered as labelled cells and sent as lists in cell order, with the amount
kept a string exactly as typed and the flag a real boolean — the typed
composition a terminal participant gets by writing the body by hand.

The row cells are labelled Vendor, Category, Amount and Flagged. The first
three mirror fields every arm sees in the expenses lookup itself; the flag
cell names a concept every briefed week carries from Daniel's first
message. The unbriefed control shares the surface: its participant gains
the row shape a terminal participant would have to improvise, and the
control still measures what it exists to measure, because the facts it
proves undiscoverable — the exact title and column names — are typed by
the participant or not at all.
"""

from __future__ import annotations

from typing import Any


def _param(name: str, label: str, kind: str = "int", hint: str = "") -> dict[str, Any]:
    return {"name": name, "label": label, "kind": kind, "hint": hint}


def _f(key: str, label: str, kind: str = "text", **extra: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "kind": kind, **extra}


WORKSPACE_BRIEF = (
    "You look after Daniel Okafor's weekly client spend report. Everything "
    "about how the report should look and what belongs in it, Daniel tells "
    "you in his messages — nothing is restated here, so keep hold of what "
    "he has asked for.\n\n"
    "The controls below are only the workspace: look up a week's expenses, "
    "check the conversion rate, file the report, and ask Daniel when you "
    "need him."
)


def surface_for(request: str) -> dict[str, Any]:
    """The participant surface for one refinement turn.

    ``request`` is the office-language text of the turn — Daniel's message
    verbatim (scenarios that embed the connection block pass the prose
    without it). The forms are identical every week by design; only this
    text varies.
    """
    return {
        "title": "Weekly client spend report",
        "brief": WORKSPACE_BRIEF,
        "request": request,
        "lookups": [
            {
                "label": "Expenses for a week",
                "description": (
                    "Each expense shows a vendor, a category, a description, "
                    "an amount in cents and a currency."
                ),
                "path": "/expenses",
                "params": [_param("week", "Week number")],
            },
            {
                "label": "Conversion rates",
                "description": "Euros per US dollar.",
                "path": "/rates",
                "params": [],
            },
        ],
        "actions": [
            {
                "label": "File the report",
                "description": (
                    "Rows are sent in the order you enter them, each row's "
                    "cells in the order shown."
                ),
                "path": "/report",
                "fields": [
                    _f("week", "Week number", "int"),
                    _f("title", "Report title"),
                    _f(
                        "columns",
                        "Column names, in order",
                        "list",
                        hint="comma-separated",
                    ),
                    _f(
                        "rows",
                        "Report rows",
                        "rows",
                        as_lists=True,
                        columns=[
                            _f("vendor", "Vendor"),
                            _f("category", "Category"),
                            _f("amount", "Amount"),
                            _f("flagged", "Flagged", "bool"),
                        ],
                    ),
                ],
            },
        ],
        "hold": None,
        "ask": True,
    }
