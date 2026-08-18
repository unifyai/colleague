"""The role-play director, over audio instead of text.

Same scene, same beats, same journal — the only change is the channel. A beat
is spoken through its role's TTS track at the same waypoint (the room quiet
for `quiet_s`); the assistant is a participant in the room and speaks through
its own voice; the harness captures every assistant utterance with
`[spoken_at, ended_at]` and records it into the fixture recorder as a `say`,
so `meeting/scenario.py`'s scorer reads exactly what it read in text.

`RolePlayDirector`'s journal shape is preserved so the scorer needs no change:
each `Said` carries `seq` (recorder order — the ordering authority), plus the
transport timestamps for the write-up and the overlap check.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from colleague.harness.fixture_server import FixtureServer, utcnow
from colleague.harness.roleplay import Said, Scene
from colleague.harness.voice.room import Utterance, VoiceRoom


class VoiceRolePlayDirector:
    """Runs a scene against an arm that has joined the room by voice."""

    def __init__(
        self,
        *,
        fixture: FixtureServer,
        scene: Scene,
        room: VoiceRoom,
        room_key: str = "room",
        assistant_kind: str = "say",
    ) -> None:
        self.fixture = fixture
        self.scene = scene
        self.room = room
        self.room_key = room_key
        self.assistant_kind = assistant_kind
        self._pool = fixture.state.get("personas")
        self._said: list[Said] = []
        self._reactions: dict[str, int] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._done = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_audio_end = time.monotonic()
        self._new_assistant = threading.Event()
        self.fixture.state.setdefault(room_key, [])
        self.fixture.state["roleplay_done"] = False
        self.fixture.state["transport"] = "voice"
        # The room reports assistant utterances here.
        self.room._on_utterance = self._on_assistant_utterance  # type: ignore[assignment]

    # ---------------------------------------------------------------- state

    @property
    def live(self) -> bool:
        return bool(self._pool is not None and self._pool.live)

    def _assistant_lines(self) -> list[dict[str, Any]]:
        return self.fixture.recorder.all(self.assistant_kind)

    def _quiet_for(self, seconds: float) -> bool:
        return (time.monotonic() - self._last_audio_end) >= seconds

    def _transcript(self) -> str:
        lines = []
        for e in self.fixture.recorder.all():
            if e["kind"] == "line":
                p = e["payload"]
                lines.append(f"[{p['who']}] {p['text']}")
            elif e["kind"] == self.assistant_kind:
                lines.append(f"[assistant] {(e['payload'] or {}).get('text', '')}")
        return "\n".join(lines)

    # -------------------------------------------------- assistant capture

    def _on_assistant_utterance(self, u: Utterance) -> None:
        """Record an assistant line the room captured, as a `say`.

        The recorder assigns the sequence, so the interleaving of persona
        `line`s and assistant `say`s reflects real speaking order — the same
        witness the text room's `/say` produced.
        """
        seq = self.fixture.recorder.record(
            self.assistant_kind,
            {
                "text": u.text,
                "who": u.who,
                "spoken_at": u.spoken_at,
                "ended_at": u.ended_at,
                "source": u.source,
                "transcript": u.transcript,
            },
        )
        self.fixture.state[self.room_key].append(
            {"seq": seq, "who": u.who, "text": u.text},
        )
        self._last_audio_end = time.monotonic()
        self._new_assistant.set()

    # ------------------------------------------------------------- speaking

    def _record_beat(self, said: Said) -> None:
        seq = self.fixture.recorder.record(
            "line",
            {"who": said.who, "text": said.text, "kind": said.kind},
        )
        said.seq = seq
        self.fixture.state[self.room_key].append(
            {"seq": seq, "who": said.who, "text": said.text},
        )
        with self._lock:
            self._said.append(said)

    def _speak(self, who: str, text: str, kind: str, **meta: Any) -> Said:
        # Record the line first so its recorder seq precedes any assistant
        # answer, then play the audio (blocking) and stamp the transport times.
        said = Said(
            who=who,
            text=text,
            kind=kind,
            seq=0,
            at=utcnow(),
            mode="spoken",
            **meta,
        )
        self._record_beat(said)
        try:
            spoken = self.room.speak(who, text)
            said.spoken_at = spoken.spoken_at
            said.ended_at = spoken.ended_at
            said.delivered = True
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            said.delivered = False
            said.mode = f"speak_failed: {type(exc).__name__}: {exc}"
        self._last_audio_end = time.monotonic()
        return said

    def _word_beat(self, beat) -> str:
        if not self.live or self._pool is None:
            return beat.text
        prompt = (
            "Here is the room conversation so far:\n\n"
            f"{self._transcript() or '(nothing yet)'}\n\n"
            "You now say the following, in your own words and in character, "
            "keeping its point exactly:\n\n"
            f"  {beat.text}\n\n"
            + (f"Purpose: {beat.intent}\n\n" if beat.intent else "")
            + "One or two sentences. Say only this; do not add other topics."
        )
        return (
            self._pool.answer(beat.who, prompt, expect=()) or ""
        ).strip() or beat.text

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
        text = (self._pool.answer(who, prompt, expect=()) or "").strip()
        if not text or text.upper().startswith("SILENT"):
            return
        self._reactions[who] = self._reactions.get(who, 0) + 1
        self._speak(who, text, "reaction")

    # ------------------------------------------------------------------ run

    def _react_to_new(self, roles: list[str], seen: int) -> int:
        lines = self._assistant_lines()
        for e in lines[seen:]:
            for who in roles:
                self._maybe_react(who, str((e.get("payload") or {}).get("text", "")))
        return len(lines)

    def _run(self) -> None:
        roles = sorted({b.who for b in self.scene.beats})
        seen_assistant = 0
        try:
            for index, beat in enumerate(self.scene.beats):
                if self._stop.is_set():
                    break
                # Let the room settle, reacting to anything the assistant said.
                deadline = time.monotonic() + max(self.scene.quiet_s, 0.1) + 60
                while time.monotonic() < deadline and not self._stop.is_set():
                    seen_assistant = self._react_to_new(roles, seen_assistant)
                    if self._quiet_for(self.scene.quiet_s):
                        break
                    time.sleep(0.1)

                said = self._speak(
                    beat.who,
                    self._word_beat(beat),
                    "beat",
                    beat_index=index,
                    to_assistant=beat.to_assistant,
                )

                if beat.to_assistant:
                    end = time.monotonic() + beat.patience
                    self._new_assistant.clear()
                    while time.monotonic() < end and not self._stop.is_set():
                        later = [
                            e for e in self._assistant_lines() if e["seq"] > said.seq
                        ]
                        if later:
                            said.answered_seq = later[0]["seq"]
                            break
                        self._new_assistant.wait(timeout=0.25)
                        self._new_assistant.clear()

            # Settle: keep listening so late answers and reactions land.
            end = time.monotonic() + self.scene.settle_s
            while time.monotonic() < end and not self._stop.is_set():
                seen_assistant = self._react_to_new(roles, seen_assistant)
                time.sleep(0.2)
        finally:
            self._finalise()
            self.fixture.state["roleplay_done"] = True
            self._done.set()

    def _finalise(self) -> None:
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

    def start(self) -> "VoiceRolePlayDirector":
        self._thread = threading.Thread(
            target=self._run,
            name="voice-roleplay",
            daemon=True,
        )
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
        # A voice arm is live in the room; there is no queued-followup fallback.
        return None

    def note_delivered(self, said: Said, mode: str) -> None:
        said.mode = mode

    def journal(self) -> list[dict[str, Any]]:
        with self._lock:
            return [s.as_dict() for s in sorted(self._said, key=lambda s: s.seq)]

    def assistant_utterances(self) -> list[dict[str, Any]]:
        return [
            (e.get("payload") or {})
            for e in self.fixture.recorder.all(self.assistant_kind)
        ]
