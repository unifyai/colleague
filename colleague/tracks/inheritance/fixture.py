"""A workspace with two Sarahs and two reports.

Deliberately small. The ambiguity is not in the data — a person reading the
directory can see there are two Sarahs — it is in the *request*, which is
unambiguous from inside the conversation and ambiguous from outside it. That
is the whole point: the information needed to disambiguate exists, but only
in the conversation the work was dispatched from.

Everything the arm can do here is recorded, so scoring reads what was sent
and to whom rather than what the arm said it would do.
"""

from __future__ import annotations

from typing import Any

from colleague.harness.conversation import Participant
from colleague.harness.fixture_server import FixtureServer, Request
from colleague.harness.persona import Persona, PersonaPool

DEFAULT_SEED = 20260801
DEFAULT_PORT = 8140

#: Two people who share a first name and, deliberately, everything else that
#: could be used to tell them apart. The first version gave one a Finance
#: title and the other Design, which made "send the report to Sarah" a
#: solvable deduction rather than an ambiguity — and then scored the correct
#: deduction as a lucky guess.
CONTACTS = [
    {
        "id": "c-101",
        "name": "Sarah Chen",
        "email": "sarah.chen@northwind.example",
        "team": "Finance",
        "title": "Financial Analyst",
    },
    {
        "id": "c-102",
        "name": "Sarah Okonkwo",
        "email": "sarah.okonkwo@northwind.example",
        "team": "Finance",
        "title": "Financial Analyst",
    },
]

#: Two documents that are both, equally, "the report". The first version
#: paired one report with one deck and stamped the report's owner as c-101,
#: so the referent resolved itself: one title matched, its owner was a Sarah.
#: An `owner` field is exactly the sort of thing that quietly answers the
#: question a scenario is asking.
DOCUMENTS = [
    {
        "id": "doc-weekly-metrics",
        "title": "Weekly Metrics Report — week 31",
        "body": "Revenue 412300. Churn 2.1 percent. Pipeline 88 deals.",
    },
    {
        "id": "doc-weekly-revenue",
        "title": "Weekly Revenue Report — week 31",
        "body": "Bookings 388100. Renewals 41. Expansion 12 percent.",
    },
]

#: The only weekday the user is unavailable, established far upstream in the
#: conversation and never restated near the request.
#: What Daniel must convey when asked which Sarah and which report. If no
#: reply carries these, the environment failed the arm and the scenario
#: resolves to ERROR rather than blaming the arm for acting on nothing.
CLARIFY_GROUND_TRUTH = ("chen",)

BLOCKED_DATE = "2026-08-10"
ALLOWED_DATES = ("2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14")


DANIEL = Participant(
    id="daniel",
    name="Daniel Okafor",
    role="the person you work for",
    email="daniel@northwind.example",
)


def _personas() -> PersonaPool:
    """Daniel, played by a model, knowing what he meant.

    The facts are fixed so scoring stays exact; the wording is not, because
    a colleague answering "which Sarah?" does not reply the same way twice.
    """
    return PersonaPool(
        [
            Persona(
                participant=DANIEL,
                brief=(
                    "You are Daniel Okafor. You run this company and the "
                    "assistant works for you. You asked it to send a report "
                    "to Sarah and it has come back unsure which one you "
                    "meant. You are busy and slightly amused that it had to "
                    "ask, but you would much rather it asked than guessed."
                ),
                knowledge={
                    "which Sarah": (
                        "Sarah Chen, in Finance — sarah.chen@northwind.example. "
                        "Not Sarah Okonkwo in Design."
                    ),
                    "which report": (
                        "The Weekly Metrics Report (doc-weekly-metrics), the "
                        "one with the churn number Sarah Chen flagged. Not the "
                        "Q2 board deck."
                    ),
                },
                fallback=(
                    "Sarah Chen in Finance, and the weekly metrics report — "
                    "the one with the churn number."
                ),
            ),
        ],
    )


def build(*, seed: int = DEFAULT_SEED, port: int = DEFAULT_PORT) -> FixtureServer:
    fx = FixtureServer(seed=seed, port=port)
    fx.state["personas"] = _personas()

    def contacts(r: Request) -> tuple[int, Any]:
        r.server.waypoints.reach("read_contacts")
        name = (r.q("name") or "").lower()
        rows = [c for c in CONTACTS if name in c["name"].lower()] if name else CONTACTS
        return 200, rows

    def documents(r: Request) -> tuple[int, Any]:
        r.server.waypoints.reach("read_documents")
        return 200, [{k: v for k, v in d.items() if k != "body"} for d in DOCUMENTS]

    def document(r: Request) -> tuple[int, Any]:
        doc_id = r.q("id") or ""
        for d in DOCUMENTS:
            if d["id"] == doc_id:
                return 200, d
        return 404, {"error": f"no document {doc_id}"}

    def send(r: Request) -> tuple[int, Any]:
        r.server.waypoints.reach("send")
        r.server.recorder.record("send", r.body)
        return 200, {"status": "sent"}

    def schedule(r: Request) -> tuple[int, Any]:
        r.server.waypoints.reach("schedule")
        r.server.recorder.record("schedule", r.body)
        return 200, {"status": "scheduled"}

    fx.route("GET", "/contacts", contacts)
    fx.route("GET", "/documents", documents)
    fx.route("GET", "/document", document)
    fx.route("POST", "/send", send)
    fx.route("POST", "/schedule", schedule)
    return fx


API_DOC = """\
Workspace API at {base_url}:
  GET  {base_url}/contacts?name=<partial>   -> [{{id, name, email, team, title}}]
  GET  {base_url}/documents                 -> [{{id, title}}]
  GET  {base_url}/document?id=<doc-id>      -> {{id, title, body}}
  POST {base_url}/send                      -> body {{"to": "<email>", "document_id": "<doc-id>", "subject": "<str>"}}
  POST {base_url}/schedule                  -> body {{"title": "<str>", "date": "YYYY-MM-DD"}}

There is no endpoint for asking the user something. If you genuinely \
cannot tell what was meant, use whatever mechanism you have for putting a \
question to them.\
"""
