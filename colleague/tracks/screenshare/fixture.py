"""Two copies of a small ops board, and frames of somebody using one of them.

Instance A is Daniel's. He shares his screen and does four things on it —
creates a ticket, assigns it, tags it, closes an old one — and the fixture
renders a frame of his screen after each step, with the action he just took
shown the way an application shows it: as a toast at the bottom, not as a
caption written for a model. Instance B is the assistant's own, and starts in
the state A started in.

The frames are the only place the four actions are described. The request
says "do the same on yours" and nothing about what "the same" is. Whether an
arm can turn what it saw into what it does is the whole measurement, and the
final state of B is the only witness.
"""

from __future__ import annotations

import copy
import tempfile
from pathlib import Path
from typing import Any

from colleague.harness.conversation import Participant
from colleague.harness.fixture_server import (
    FixtureServer,
    Request,
    missing_fields,
    reject,
)
from colleague.harness.persona import Persona, PersonaPool
from colleague.harness.frames import (
    AMBER,
    BLACK,
    BLUE,
    GREEN,
    GREY,
    LIGHT,
    RED,
    WHITE,
    Canvas,
)

DEFAULT_SEED = 20260801
DEFAULT_PORT = 8151

#: The board both instances start with.
INITIAL_TICKETS: list[dict[str, Any]] = [
    {
        "id": "t-1",
        "title": "Old VAT query",
        "priority": "low",
        "assignee": "",
        "tags": [],
        "status": "open",
    },
    {
        "id": "t-2",
        "title": "Renew licences",
        "priority": "medium",
        "assignee": "tomasz",
        "tags": ["ops"],
        "status": "open",
    },
    {
        "id": "t-3",
        "title": "Q3 offsite venue",
        "priority": "low",
        "assignee": "priya",
        "tags": [],
        "status": "open",
    },
]

#: What Daniel does on A, in order. Ground truth for B, and the script the
#: frames are rendered from. Never sent to the arm as text.
DEMONSTRATION: list[dict[str, Any]] = [
    {"action": "create", "title": "Renew Halden contract", "priority": "high"},
    {"action": "assign", "ticket": "t-4", "to": "meera"},
    {"action": "tag", "ticket": "t-4", "tag": "vendor"},
    {"action": "close", "ticket": "t-1"},
]

NEW_TITLE = "renew halden contract"

#: `follow_the_share` swaps Daniel for a stand-in who will not narrate the
#: demonstration: the four steps exist only in the frames, and a Daniel who
#: typed them out on request would collapse the scenario into its own text
#: control. Scenario-scoped, because in `follow_the_text` he literally did
#: say the steps and may restate them.
FRAMES_PERSONA_OVERRIDES: dict[str, dict[str, Any]] = {
    "daniel": {
        "brief": (
            "You are Daniel Okafor. You just demonstrated four board "
            "actions over screen share and asked your assistant to do the "
            "same on its own board. You are not going to type the steps "
            "out — that is the whole point of showing it. If asked what "
            "you did, say to look at what you showed on screen; if asked "
            "anything about a specific step, say the share showed "
            "everything."
        ),
        "knowledge": {},
        "fallback": "It's all in what I showed you on screen.",
        "fallback_label": "repointed",
        "forbidden": ("halden", "meera", "vendor", "vat"),
    },
}

FRAME_W, FRAME_H = 900, 420


def apply(board: list[dict[str, Any]], step: dict[str, Any]) -> str:
    """Apply one action to a board in place; return the toast text."""
    if step["action"] == "create":
        tid = f"t-{len(board) + 1}"
        board.append(
            {
                "id": tid,
                "title": step["title"],
                "priority": step["priority"],
                "assignee": "",
                "tags": [],
                "status": "open",
            },
        )
        return f"NEW TICKET {tid}: {step['title']} ({step['priority']})"
    ticket = next(t for t in board if t["id"] == step["ticket"])
    if step["action"] == "assign":
        ticket["assignee"] = step["to"]
        return f"ASSIGNED {ticket['id']} TO {step['to']}"
    if step["action"] == "tag":
        ticket["tags"].append(step["tag"])
        return f"TAGGED {ticket['id']}: {step['tag']}"
    if step["action"] == "close":
        ticket["status"] = "closed"
        return f"CLOSED {ticket['id']}: {ticket['title']}"
    raise KeyError(step["action"])


def expected_final_board() -> list[dict[str, Any]]:
    board = copy.deepcopy(INITIAL_TICKETS)
    for step in DEMONSTRATION:
        apply(board, step)
    return board


def _render(board: list[dict[str, Any]], toast: str, owner: str) -> Canvas:
    c = Canvas(FRAME_W, FRAME_H)
    c.rect(0, 0, FRAME_W, 44, BLUE)
    c.text(14, 12, f"OPS BOARD - {owner}", WHITE, 3)
    c.text(
        14,
        60,
        "ID    TITLE                    PRIO    ASSIGNEE  TAGS      STATUS",
        GREY,
        2,
    )
    c.rect(14, 78, FRAME_W - 28, 2, LIGHT)
    y = 92
    for t in board:
        color = GREY if t["status"] == "closed" else BLACK
        c.text(14, y, t["id"].ljust(5), color, 2)
        c.text(86, y, t["title"][:24].ljust(24), color, 2)
        prio_color = {"high": RED, "medium": AMBER}.get(t["priority"], color)
        c.text(386, y, t["priority"].ljust(7), prio_color, 2)
        c.text(482, y, (t["assignee"] or "-").ljust(9), color, 2)
        c.text(602, y, (",".join(t["tags"]) or "-")[:9].ljust(9), color, 2)
        c.text(722, y, t["status"], GREEN if t["status"] == "open" else GREY, 2)
        y += 30
    if toast:
        c.rect(14, FRAME_H - 60, FRAME_W - 28, 44, LIGHT)
        c.text(28, FRAME_H - 46, "> " + toast, BLUE, 3)
    return c


def frames(seed: int = DEFAULT_SEED) -> list[str]:
    """Render Daniel's screen after each step; return the file paths in order.

    Deterministic for a seed (the demonstration is scripted, so the seed
    only names the directory), and cheap enough to re-render on every build.
    """
    out_dir = Path(tempfile.gettempdir()) / "colleague-screenshare" / f"seed-{seed}"
    board = copy.deepcopy(INITIAL_TICKETS)
    paths: list[str] = []
    paths.append(str(_render(board, "", "DANIEL").save(out_dir / "frame-0.png")))
    for i, step in enumerate(DEMONSTRATION, start=1):
        toast = apply(board, step)
        paths.append(
            str(_render(board, toast, "DANIEL").save(out_dir / f"frame-{i}.png")),
        )
    return paths


def _personas() -> PersonaPool:
    return PersonaPool(
        [
            Persona(
                participant=Participant(
                    id="daniel",
                    name="Daniel Okafor",
                    role="the person you work for",
                    email="daniel@northwind.example",
                ),
                brief=(
                    "You are Daniel Okafor. Your assistant is mirroring "
                    "some board changes for you. Answer questions briefly "
                    "as yourself; when it reports the work done, a short "
                    "acknowledgment or nothing at all is your way."
                ),
                fallback="Noted.",
                fallback_label="conversational",
            ),
        ],
    )


def build(*, seed: int = DEFAULT_SEED, port: int = DEFAULT_PORT) -> FixtureServer:
    fx = FixtureServer(seed=seed, port=port)
    fx.state["personas"] = _personas()
    fx.state["boards"] = {
        "a": expected_final_board(),  # Daniel already did his part
        "b": copy.deepcopy(INITIAL_TICKETS),
    }
    fx.state["frames"] = frames(seed)

    def board(inst: str):
        def handler(_r: Request) -> tuple[int, Any]:
            fx.waypoints.reach(f"read_{inst}")
            return 200, {"instance": inst, "tickets": fx.state["boards"][inst]}

        return handler

    def mutate(inst: str, action: str, *fields: str):
        def handler(r: Request) -> tuple[int, Any]:
            missing = missing_fields(r.body, *fields)
            if missing:
                return reject(r.server, f"{inst}_{action}", r.body, missing)
            body = dict(r.body)
            tickets = fx.state["boards"][inst]
            step: dict[str, Any] = {"action": action}
            if action == "create":
                step.update(
                    title=str(body["title"]).strip(),
                    priority=str(body["priority"]).strip().lower(),
                )
            else:
                tid = str(body["ticket"]).strip().lower()
                if not any(t["id"] == tid for t in tickets):
                    return 404, {"error": f"no ticket {tid!r} on instance {inst}"}
                step["ticket"] = tid
                if action == "assign":
                    step["to"] = str(body["to"]).strip().lower()
                if action == "tag":
                    step["tag"] = str(body["tag"]).strip().lower()
            toast = apply(tickets, step)
            fx.waypoints.reach(f"{inst}_mutation", action=action)
            fx.recorder.record(f"{inst}_{action}", body)
            return 200, {"status": "ok", "did": toast, "tickets": tickets}

        return handler

    for inst in ("a", "b"):
        fx.route("GET", f"/{inst}/board", board(inst))
        fx.route(
            "POST",
            f"/{inst}/tickets",
            mutate(inst, "create", "title", "priority"),
        )
        fx.route("POST", f"/{inst}/assign", mutate(inst, "assign", "ticket", "to"))
        fx.route("POST", f"/{inst}/tag", mutate(inst, "tag", "ticket", "tag"))
        fx.route("POST", f"/{inst}/close", mutate(inst, "close", "ticket"))
    return fx


API_DOC = """\
Ops board API at {base_url}. Two instances: /a is Daniel's board, /b is yours.
  GET  {base_url}/<inst>/board    -> {{"instance", "tickets": [{{id, title, priority, assignee, tags, status}}]}}
  POST {base_url}/<inst>/tickets  -> body {{"title": "<str>", "priority": "low"|"medium"|"high"}}
  POST {base_url}/<inst>/assign   -> body {{"ticket": "<id>", "to": "<person>"}}
  POST {base_url}/<inst>/tag      -> body {{"ticket": "<id>", "tag": "<str>"}}
  POST {base_url}/<inst>/close    -> body {{"ticket": "<id>"}}

Ticket ids are assigned in creation order (t-1, t-2, ...).\
"""
