"""Simulated people who carry a scene themselves.

The interlocutor fires fixed strings at fixture waypoints, which is right
for a correction that must mean exactly one thing. It is wrong for a room:
three people talking, one assistant among them, and no way to script every
branch of what the assistant might say or ask. The system under test is a
model; it will take the conversation somewhere no script anticipated.

So the people are role-players. Each is a `Persona` — a brief, what they
know, how they behave — and the scene is a list of **beats**: the things
that get said, in order, by whom, and whether each is aimed at the
assistant. That order is the deterministic flow. What varies is the wording
(a live role says the beat in its own words, in the context of what has
been said) and the reactions (a live role may answer a question the
assistant puts to it, or push back). Without a model the roles speak their
beats verbatim and never react, which is the controlled version of the same
scene and is what the self-test runs.

Ground truth never lives in a role's head at run time: the facts the
assistant should produce are in the fixture, and the scorer reads what the
fixture witnessed. Timing is recorder sequence, not wall clock: a beat aimed
at the assistant records the sequence at which it was spoken and the
sequence of the next line, so "answered before the moment passed" is two
integers.

Roles are the environment. Their tokens are metered by the persona pool and
never charged to the arm. Repeats, not single runs, are the unit of
measurement for anything a live role touches.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from colleague.harness.fixture_server import FixtureServer, utcnow
from colleague.harness.session import Unsupported


@dataclass(frozen=True)
class Beat:
    """One thing that gets said in the scene, by a named role, in order."""

    who: str
    text: str
    """What is said in controlled mode, and what a live role says in its own words."""

    intent: str = ""
    """Why they say it. Shown to a live role so the rewording keeps the point."""

    to_assistant: bool = False
    """Aimed at the assistant. Starts a patience window and an in-time check."""

    patience: float = 20.0
    """Seconds a role waits for the assistant after an aimed beat before moving on."""

    expect: tuple[str, ...] = ()
    """Markers a correct assistant answer would carry; recorded, not enforced."""


@dataclass
class Scene:
    beats: list[Beat]
    quiet_s: float = 2.0
    """How long the room must have been quiet before the next beat is spoken."""

    settle_s: float = 6.0
    """After the last beat: how long roles keep listening (and reacting, if live)."""

    react: bool = True
    """Whether live roles may answer or push back on what the assistant says."""

    max_reactions_per_role: int = 3


@dataclass
class Said:
    """One line a role produced, with everything the scorer needs to place it."""

    who: str
    text: str
    kind: str
    """``beat`` or ``reaction``."""

    seq: int
    """Fixture recorder sequence at which the line was recorded."""

    at: str
    beat_index: int | None = None
    to_assistant: bool = False
    delivered: bool = True
    mode: str = ""
    """live_interject / queued_followup / pending / not_delivered / resumed_turn / spoken."""

    answered_seq: int | None = None
    """First assistant line recorded after this one, if any."""

    next_seq: int | None = None
    """Sequence of the next role line — the moment after which an answer is late."""

    spoken_at: str | None = None
    """Transport timestamp: when this line's audio began (voice transport only)."""

    ended_at: str | None = None
    """Transport timestamp: when this line's audio finished (voice transport only)."""

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


class RolePlayDirector:
    """Runs a scene against a live arm: roles speak, listen, and react.

    ``deliver(sender, text)`` is the arm's way in — the same as the
    interlocutor's — and may raise `Unsupported`, in which case the line is
    held as *pending* for the runner to feed as a continuation turn once the
    current one ends. That is a queued delivery and is recorded as one.

    ``assistant_kind`` names the recorder kind the fixture uses for the
    assistant's lines into the room (its reply channel), so the director can
    see them without trusting arm instrumentation.
    """

    def __init__(
        self,
        *,
        fixture: FixtureServer,
        scene: Scene,
        deliver: Callable[[str, str], dict[str, Any]],
        assistant_kind: str = "say",
        room_key: str = "room",
    ) -> None:
        self.fixture = fixture
        self.scene = scene
        self._deliver = deliver
        self.assistant_kind = assistant_kind
        self.room_key = room_key
        self._pool = fixture.state.get("personas")
        self._said: list[Said] = []
        self._pending: list[Said] = []
        self._reactions: dict[str, int] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._done = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_room_seq = 0
        self.fixture.state.setdefault(room_key, [])
        self.fixture.state["roleplay_done"] = False

    # ---------------------------------------------------------------- state

    @property
    def live(self) -> bool:
        return bool(self._pool is not None and self._pool.live)

    def _assistant_lines(self) -> list[dict[str, Any]]:
        return self.fixture.recorder.all(self.assistant_kind)

    def _room_last_seq(self) -> int:
        entries = self.fixture.recorder.all()
        relevant = [e for e in entries if e["kind"] in (self.assistant_kind, "line")]
        return relevant[-1]["seq"] if relevant else 0

    def _room_quiet_for(self, seconds: float) -> bool:
        """No line from anyone for ``seconds`` — measured on the recorder clock."""
        entries = [
            e
            for e in self.fixture.recorder.all()
            if e["kind"] in (self.assistant_kind, "line")
        ]
        if not entries:
            return True
        last = entries[-1]["at"]
        from datetime import datetime

        elapsed = (
            datetime.now(datetime.fromisoformat(last).tzinfo)
            - datetime.fromisoformat(last)
        ).total_seconds()
        return elapsed >= seconds

    def _transcript(self) -> str:
        lines = []
        for e in self.fixture.recorder.all():
            if e["kind"] == "line":
                p = e["payload"]
                lines.append(f"[{p['who']}] {p['text']}")
            elif e["kind"] == self.assistant_kind:
                lines.append(f"[assistant] {(e['payload'] or {}).get('text', '')}")
        return "\n".join(lines)

    # ------------------------------------------------------------- speaking

    def _record(self, who: str, text: str, kind: str, **meta: Any) -> Said:
        seq = self.fixture.recorder.record(
            "line",
            {"who": who, "text": text, "kind": kind},
        )
        self.fixture.state[self.room_key].append({"seq": seq, "who": who, "text": text})
        # What was actually said, in whoever's words it ended up in, joins
        # the speaker's own memory — the persona engine's transcript of what
        # this person has said on any channel this run.
        if self._pool is not None and hasattr(self._pool, "note_authored"):
            self._pool.note_authored(who, text, channel="room")
        said = Said(who=who, text=text, kind=kind, seq=seq, at=utcnow(), **meta)
        with self._lock:
            self._said.append(said)
        return said

    def _speak(self, who: str, text: str, kind: str, **meta: Any) -> Said:
        said = self._record(who, text, kind, **meta)
        try:
            detail = self._deliver(who, text) or {}
            said.delivered = bool(detail.get("delivered", True))
            said.mode = str(detail.get("mode") or "live_interject")
        except Unsupported:
            said.delivered = False
            said.mode = "pending"
            with self._lock:
                self._pending.append(said)
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            said.delivered = False
            said.mode = f"delivery_failed: {type(exc).__name__}: {exc}"
        return said

    def _word_beat(self, beat: Beat) -> str:
        """The beat in the role's own words when live; verbatim otherwise."""
        if not self.live or self._pool is None:
            return beat.text
        transcript = self._transcript()
        prompt = (
            "Here is the room conversation so far:\n\n"
            f"{transcript or '(nothing yet)'}\n\n"
            "You now say the following, in your own words and in character, "
            "keeping its point exactly:\n\n"
            f"  {beat.text}\n\n"
            + (f"Purpose: {beat.intent}\n\n" if beat.intent else "")
            + "One or two sentences. Say only this; do not add other topics."
        )
        # Direction, not conversation: the wording prompt must not enter the
        # persona's memory as something the assistant said to them.
        text = self._pool.answer(beat.who, prompt, channel="scene", remember=False)
        return text.strip() or beat.text

    def _maybe_react(self, who: str, assistant_line: str) -> None:
        if not (self.scene.react and self.live and self._pool is not None):
            return
        if self._reactions.get(who, 0) >= self.scene.max_reactions_per_role:
            return
        prompt = (
            "Here is the room conversation so far:\n\n"
            f"{self._transcript()}\n\n"
            f'The assistant just said: "{assistant_line}"\n\n'
            "If that was addressed to you and calls for a reply — an answer to "
            "a question, a correction, a thank-you that moves things on — say "
            "it, in one or two sentences. If it was not for you, or nothing "
            "needs saying, reply with exactly the single word SILENT."
        )
        text = self._pool.answer(who, prompt, channel="scene", remember=False).strip()
        if not text or text.upper().startswith("SILENT"):
            return
        self._reactions[who] = self._reactions.get(who, 0) + 1
        self._speak(who, text, "reaction")

    # ------------------------------------------------------------------ run

    def _run(self) -> None:
        roles = sorted({b.who for b in self.scene.beats})
        seen_assistant = 0
        try:
            for index, beat in enumerate(self.scene.beats):
                if self._stop.is_set():
                    break
                # Let the room settle before the next line, and give live
                # roles a chance to react to anything the assistant just said.
                deadline = time.monotonic() + max(self.scene.quiet_s, 0.1) + 60
                while time.monotonic() < deadline and not self._stop.is_set():
                    lines = self._assistant_lines()
                    for e in lines[seen_assistant:]:
                        for who in roles:
                            self._maybe_react(
                                who,
                                str((e.get("payload") or {}).get("text", "")),
                            )
                    seen_assistant = len(lines)
                    if self._room_quiet_for(self.scene.quiet_s):
                        break
                    time.sleep(0.25)

                said = self._speak(
                    beat.who,
                    self._word_beat(beat),
                    "beat",
                    beat_index=index,
                    to_assistant=beat.to_assistant,
                )

                if beat.to_assistant:
                    # Wait, up to patience, for the assistant to say something.
                    end = time.monotonic() + beat.patience
                    while time.monotonic() < end and not self._stop.is_set():
                        lines = self._assistant_lines()
                        later = [e for e in lines if e["seq"] > said.seq]
                        if later:
                            said.answered_seq = later[0]["seq"]
                            break
                        time.sleep(0.25)

            # Settle: keep listening so late answers and reactions are seen.
            end = time.monotonic() + self.scene.settle_s
            while time.monotonic() < end and not self._stop.is_set():
                lines = self._assistant_lines()
                for e in lines[seen_assistant:]:
                    for who in roles:
                        self._maybe_react(
                            who,
                            str((e.get("payload") or {}).get("text", "")),
                        )
                seen_assistant = len(lines)
                time.sleep(0.25)
        finally:
            self._finalise()
            self.fixture.state["roleplay_done"] = True
            self._done.set()

    def _finalise(self) -> None:
        """Fill in next_seq / answered_seq now that the whole scene is known."""
        lines = self._assistant_lines()
        with self._lock:
            ordered = sorted(self._said, key=lambda s: s.seq)
            for i, s in enumerate(ordered):
                s.next_seq = ordered[i + 1].seq if i + 1 < len(ordered) else None
                if s.to_assistant and s.answered_seq is None:
                    later = [e for e in lines if e["seq"] > s.seq]
                    if later:
                        s.answered_seq = later[0]["seq"]

    # ------------------------------------------------------------ interface

    def start(self) -> "RolePlayDirector":
        self._thread = threading.Thread(target=self._run, name="roleplay", daemon=True)
        self._thread.start()
        return self

    def wait(self, timeout: float = 600.0) -> bool:
        return self._done.wait(timeout=timeout)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def pop_pending(self) -> Said | None:
        with self._lock:
            return self._pending.pop(0) if self._pending else None

    def note_delivered(self, said: Said, mode: str) -> None:
        said.delivered = mode not in ("not_delivered",)
        said.mode = mode

    def journal(self) -> list[dict[str, Any]]:
        with self._lock:
            return [s.as_dict() for s in sorted(self._said, key=lambda s: s.seq)]

    def beats_aimed(self) -> list[Said]:
        with self._lock:
            return [s for s in self._said if s.kind == "beat" and s.to_assistant]
