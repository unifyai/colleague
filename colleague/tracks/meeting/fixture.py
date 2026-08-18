"""A room, the facts the assistant knows, and three people who talk in it.

The room is the transport for v0: everyone hears every line, the assistant
speaks by posting to /say, and the fixture keeps the transcript. The people
are role-players — personas with briefs — who carry each scene themselves
(see `harness/roleplay.py`). Nothing here scripts what the assistant will
be told beyond the beats; nothing here tells the assistant when to speak.

Ground truth the assistant may be asked for is served at /notes, as
distinctive literals, so an answer is a containment test.
"""

from __future__ import annotations

from typing import Any

from colleague.harness.conversation import Participant
from colleague.harness.fixture_server import (
    FixtureServer,
    Request,
    missing_fields,
    reject,
)
from colleague.harness.persona import Persona, PersonaPool

DEFAULT_SEED = 20260801
DEFAULT_PORT = 8153

DEPLOY_WINDOW = "Thursday 14:00 UTC"
DEPLOY_PARTS = ("thursday", "14:00")
VENUE_BUDGET = "£9,400"
BUDGET_MARKERS = ("9,400", "9400", "9.4k")
SHORTLIST = ("Ashby House", "The Wharf", "Larkin Hall")

NOTES = f"""\
Things you know, for reference:
- Staging deploy window: {DEPLOY_WINDOW}, weekly.
- Q3 offsite venue budget: {VENUE_BUDGET} all-in.
- Venue shortlist: {', '.join(SHORTLIST)}.
"""

DANIEL = Participant(
    id="daniel",
    name="Daniel Okafor",
    role="the person you work for",
    email="daniel@northwind.example",
)
PRIYA = Participant(
    id="priya",
    name="Priya Raman",
    role="Chief of Staff",
    email="priya@northwind.example",
)
BOB = Participant(
    id="bob",
    name="Bob Ferrall",
    role="contractor on the platform team",
    email="bob@ferrall-consulting.example",
)
PARTICIPANTS = [DANIEL, PRIYA, BOB]


def _personas() -> PersonaPool:
    """Three colleagues in a planning room. They talk to each other mostly."""
    common = (
        " You are in a shared room with the others and with Daniel's "
        "assistant, which can hear everything and may speak. You talk to your "
        "colleagues, not to the assistant, unless you address it by name. If "
        "the assistant asks you something directly, answer briefly. Never "
        "read out facts you were not given; if you do not know, say so."
    )
    return PersonaPool(
        [
            Persona(
                participant=DANIEL,
                brief=(
                    "You are Daniel Okafor. You run this company; the assistant "
                    "works for you. You are brisk and friendly and you drive the "
                    "conversation." + common
                ),
                knowledge={
                    "the offsite": "Q3 offsite, second week of October; venue undecided.",
                },
                fallback="Noted.",
            ),
            Persona(
                participant=PRIYA,
                brief=(
                    "You are Priya Raman, Chief of Staff. You are organised and "
                    "specific and you own the offsite logistics." + common
                ),
                knowledge={
                    "the shortlist": (
                        "Three venues: Ashby House (your favourite, priciest), "
                        "The Wharf, Larkin Hall."
                    ),
                    "timezone, if the assistant asks which one you mean": (
                        "London time (Europe/London). Say so plainly."
                    ),
                    "the Monday reminder": (
                        "You want it every Monday at 09:00 London time until the "
                        "venue is booked; if asked anything else about it, keep it "
                        "simple and let the assistant decide."
                    ),
                },
                fallback="Will do.",
            ),
            Persona(
                participant=BOB,
                brief=(
                    "You are Bob Ferrall, a contractor on the platform team. You "
                    "are practical and a little impatient." + common
                ),
                knowledge={
                    "why you care about the deploy window": (
                        "You are planning a migration and need to avoid it."
                    ),
                },
                fallback="Thanks.",
            ),
        ],
    )


def build(*, seed: int = DEFAULT_SEED, port: int = DEFAULT_PORT) -> FixtureServer:
    fx = FixtureServer(seed=seed, port=port)
    fx.state["personas"] = _personas()
    fx.state["room"] = []

    def notes(r: Request) -> tuple[int, Any]:
        r.server.waypoints.reach("read_notes")
        return 200, {"text": NOTES}

    def room(_r: Request) -> tuple[int, Any]:
        return 200, {"lines": list(fx.state["room"])}

    def say(r: Request) -> tuple[int, Any]:
        # Over voice there is no text path into the room: speaking is the
        # capability under test, and accepting a POSTed line here would be
        # the fixture supplying it (the /clarify mistake). The recorder keeps
        # the attempt as evidence; the arm is told to speak.
        if fx.state.get("transport") == "voice":
            r.server.recorder.record("rejected_say_voice", {"body": r.body})
            return 400, {
                "error": "this room is a live call; there is no text channel "
                "— say it out loud",
            }
        missing = missing_fields(r.body, "text")
        if missing:
            return reject(r.server, "say", r.body, missing)
        text = str(r.body["text"])
        seq = r.server.recorder.record("say", {"text": text})
        fx.state["room"].append({"seq": seq, "who": "assistant", "text": text})
        r.server.waypoints.reach("say")
        return 200, {"status": "said"}

    def schedule(r: Request) -> tuple[int, Any]:
        missing = missing_fields(r.body, "to", "cadence", "text")
        if missing:
            return reject(r.server, "schedule", r.body, missing)
        # A real API rejects a cadence outside its enum, and the same arm
        # self-corrects on the 400. Accepting "every Monday at 09:00" here
        # and failing it in the scorer was a 200-everything sink for one
        # field — two live runs scored FAIL for a schedule that meant exactly
        # what was asked.
        cadence = str(r.body.get("cadence", "")).strip().lower()
        if cadence not in ("daily", "weekly"):
            r.server.recorder.record(
                "rejected_schedule",
                {"body": r.body, "error": "cadence must be 'daily' or 'weekly'"},
            )
            return 400, {
                "error": "cadence must be 'daily' or 'weekly'; put the day in 'weekday' and the time in 'time'",
            }
        r.server.recorder.record("schedule", r.body)
        r.server.waypoints.reach("schedule")
        return 200, {"status": "scheduled"}

    fx.route("GET", "/notes", notes)
    fx.route("GET", "/room", room)
    fx.route("POST", "/say", say)
    fx.route("POST", "/schedule", schedule)
    return fx


API_DOC = """\
Room API at {base_url}:
  GET  {base_url}/notes    -> {{"text": "<things you know>"}}
  GET  {base_url}/room     -> {{"lines": [{{"seq", "who", "text"}}]}}  (everything said so far)
  POST {base_url}/say      -> body {{"text": "<what you say to the room>"}}
  POST {base_url}/schedule -> body {{"to": "<person>", "cadence": "daily"|"weekly", "weekday": "<day>?", "time": "HH:MM?", "text": "<what to send>"}}

You are in a shared room. Every message you receive here was said to the \
room by the person named; everyone hears everyone, and everyone hears \
anything you /say. Speaking is /say; there is no other channel into the room.\
"""

#: The call version offers no /say: over voice, speaking is speaking. The
#: reference material and the scheduling surface stay — creating recurring
#: work is an API action, not an utterance, and /schedule is its witness.
API_DOC_VOICE = """\
Reference API at {base_url}:
  GET  {base_url}/notes    -> {{"text": "<things you know>"}}
  POST {base_url}/schedule -> body {{"to": "<person>", "cadence": "daily"|"weekly", "weekday": "<day>?", "time": "HH:MM?", "text": "<what to send>"}}

You are joining a live voice call with the people above. You hear everyone \
and everyone hears you when you speak. There is no text channel into the \
call: to say something, say it.\
"""
