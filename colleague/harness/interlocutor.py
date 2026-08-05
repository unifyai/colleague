"""A second person, talking to the assistant while it works.

Every scripted turn is keyed to a **waypoint** the fixture observes, not to
elapsed time. "Say this once the agent has read the recipient list" is
reproducible; "say this after four seconds" is a race that resolves
differently on a cached run and a live one.

The interlocutor records the fixture's recorder sequence at the moment each
turn was delivered. Scoring then compares that against the sequence of the
side effect under test — so "did the correction arrive before the wrong mail
went out" is answered by two integers, not by reading a log.

Delivery is arm-supplied, because arms differ in what delivery can even mean:
a live interjection into a running loop, a queued turn that lands after the
current one finishes, or nothing at all. The interlocutor does not care which
— it records what happened and lets the scorer interpret it against the arm's
declared profile.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from colleague.harness.capability import ArmProfile, Steering
from colleague.harness.fixture_server import FixtureServer, utcnow


@dataclass
class ScriptedTurn:
    """One thing a participant says, at a point defined by the agent's own progress."""

    label: str
    sender: str
    text: str
    waypoint: str
    nth: int = 1
    timeout: float = 180.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "sender": self.sender,
            "text": self.text,
            "waypoint": self.waypoint,
            "nth": self.nth,
        }


@dataclass
class Delivery:
    turn: ScriptedTurn
    delivered: bool
    mode: str
    """How it reached the arm: live_interject / queued_followup / not_delivered."""

    recorder_seq: int
    """Fixture recorder sequence when the turn was **dispatched**.

    Not when the arm received it. For a live interjection those differ by an
    LLM round trip, and reading this as receipt once produced a scored
    failure against an agent that had correctly reported the correction
    arriving too late to act on.

    Scenarios that depend on the correction being in hand must widen the
    window themselves — hold the response that precedes the irreversible
    step — rather than inferring receipt from this number.
    """

    at: str
    detail: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        out = {
            **self.turn.as_dict(),
            "delivered": self.delivered,
            "mode": self.mode,
            "recorder_seq": self.recorder_seq,
            "at": self.at,
        }
        if self.detail:
            out["detail"] = self.detail
        if self.error:
            out["error"] = self.error
        return out


class Interlocutor:
    """Runs the scripted turns against a live arm, in the background."""

    def __init__(
        self,
        *,
        fixture: FixtureServer,
        profile: ArmProfile,
        turns: list[ScriptedTurn],
        deliver: Callable[[ScriptedTurn], dict[str, Any]],
    ) -> None:
        self.fixture = fixture
        self.profile = profile
        self.turns = turns
        self._deliver = deliver
        self._deliveries: list[Delivery] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _mode(self) -> str:
        return {
            Steering.LIVE_INTERJECT: "live_interject",
            Steering.QUEUED_FOLLOWUP: "queued_followup",
            Steering.RESTART_ONLY: "not_delivered",
            Steering.NONE: "not_delivered",
        }[self.profile.steering]

    def _wait_responsively(self, turn: ScriptedTurn) -> bool:
        """Wait for the waypoint in slices, so stop() is not ignored.

        A single long `wait_for` cannot see `_stop`, so an agent that finished
        without ever reaching the waypoint left this thread blocked for the
        full timeout. `stop()` joined for five seconds, gave up, and the
        journal was returned empty — with no record that the waypoint was
        never reached. The scorer then could not tell "the agent never got
        there" from "no turns were configured", and scored the run as if the
        correction had simply been ignored.
        """
        import time

        deadline = time.monotonic() + turn.timeout
        while time.monotonic() < deadline and not self._stop.is_set():
            if self.fixture.waypoints.wait_for(
                turn.waypoint,
                timeout=0.5,
                nth=turn.nth,
            ):
                return True
        return False

    def _run(self) -> None:
        for turn in self.turns:
            if self._stop.is_set():
                break
            reached = self._wait_responsively(turn)
            if not reached:
                self._append(
                    Delivery(
                        turn=turn,
                        delivered=False,
                        mode=(
                            "stopped_before_waypoint"
                            if self._stop.is_set()
                            else "waypoint_never_reached"
                        ),
                        recorder_seq=self.fixture.recorder.count(),
                        at=utcnow(),
                    ),
                )
                continue

            # The arm's own steering mechanism decides what delivery means.
            # An arm that cannot address a running loop still gets the turn
            # offered, so its driver can record how it chose to cope.
            seq = self.fixture.recorder.count()
            try:
                detail = self._deliver(turn) or {}
                self._append(
                    Delivery(
                        turn=turn,
                        delivered=bool(detail.get("delivered", True)),
                        mode=str(detail.get("mode") or self._mode()),
                        recorder_seq=seq,
                        at=utcnow(),
                        detail={
                            k: v
                            for k, v in detail.items()
                            if k not in {"delivered", "mode"}
                        },
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
                self._append(
                    Delivery(
                        turn=turn,
                        delivered=False,
                        mode="delivery_failed",
                        recorder_seq=seq,
                        at=utcnow(),
                        error=f"{type(exc).__name__}: {exc}",
                    ),
                )

    def _append(self, delivery: Delivery) -> None:
        with self._lock:
            self._deliveries.append(delivery)

    def start(self) -> "Interlocutor":
        self._thread = threading.Thread(
            target=self._run,
            name="interlocutor",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def journal(self) -> list[dict[str, Any]]:
        with self._lock:
            return [d.as_dict() for d in self._deliveries]

    def delivery(self, label: str) -> Delivery | None:
        with self._lock:
            for d in self._deliveries:
                if d.turn.label == label:
                    return d
        return None

    def __enter__(self) -> "Interlocutor":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()
