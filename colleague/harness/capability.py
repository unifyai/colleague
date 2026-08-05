"""What each arm can and cannot express, declared up front.

Several tracks probe capabilities that some harnesses simply do not have. A
harness with no running loop cannot receive a mid-task correction; a harness
with one flat memory directory cannot scope a fact to a subset of readers.
Recording those as a score of zero would be dishonest — zero is what you get
for trying and failing, and these arms are not trying.

So an arm declares its mechanisms, and a scenario that needs a mechanism the
arm lacks resolves to ``UNSUPPORTED``. That is reported as its own column,
never averaged into an accuracy figure, and never presented as a loss. The
`standing` track already did this by hand for OpenCode's policy propagation
("not reachable"); this makes it a first-class outcome instead.

The distinction that matters in reporting:

    PASS         the arm did the right thing
    FAIL         the arm had the mechanism and still got it wrong
    UNSUPPORTED  the arm has no mechanism for this at all
    DEGRADED     the arm reached the outcome through a materially worse
                 route (a restart rather than a redirect, say) — correct,
                 but the cost belongs in the write-up
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Outcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNSUPPORTED = "unsupported"
    DEGRADED = "degraded"

    ERROR = "error"
    """The harness could not measure — a bad credential, a crash, a timeout.

    Distinct from FAIL, which means the arm had its chance and got it wrong.
    Collapsing the two lets a broken sweep read as a arm that performed
    badly, which is the most expensive kind of wrong answer a benchmark can
    give: it looks like a finding. An ERROR anywhere fails the run.
    """

    @property
    def scoreable(self) -> bool:
        """Whether this outcome belongs in an accuracy denominator."""
        return self in (Outcome.PASS, Outcome.FAIL, Outcome.DEGRADED)

    @property
    def credited(self) -> bool:
        """Whether this outcome counts as the scenario having been achieved."""
        return self in (Outcome.PASS, Outcome.DEGRADED)


class Steering(str, Enum):
    """How a correction can reach work that is already running."""

    LIVE_INTERJECT = "live_interject"
    """The running loop accepts a message mid-flight and adapts in place."""

    QUEUED_FOLLOWUP = "queued_followup"
    """The correction is delivered as a new turn once the current one ends."""

    RESTART_ONLY = "restart_only"
    """The only way to change course is to abandon the run and start over."""

    NONE = "none"
    """No mechanism at all: the work runs to completion unobserved."""


class Storage(str, Enum):
    """How learned knowledge can be scoped once it is written down."""

    SCOPED = "scoped"
    """Facts can be filed where only some readers can reach them."""

    FLAT = "flat"
    """One store; anything written is readable by anyone who runs the agent."""

    NONE = "none"


@dataclass(frozen=True)
class ArmProfile:
    """The mechanisms an arm brings to the multi-party tracks.

    These are properties of the harness, not of the model. They are declared
    here rather than discovered at runtime so that a scenario can decide
    up front whether it is even applicable, and so a reader can check the
    claim against the arm's own documentation.
    """

    name: str
    steering: Steering
    storage: Storage
    persistent_sessions: bool
    """Whether a finished task can be resumed with its working state intact."""

    multi_party: bool
    """Whether the harness models more than one human correspondent."""

    clarification: bool
    """Whether the harness can ask the user a question and *block* on it.

    The distinction that matters is blocking. Any arm can emit a question;
    the capability is suspending the work until an answer arrives, so the
    task resumes with it rather than proceeding on a guess.

    A fixture must never provide this. An earlier version of `inheritance`
    exposed a `/clarify` HTTP endpoint, which handed a fake mechanism to arms
    that have none and steered the one arm that has a real one away from it —
    a task description that names an endpoint gets that endpoint called from
    code, and code cannot wait for a person. It measured who used the stub.
    """

    accepts_images: bool
    """Whether image content can reach the arm through its normal input path."""

    scheduler: bool
    notes: str = ""

    def supports(self, requirement: str) -> bool:
        return bool(getattr(self, requirement, False))


#: Declared from each harness's own documented capabilities. Where a claim is
#: contestable it is stated in ``notes`` so a reader can check it rather than
#: take it on trust.
PROFILES: dict[str, ArmProfile] = {
    "unify": ArmProfile(
        name="unify",
        clarification=True,
        steering=Steering.LIVE_INTERJECT,
        storage=Storage.SCOPED,
        persistent_sessions=True,
        multi_party=True,
        accepts_images=True,
        scheduler=True,
        notes=(
            "ConversationManager holds per-action interject/ask/pause/stop "
            "tools; inner loops race generation against the interjection "
            "queue. Knowledge is written to typed contexts that carry scope."
        ),
    ),
    "hermes": ArmProfile(
        name="hermes",
        clarification=False,
        steering=Steering.RESTART_ONLY,
        storage=Storage.FLAT,
        persistent_sessions=True,
        multi_party=False,
        accepts_images=False,
        scheduler=True,
        notes=(
            "`hermes chat -Q -q` is one-shot per turn, but sessions persist "
            "to SQLite and `--resume <id>` continues one — a documented "
            "automation pattern the adapter now uses for continuations. "
            "Still no mid-run address and no clarify channel headless; a "
            "converged automation is a no_agent cron script with no loop to "
            "address. Skills live in one directory readable by whoever runs "
            "the agent."
        ),
    ),
    "hermes-tui": ArmProfile(
        name="hermes-tui",
        clarification=True,
        steering=Steering.LIVE_INTERJECT,
        storage=Storage.FLAT,
        persistent_sessions=True,
        multi_party=False,
        accepts_images=False,
        scheduler=True,
        notes=(
            "The TUI gateway JSON-RPC surface (`python -m tui_gateway.entry`),"
            " documented by hermes as a public integration protocol. "
            "prompt.submit returns at status=streaming; session.steer injects "
            "into the running tool batch and session.redirect replaces the "
            "in-flight model call; clarify.request/clarify.respond is a real "
            "blocking question channel; session.resume/branch continue the "
            "same SQLite sessions the CLI writes. Senders are still text in "
            "one session — multi-person identity is a messaging-gateway "
            "capability this surface does not carry."
        ),
    ),
    "openclaw": ArmProfile(
        name="openclaw",
        clarification=False,
        steering=Steering.QUEUED_FOLLOWUP,
        storage=Storage.FLAT,
        persistent_sessions=True,
        multi_party=False,
        accepts_images=True,
        scheduler=True,
        notes=(
            "Sessions persist and accept further turns, so a correction "
            "lands as the next turn rather than inside the running one."
        ),
    ),
    "unify-cm": ArmProfile(
        name="unify-cm",
        clarification=True,
        steering=Steering.LIVE_INTERJECT,
        storage=Storage.SCOPED,
        persistent_sessions=True,
        multi_party=True,
        accepts_images=True,
        scheduler=True,
        notes=(
            "The ConversationManager surface — DESIGN.md's 'faithful surface "
            "for these tracks'. Senders are first-class contacts on every "
            "inbound event; replies are Sent events addressed to a contact; "
            "silence is the `wait` tool, detected exactly; each in-flight "
            "action exposes its own interject/stop/ask tools and routing a "
            "correction to the right one is a recorded brain decision. Adds "
            "a slow-brain model axis the plain `act` arm never had."
        ),
    ),
    "opencode": ArmProfile(
        name="opencode",
        clarification=False,
        steering=Steering.RESTART_ONLY,
        storage=Storage.FLAT,
        persistent_sessions=False,
        multi_party=False,
        accepts_images=True,
        scheduler=False,
        notes=(
            "`opencode run` is one-shot. Workspace files persist between "
            "runs, but no running loop can be addressed."
        ),
    ),
}


@dataclass
class ScenarioResult:
    """One scenario's outcome for one arm."""

    scenario: str
    outcome: Outcome
    detail: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "outcome": self.outcome.value,
            "reason": self.reason,
            **({"detail": self.detail} if self.detail else {}),
        }


def summarize(results: list[ScenarioResult]) -> dict[str, Any]:
    """Aggregate, keeping UNSUPPORTED out of the accuracy denominator."""
    scoreable = [r for r in results if r.outcome.scoreable]
    credited = [r for r in scoreable if r.outcome.credited]
    by_outcome: dict[str, int] = {}
    for r in results:
        by_outcome[r.outcome.value] = by_outcome.get(r.outcome.value, 0) + 1
    return {
        "total_scenarios": len(results),
        "scoreable": len(scoreable),
        "credited": len(credited),
        "accuracy": (round(len(credited) / len(scoreable), 4) if scoreable else None),
        "by_outcome": by_outcome,
        "results": [r.as_dict() for r in results],
    }
