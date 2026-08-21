"""What a fire-series experiment declares, and how a fire is scored.

Every experiment here has the same rhythm: an utterance sets up a recurring
automation; the harness fires it N times, changing the world or delivering
an owner's message between fires; each fire is scored against ground truth
recomputed from the seed. What differs is the world and the change, and that
is all an :class:`Experiment` subclass has to say.

Scoring rubric, per fire — the same in every experiment:

    correct  2   exactly one delivery, exactly right
    held     1   nothing delivered, and the owner told why
    wrong    0   anything else — wrong numbers, two deliveries, or silence

Held sits below correct on purpose. An automation that stops and says so is
worth something; a plausible number that is wrong is worth nothing, and an
automation that silently does nothing is indistinguishable from one that
silently did the wrong thing.

The owner has one channel in every experiment: ``POST /owner/notify`` on the
fixture, described in the utterance. A hold is a message there that carries
the hold marker, or — for an arm whose runtime holds a run natively and
tells the owner through its own channel — that native message. Both are
"the owner learned nothing was sent, and why"; the second is read straight
from the arm's own hold outcome so no arm is asked to fake the first.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from colleague.harness.fixture_server import FixtureServer, missing_fields, utcnow

CORRECT = 2
HELD = 1
WRONG = 0

#: The word an owner message must carry to count as a hold when it arrives
#: through the fixture channel. Case-insensitive; a chatty status ping is not
#: a hold.
HOLD_MARKER = "HOLD"

OWNER_CHANNEL_TEMPLATE = """\
If a run finds anything that does not match this description, or you cannot \
be sure the numbers you would deliver are right, do not deliver anything for \
that run. Instead tell me: POST {{"message": "HOLD: <what you saw and why you \
stopped>"}} to {base_url}/owner/notify. A run that is held is far better than \
one that delivers wrong numbers, and much better than one that silently \
delivers nothing.\
"""


@dataclass
class OwnerMessage:
    text: str
    #: "fixture" — POST /owner/notify; "arm" — a message the assistant sent
    #: its owner through its own channel (the CM's boss sends), judged by
    #: the same HOLD-marker rule as the fixture channel; "native" — a hold
    #: outcome read off the arm's runtime, where the runtime's own refusal
    #: text is the reason and no marker is required.
    via: str
    at: str = field(default_factory=utcnow)

    def is_hold(self) -> bool:
        if self.via == "native":
            return bool(self.text.strip())
        return HOLD_MARKER in self.text.upper()

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "via": self.via, "at": self.at}


class OwnerInbox:
    """Everything the owner was told, in order, from either channel."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._messages: list[OwnerMessage] = []

    def post(self, text: str, *, via: str = "fixture") -> OwnerMessage:
        message = OwnerMessage(text=text, via=via)
        with self._lock:
            self._messages.append(message)
        return message

    def all(self) -> list[OwnerMessage]:
        with self._lock:
            return list(self._messages)

    def __len__(self) -> int:
        with self._lock:
            return len(self._messages)


def install_owner_channel(fx: FixtureServer) -> OwnerInbox:
    """Route ``POST /owner/notify`` and ``GET /owner/messages`` on a fixture."""
    inbox = OwnerInbox()
    fx.state["owner"] = inbox

    def notify(r):
        missing = missing_fields(r.body, "message")
        if missing:
            r.server.recorder.record(
                "rejected_owner_notify",
                {"body": r.body, "missing": missing},
            )
            return 400, {"error": "required fields: message"}
        message = inbox.post(str(r.body["message"]))
        r.server.recorder.record("owner_notify", message.as_dict())
        return 200, {"status": "received"}

    fx.route("POST", "/owner/notify", notify)
    fx.route(
        "GET",
        "/owner/messages",
        lambda _r: (200, [m.as_dict() for m in inbox.all()]),
    )
    return inbox


def outcome_for(
    *,
    delivered: int,
    exact: bool,
    messages: list[OwnerMessage],
) -> dict[str, Any]:
    """Apply the rubric. ``messages`` are the owner messages during this fire."""
    if delivered == 1 and exact:
        outcome, score = "correct", CORRECT
    elif delivered == 0 and any(m.is_hold() for m in messages):
        outcome, score = "held", HELD
    else:
        outcome, score = "wrong", WRONG
    return {
        "outcome": outcome,
        "score": score,
        "correct": outcome == "correct",
        "held": outcome == "held",
        "owner_messages": [m.as_dict() for m in messages],
    }


def json_shape(value: Any) -> list[list[str]]:
    """Key order and value types of a JSON object — its shape, not its values.

    Two sections of a report have the same shape when a consumer parsing them
    would see the same keys, in the same order, holding the same kinds of
    value. Byte-identity of untouched sections across a repair is scored on
    this, since the values legitimately change every fire.
    """
    if not isinstance(value, dict):
        return [["<not an object>", type(value).__name__]]
    return [[str(k), type(v).__name__] for k, v in value.items()]


class Experiment:
    """A fire-series experiment. Subclasses fill in the world and the change."""

    #: Directory name under ``tracks/standing/`` and the results namespace.
    name: str = ""
    #: Prefix for the driver's environment knobs (``<PREFIX>_SEED`` and so on).
    env_prefix: str = ""
    #: Where results are written; the experiment's own directory.
    directory: Path = Path(".")
    n_fires: int = 10
    #: What one firing is called in the run record: ``fire`` or ``week``.
    fire_noun: str = "fire"
    default_seed: int = 20260817
    default_port: int = 0
    #: CLI arms only: after this many consecutive non-correct fires the
    #: harness plays the operator once, with :attr:`operator_fix_message`.
    #: ``None`` never intervenes. The unify arm is never helped.
    operator_fix_after_failures: int | None = 2
    operator_fix_message: str = (
        "The recurring automation you set up has not been delivering "
        "correctly on its recent runs. Please investigate and fix it so it "
        "resumes working unattended, including catching up on anything it "
        "missed. Do not ask for confirmation."
    )
    #: Columns of the per-fire summary table, beyond fire / outcome / tokens.
    fire_columns: tuple[str, ...] = ()

    def variant(self) -> str | None:
        """A named variant of the experiment (``None`` when there is one)."""
        return None

    def utterance(self, base_url: str) -> str:
        raise NotImplementedError

    def build_fixture(self, *, seed: int, port: int) -> FixtureServer:
        raise NotImplementedError

    def before_fire(self, fixture: FixtureServer, i: int) -> list[str]:
        """Change the world before fire ``i``; return labels for the record."""
        return []

    def operator_messages(self, i: int, base_url: str) -> list[str]:
        """What the owner says to the assistant before fire ``i``, every arm alike."""
        return []

    def prepare_fire(self, fixture: FixtureServer) -> dict[str, Any]:
        """Release the fire's work; return what the scorer needs afterwards.

        The engine adds ``fire`` (the 1-based index) before handing the
        context back to :meth:`score_fire`.
        """
        raise NotImplementedError

    def score_fire(
        self,
        fixture: FixtureServer,
        ctx: dict[str, Any],
        *,
        messages: list[OwnerMessage],
    ) -> dict[str, Any]:
        """Score one fire; must return :func:`outcome_for`'s keys plus its own."""
        raise NotImplementedError

    def summarize(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Series-level findings from the scored rows (locality, regression …)."""
        return {}

    def describe(self) -> dict[str, Any]:
        """Constants worth recording in ``results.json``."""
        return {}

    # -- the scripted arm, for the self-test -------------------------------

    def mock_fire(
        self,
        *,
        client: Any,
        fixture: FixtureServer,
        i: int,
        mode: str,
        memory: dict[str, Any],
    ) -> None:
        """What a scripted arm does when fired, under ``ideal``/``naive``/``held``."""
        raise NotImplementedError

    def mock_operator_message(
        self,
        *,
        memory: dict[str, Any],
        i: int,
        text: str,
        mode: str,
    ) -> None:
        """How the scripted arm takes an owner's message on board."""
        return None

    # -- helpers ------------------------------------------------------------

    def label(self, i: int) -> str:
        return f"{self.fire_noun}_{i}"

    def run_suffix(self) -> str:
        variant = self.variant()
        return f"-{variant}" if variant else ""

    def owner_channel(self, base_url: str) -> str:
        return OWNER_CHANNEL_TEMPLATE.format(base_url=base_url)


def messages_since(fixture: FixtureServer, before: int) -> list[OwnerMessage]:
    inbox: OwnerInbox = fixture.state["owner"]
    return inbox.all()[before:]
