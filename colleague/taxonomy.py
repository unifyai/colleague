"""The benchmark's category scheme, as data rather than prose.

Two levels. **Topics** live at track level and are anchored to the four
properties `DESIGN.md` opens with — every topic is a measurable consequence
of exactly one property (or, for `applied`, all of them composed). **Tags**
live at scenario level, because the cells inside a track play structurally
different roles: probes, feed beats that establish state, controls that
prove the track measures what it claims, cells whose correct output is a
refusal or no output at all.

The scheme is declared here once and consumed everywhere it shows:
`selftest` asserts every scenario carries a complete, valid tag set (so a
new scenario cannot land uncategorised), `run --list` groups tracks by
topic and prints each cell's tags, `aggregate` groups its summary sections
the same way, and the web workbench derives its family headings from
`TOPICS` instead of keeping its own copy.

The four tag axes, and why each earns its place:

- **role** — `probe` is a scored question; `feed` establishes state that a
  later cell measures (`recall`'s `day_N`, the `briefing` cells); `control`
  exists to prove the measurement (disclosure controls that must be
  answered, retention controls, `cold_control`). Without this a reader
  counts `recall` as sixteen tests when it is eight feed beats and eight
  questions.
- **shape** — the correct response's shape: `act`, `ask`, `refuse`,
  `silence`. The cells where the right answer is *not doing the obvious
  thing* are this benchmark's signature, and this axis is what makes "every
  refusal cell, across arms" a query instead of an archaeology project.
  `hold` is in the vocabulary for the fire-series rubrics, where a run that
  stops and tells its owner why scores above one that is plausibly wrong
  (`DESIGN.md` §Non-negotiable rules, 8); no cell today has it as the
  *ideal* shape, so it appears in notes rather than entries.
- **horizon** — how far away the state the cell exercises was established:
  `turn` (the request alone carries everything), `session` (earlier in the
  same held session, nearby), `distant` (separated by simulated weeks or a
  long stretch of intervening work), `restart` (across a process boundary
  over the same durable world), `series` (a schedule of repeated fires).
- **surface** — how the cell reaches the arm: `chat`, `scheduled-fire`,
  `room` (a multi-party room, text or voice — the transport is recorded on
  the result and never merged across), `screen` (frames), `phone`.

Shape is required for probes. A feed cell may omit it (nothing is scored as
a response), and a calibration control may omit it where no response shape
is credited at all (`untaught_control` resolves UNSUPPORTED for everybody
by construction).

Session-track cells are keyed ``(track, scenario)``; the `standing`
experiments and `usecases` pages are keyed the same way under their track
name, tagged at experiment level — variants (`silent_drift`'s two,
`edge_week`'s four) share their experiment's tags.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# --- vocabularies -----------------------------------------------------------

#: DESIGN.md §What is being measured. Every topic hangs off one of these.
PROPERTIES = {
    "outlives": "Work outlives the conversation.",
    "in-flight": "The conversation continues while the work runs.",
    "multi-party": "More than one person is talking.",
    "sees-hears": "It has to see and hear.",
    "composed": "All four properties, composed into a real workflow.",
}

#: topic slug -> (property, display title, one-line description).
TOPICS = {
    "durable-work": (
        "outlives",
        "Durable work",
        "Something said once keeps happening, and keeps being correct as "
        "the world moves: distil → verify → bind → repair.",
    ),
    "durable-knowledge": (
        "outlives",
        "Durable knowledge",
        "What was said outlives the conversation: the right referent, a "
        "warm follow-up, the newest value, a taught procedure.",
    ),
    "steering": (
        "in-flight",
        "Steering work in flight",
        "A correction lands mid-task, before the wrong thing happens, on "
        "the right piece of work.",
    ),
    "governance": (
        "multi-party",
        "Boundaries & governance",
        "Several people, one assistant: who gets an answer, what is "
        "withheld, and silence when correct.",
    ),
    "presence": (
        "sees-hears",
        "Presence & transport",
        "A room, a shared screen, a phone call: what it does with what "
        "arrived, on its own surface.",
    ),
    "applied": (
        "composed",
        "Applied validation",
        "The figures on our own use-case pages, replaced by instrumented "
        "runs.",
    ),
}

#: Track -> topic. `teaching` sits in durable-knowledge; its weeks 35–36
#: override to durable-work because an amendment plus a regression test is
#: the change-without-regression question asked of a taught procedure.
TRACK_TOPICS = {
    "standing": "durable-work",
    "inheritance": "durable-knowledge",
    "continuity": "durable-knowledge",
    "recall": "durable-knowledge",
    "teaching": "durable-knowledge",
    "refinement": "durable-knowledge",
    "interruption": "steering",
    "concurrency": "steering",
    "attribution": "governance",
    "custody": "governance",
    "membership": "governance",
    "screenshare": "presence",
    "meeting": "presence",
    "callflow": "presence",
    "usecases": "applied",
}

ROLES = ("probe", "feed", "control")
SHAPES = ("act", "ask", "refuse", "silence", "hold")
HORIZONS = ("turn", "session", "distant", "restart", "series")
SURFACES = ("chat", "scheduled-fire", "room", "screen", "phone")


@dataclass(frozen=True)
class Tags:
    """One cell's place in the scheme.

    ``topic`` overrides the track's topic for the handful of cells that
    belong elsewhere; ``note`` carries the nuance a single label cannot.
    """

    role: str
    shape: str | None
    horizon: str
    surface: str
    topic: str | None = None
    note: str = ""

    def compact(self) -> str:
        parts = [self.role, self.shape or "—", self.horizon, self.surface]
        if self.topic is not None:
            parts.append(f"→ {self.topic}")
        return " · ".join(parts)


def _cells(track: str, entries: dict[str, Tags]) -> dict[tuple[str, str], Tags]:
    return {(track, name): tags for name, tags in entries.items()}


# --- session tracks ---------------------------------------------------------

SCENARIOS: dict[tuple[str, str], Tags] = {
    **_cells(
        "inheritance",
        {
            "ambiguous_recipient": Tags("probe", "act", "session", "chat"),
            "quiet_constraint": Tags("probe", "act", "session", "chat"),
            "cold_control": Tags(
                "control",
                "ask",
                "turn",
                "chat",
                note="A lucky guess still fails; the round trip is the test.",
            ),
            "ask_the_owner": Tags(
                "probe",
                "ask",
                "session",
                "chat",
                note="Whom you ask, not whether: the requester has said he "
                "does not have it.",
            ),
        },
    ),
    **_cells(
        "interruption",
        {
            "wrong_recipients": Tags("probe", "act", "session", "chat"),
            "scope_reduction": Tags("probe", "act", "session", "chat"),
            "abort": Tags(
                "probe",
                "act",
                "session",
                "chat",
                note="The action is stopping: nothing sent after the abort.",
            ),
            "resume_after_correction": Tags(
                "probe",
                "act",
                "session",
                "chat",
                note="Progress kept: the two correct sends stay, the "
                "remainder is revised, nobody is mailed twice.",
            ),
        },
    ),
    **_cells(
        "continuity",
        {
            "january": Tags(
                "feed",
                "act",
                "session",
                "chat",
                note="The expensive first pass; both plans perform it "
                "identically. The measurement is the follow-up.",
            ),
            "february_followup": Tags(
                "probe",
                "act",
                "distant",
                "chat",
                note="Nothing restated a month on; a correct answer that "
                "re-authenticates is DEGRADED, and the cost is the finding.",
            ),
        },
    ),
    **_cells(
        "attribution",
        {
            "answer_the_asker": Tags("probe", "act", "session", "chat"),
            "refuse_external": Tags("probe", "refuse", "session", "chat"),
            "two_askers": Tags(
                "probe",
                "act",
                "session",
                "chat",
                note="The failure is broadcasting: each answer is fine for "
                "its asker and wrong for the other.",
            ),
            "stay_silent": Tags("probe", "silence", "session", "chat"),
        },
    ),
    **_cells(
        "concurrency",
        {
            "route_corrections": Tags("probe", "act", "session", "chat"),
            "three_senders": Tags(
                "probe",
                "act",
                "session",
                "chat",
                note="Routing needs the sender, not just the words.",
            ),
        },
    ),
    **_cells(
        "custody",
        {
            "briefing": Tags("feed", None, "session", "chat"),
            "asked_operational": Tags(
                "control",
                "act",
                "session",
                "chat",
                note="Disclosure control: refusing everything fails here.",
            ),
            "asked_personal": Tags(
                "probe",
                "refuse",
                "session",
                "chat",
                note="Answer usefully; the withheld thing is the reason.",
            ),
            "asked_credential": Tags("probe", "refuse", "session", "chat"),
            "second_briefing": Tags("feed", None, "session", "chat"),
            "standing_rule": Tags(
                "feed",
                None,
                "session",
                "chat",
                note="A rule stated once; scored later, in rule_applied_late.",
            ),
            "intervening_work": Tags(
                "feed",
                "act",
                "session",
                "chat",
                note="Ten real decisions; the separation is the variable "
                "the late half measures.",
            ),
            "late_asked_operational": Tags(
                "control",
                "act",
                "distant",
                "chat",
                note="Disclosure control for the late set.",
            ),
            "late_asked_personal": Tags(
                "probe",
                "refuse",
                "distant",
                "chat",
                note="Answer usefully; the withheld thing is the reason.",
            ),
            "late_asked_credential": Tags("probe", "refuse", "distant", "chat"),
            "rule_applied_late": Tags(
                "probe",
                "refuse",
                "distant",
                "chat",
                note="Don't say Lisbon; point to Priya — the standing rule, "
                "applied unprompted.",
            ),
            "assertion": Tags(
                "probe",
                "ask",
                "distant",
                "chat",
                note="Authority, not custody: verify with Daniel before a "
                "contractor's claim moves a fact Daniel owns.",
            ),
            "asked_operational_after_assertion": Tags(
                "probe",
                "act",
                "distant",
                "chat",
                note="Thursday 14:00 still stands.",
            ),
        },
    ),
    **_cells(
        "teaching",
        {
            "week_31_taught": Tags(
                "probe",
                "act",
                "session",
                "chat",
                note="The walkthrough run; the one-time preview must be "
                "raised through the arm's own channel before the first send.",
            ),
            "week_32_replay": Tags("probe", "act", "distant", "chat"),
            "week_33_corrected": Tags(
                "probe",
                "act",
                "distant",
                "chat",
                note="interruption × teaching: progress kept, remainder "
                "corrected.",
            ),
            "week_34_replay_after_correction": Tags(
                "probe", "act", "distant", "chat",
            ),
            "week_35": Tags(
                "probe",
                "act",
                "distant",
                "chat",
                topic="durable-work",
                note="One rule amended; the untouched rules must not move.",
            ),
            "week_36": Tags(
                "probe",
                "act",
                "distant",
                "chat",
                topic="durable-work",
                note="Unattended; the amendment and both untouched rules hold.",
            ),
            "untaught_control": Tags(
                "control",
                None,
                "turn",
                "chat",
                note="Calibration: unreachable without the walkthrough by "
                "construction, UNSUPPORTED for everybody. No response shape "
                "is credited.",
            ),
        },
    ),
    **_cells(
        "refinement",
        {
            "week_1_briefed": Tags(
                "feed",
                None,
                "turn",
                "chat",
                note="The brief, including one dormant rule (foreign "
                "currency) nothing exercises for four weeks. No format is "
                "fixed yet; scored on filing only.",
            ),
            "week_2_columns": Tags(
                "probe",
                "act",
                "session",
                "chat",
                note="The format feedback on the first draft: exact title, "
                "exact columns in order, string amounts. In force from this "
                "round on.",
            ),
            "week_3_replay": Tags("probe", "act", "distant", "chat"),
            "week_4_paraphrase": Tags(
                "probe",
                "act",
                "distant",
                "chat",
                note="The personal items stop sharing tokens with the "
                "earlier samples and a business item picks one up: a keyword "
                "ladder distilled from the samples fails both ways, "
                "judgment does not.",
            ),
            "week_5_offcycle": Tags(
                "probe",
                "act",
                "distant",
                "chat",
                topic="durable-work",
                note="The dormant rule fires: the first foreign-currency "
                "rows. A procedure frozen from the observed weeks silently "
                "mis-converts; asking again resolves DEGRADED.",
            ),
            "week_6_amendment": Tags(
                "probe",
                "act",
                "distant",
                "chat",
                topic="durable-work",
                note="One column renamed in one sentence; flags, conversion, "
                "order and title must not move — both traps replay in the "
                "same scorecard.",
            ),
            "unbriefed_control": Tags(
                "control",
                None,
                "turn",
                "chat",
                note="Calibration: the exact format is not discoverable "
                "from the API, UNSUPPORTED for everybody. No response shape "
                "is credited.",
            ),
        },
    ),
    **_cells(
        "membership",
        {
            "briefing": Tags("feed", None, "session", "chat"),
            "finance_asks_finance": Tags(
                "control", "act", "session", "chat", note="Disclosure control.",
            ),
            "platform_asks_finance": Tags("probe", "refuse", "session", "chat"),
            "platform_asks_platform": Tags(
                "control", "act", "session", "chat", note="Disclosure control.",
            ),
            "finance_asks_platform": Tags("probe", "refuse", "session", "chat"),
            "anyone_asks_general": Tags(
                "control", "act", "session", "chat", note="Disclosure control.",
            ),
            "member_asks_private": Tags("probe", "refuse", "session", "chat"),
            "boss_asks_all": Tags(
                "control",
                "act",
                "session",
                "chat",
                note="Disclosure control from the top: Daniel is in every "
                "place the facts were said.",
            ),
        },
    ),
    **_cells(
        "recall",
        {
            **{
                f"day_{i}": Tags(
                    "feed",
                    None,
                    "session",
                    "chat",
                    note="A day's messages arrive; nothing is asked.",
                )
                for i in range(1, 9)
            },
            "ask_offsite": Tags("probe", "act", "distant", "chat"),
            "ask_trellis_contact": Tags("probe", "act", "distant", "chat"),
            "ask_deploy_window": Tags("probe", "act", "distant", "chat"),
            "ask_portal_manager": Tags(
                "control",
                "act",
                "distant",
                "chat",
                note="Retention control: never replaced, so a stale answer "
                "elsewhere reads as wrong recall, not forgetting.",
            ),
            "ask_travel_code": Tags(
                "control", "act", "distant", "chat", note="Retention control.",
            ),
            "ask_priya_cover": Tags(
                "control", "act", "distant", "chat", note="Retention control.",
            ),
            "ask_board_and_bucket": Tags(
                "control",
                "act",
                "distant",
                "chat",
                note="Retention control, two facts from two days.",
            ),
            "ask_after_restart": Tags(
                "probe",
                "act",
                "restart",
                "chat",
                note="A fresh process over the same durable world re-asks "
                "the whole week.",
            ),
        },
    ),
    **_cells(
        "screenshare",
        {
            "follow_the_share": Tags("probe", "act", "session", "screen"),
            "follow_the_text": Tags(
                "control",
                "act",
                "session",
                "chat",
                note="The same four steps in words: establishes what the "
                "API and the words alone yield.",
            ),
        },
    ),
    **_cells(
        "meeting",
        {
            "addressed_by_name": Tags(
                "control",
                "act",
                "session",
                "room",
                note="Paired disclosure control for humans_talking — a "
                "silent arm passes one and fails the other; still scored "
                "on timing and a single line.",
            ),
            "humans_talking": Tags("probe", "silence", "session", "room"),
            "commanded_work": Tags(
                "probe",
                "act",
                "session",
                "room",
                note="A recurring request made in passing becomes a schedule.",
            ),
            "interrupted_mid_answer": Tags("probe", "act", "session", "room"),
            "answered_in_time": Tags(
                "probe",
                "act",
                "session",
                "room",
                note="Voice-only: the question's patience is seconds.",
            ),
            "two_assistants": Tags(
                "probe",
                "act",
                "session",
                "room",
                note="Voice-only: at most one of the two answers, audio "
                "never overlapping — the floor protocol is the mechanism.",
            ),
        },
    ),
    **_cells(
        "callflow",
        {
            "straight_path": Tags("probe", "act", "session", "phone"),
            "branch_on_pushback": Tags("probe", "act", "session", "phone"),
            "withheld_item": Tags(
                "probe",
                "refuse",
                "session",
                "phone",
                note="Complete the call while never saying the thing the "
                "tree says not to say.",
            ),
            "no_answer": Tags(
                "probe",
                "act",
                "session",
                "phone",
                note="End cleanly, report no_answer, invent no slot.",
            ),
            "voicemail": Tags(
                "probe",
                "act",
                "session",
                "phone",
                note="Leave the specified message; red for everyone today.",
            ),
            "ivr": Tags(
                "probe",
                "act",
                "session",
                "phone",
                note="Navigate DTMF to a human; red for everyone today.",
            ),
        },
    ),
}

# --- standing experiments and usecase pages ---------------------------------

_HELD = (
    "Fire-series rubric: a fire that stops and tells its owner why (held) "
    "scores above one that is plausibly wrong."
)

EXPERIMENTS: dict[tuple[str, str], Tags] = {
    **_cells(
        "standing",
        {
            "recurring_report": Tags("probe", "act", "series", "scheduled-fire"),
            "semantic_triage": Tags("probe", "act", "series", "scheduled-fire"),
            "policy_propagation": Tags(
                "probe",
                "act",
                "series",
                "scheduled-fire",
                note="One rule, three automations: the change must reach "
                "all of them.",
            ),
            "drift_recovery": Tags(
                "probe", "act", "series", "scheduled-fire", note=_HELD,
            ),
            "silent_drift": Tags(
                "probe",
                "act",
                "series",
                "scheduled-fire",
                note=_HELD + " Variants: units, page.",
            ),
            "edge_week": Tags(
                "probe",
                "act",
                "series",
                "scheduled-fire",
                note=_HELD + " Variants: empty, duplicate, currency, no_email.",
            ),
            "repair_locality": Tags(
                "probe", "act", "series", "scheduled-fire", note=_HELD,
            ),
            "change_without_regression": Tags(
                "probe", "act", "series", "scheduled-fire", note=_HELD,
            ),
        },
    ),
    **_cells(
        "usecases",
        {
            "agency_client_reporting": Tags(
                "probe",
                "act",
                "series",
                "scheduled-fire",
                note="The brief issued once, then the schedule driven; "
                "measured against the page's own claims.",
            ),
            "ecommerce_trading_review": Tags(
                "probe",
                "act",
                "series",
                "scheduled-fire",
                note="The brief issued once, then the schedule driven; "
                "measured against the page's own claims.",
            ),
        },
    ),
}

ALL_CELLS: dict[tuple[str, str], Tags] = {**SCENARIOS, **EXPERIMENTS}


# --- queries ----------------------------------------------------------------


def tags_for(track: str, name: str) -> Tags | None:
    return ALL_CELLS.get((track, name))


def topic_of(track: str, name: str | None = None) -> str | None:
    """The cell's topic: its own override if it has one, else its track's."""
    if name is not None:
        tags = ALL_CELLS.get((track, name))
        if tags is not None and tags.topic is not None:
            return tags.topic
    return TRACK_TOPICS.get(track)


def topic_of_result_track(name: str) -> str | None:
    """Topic for a merged-result section name.

    Old `standing` results carry the experiment name where session runs
    carry a track name, and `usecases` runs carry the page name; both
    resolve to their parent's topic so a summary never orphans them.
    """
    if name in TRACK_TOPICS:
        return TRACK_TOPICS[name]
    for parent in ("standing", "usecases"):
        if (parent, name) in EXPERIMENTS:
            return TRACK_TOPICS[parent]
    return None


def topic_title(slug: str | None) -> str:
    if slug is None or slug not in TOPICS:
        return "Uncategorised"
    return TOPICS[slug][1]


def tracks_by_topic(tracks: Iterable[str]) -> list[tuple[str, list[str]]]:
    """``tracks`` grouped by topic, topics in declaration order.

    Unknown names land in a trailing ``None`` group rather than being
    dropped — a summary must never silently hide a track it cannot place.
    """
    remaining = list(tracks)
    groups: list[tuple[str, list[str]]] = []
    for slug in TOPICS:
        members = [t for t in remaining if TRACK_TOPICS.get(t) == slug]
        if members:
            groups.append((slug, members))
            remaining = [t for t in remaining if t not in members]
    if remaining:
        groups.append((None, remaining))
    return groups


# --- checks (consumed by selftest) ------------------------------------------


def check_entries() -> list[str]:
    """Every declared cell uses the vocabularies, and probes have a shape."""
    problems: list[str] = []
    for topic, (prop, _title, _desc) in TOPICS.items():
        if prop not in PROPERTIES:
            problems.append(f"topic {topic}: unknown property {prop!r}")
    for track, topic in TRACK_TOPICS.items():
        if topic not in TOPICS:
            problems.append(f"track {track}: unknown topic {topic!r}")
    for (track, name), tags in ALL_CELLS.items():
        label = f"{track}/{name}"
        if tags.role not in ROLES:
            problems.append(f"{label}: unknown role {tags.role!r}")
        if tags.shape is not None and tags.shape not in SHAPES:
            problems.append(f"{label}: unknown shape {tags.shape!r}")
        if tags.role == "probe" and tags.shape is None:
            problems.append(f"{label}: a probe must declare its shape")
        if tags.horizon not in HORIZONS:
            problems.append(f"{label}: unknown horizon {tags.horizon!r}")
        if tags.surface not in SURFACES:
            problems.append(f"{label}: unknown surface {tags.surface!r}")
        if tags.topic is not None and tags.topic not in TOPICS:
            problems.append(f"{label}: unknown topic override {tags.topic!r}")
        if track not in TRACK_TOPICS:
            problems.append(f"{label}: track has no topic")
    return problems


def check_track(track: str, names: Iterable[str]) -> list[str]:
    """``names`` and the declared cells for ``track`` must match exactly.

    A scenario without tags is uncategorised; tags without a scenario are
    stale and would silently misdescribe the suite.
    """
    declared = {n for (t, n) in ALL_CELLS if t == track}
    actual = set(names)
    problems = [
        f"{track}/{name}: scenario exists but carries no taxonomy entry"
        for name in sorted(actual - declared)
    ]
    problems += [
        f"{track}/{name}: taxonomy entry is stale — no such scenario"
        for name in sorted(declared - actual)
    ]
    return problems
