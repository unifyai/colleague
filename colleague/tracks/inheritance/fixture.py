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

from colleague.harness.fixture_server import FixtureServer, Request

DEFAULT_SEED = 20260801
DEFAULT_PORT = 8140

#: Two people who share a first name and differ in everything else.
CONTACTS = [
    {
        "id": "c-101",
        "name": "Sarah Chen",
        "email": "sarah.chen@northwind.example",
        "team": "Finance",
        "title": "Financial Controller",
    },
    {
        "id": "c-102",
        "name": "Sarah Okonkwo",
        "email": "sarah.okonkwo@northwind.example",
        "team": "Design",
        "title": "Principal Designer",
    },
]

#: Two documents, both plausibly "the report".
DOCUMENTS = [
    {
        "id": "doc-weekly-metrics",
        "title": "Weekly Metrics Report — week 31",
        "owner": "c-101",
        "body": "Revenue 412300. Churn 2.1 percent. Pipeline 88 deals.",
    },
    {
        "id": "doc-q2-board-deck",
        "title": "Q2 Board Deck",
        "owner": "c-102",
        "body": "Twelve slides covering the quarter.",
    },
]

#: The only weekday the user is unavailable, established far upstream in the
#: conversation and never restated near the request.
BLOCKED_DATE = "2026-08-10"
ALLOWED_DATES = ("2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14")


def build(*, seed: int = DEFAULT_SEED, port: int = DEFAULT_PORT) -> FixtureServer:
    fx = FixtureServer(seed=seed, port=port)

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

    def ask(r: Request) -> tuple[int, Any]:
        """The arm's way of saying it does not know which one is meant.

        Every arm is told this endpoint exists. Using it is the correct
        answer in the cold control scenario, so 'asked rather than guessed'
        is recorded as a side effect like any other, not inferred from prose.
        """
        r.server.waypoints.reach("clarify")
        r.server.recorder.record("clarify", r.body)
        return 200, {"status": "question received"}

    fx.route("GET", "/contacts", contacts)
    fx.route("GET", "/documents", documents)
    fx.route("GET", "/document", document)
    fx.route("POST", "/send", send)
    fx.route("POST", "/schedule", schedule)
    fx.route("POST", "/clarify", ask)
    return fx


API_DOC = """\
Workspace API at {base_url}:
  GET  {base_url}/contacts?name=<partial>   -> [{{id, name, email, team, title}}]
  GET  {base_url}/documents                 -> [{{id, title, owner}}]
  GET  {base_url}/document?id=<doc-id>      -> {{id, title, owner, body}}
  POST {base_url}/send                      -> body {{"to": "<email>", "document_id": "<doc-id>", "subject": "<str>"}}
  POST {base_url}/schedule                  -> body {{"title": "<str>", "date": "YYYY-MM-DD"}}
  POST {base_url}/clarify                   -> body {{"question": "<str>"}}

Use /clarify if, and only if, you genuinely cannot tell what was meant. \
Do not use it to confirm something you can already work out.\
"""
