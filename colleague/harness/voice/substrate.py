"""The director-facing room surface, for substrates that are not LiveKit.

The contract (README §"Why LiveKit…"): an arm on its own substrate joins that
substrate's room; the harness still owns the persona voices and the capture
on that substrate. `VoiceRolePlayDirector` and the runner drive a room
through a small surface — `speak`, an assistant-utterance callback, an invite
— and this base provides everything in that surface that is not the transport
itself, so a substrate room (Discord voice, a phone call) implements only how
audio moves.

**How the assistant's words are captured.** The same rule as unify-cm, whose
LiveKit result is scored on the arm's own utterance text and not a
transcription (README §"How the assistant's utterance text is obtained"): the
authoritative text is the exact string the arm fed its own TTS, tapped at the
point it speaks from text, and handed here through `note_assistant_text`. One
tapped line is one utterance, emitted when the arm speaks it — robust to how
the transport's audio happens to pause, which a per-segment energy split is
not (a TTS voice pauses between clauses, and splitting there would cut a
"Thursday at 2 p.m." answer in half). The arm's audio *is* still carried on
the real substrate and is captured here as corroboration: its duration proves
the line was voiced in the room, and a whole-call transcript is kept beside
the run as a cross-check on the tapped text.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from colleague.harness.voice import stt
from colleague.harness.voice.room import RoomInvite, Utterance
from colleague.harness.voice.tts import SAMPLE_RATE, SAMPLE_WIDTH, VoiceBank


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class SubstrateVoiceRoom:
    """A harness-owned room on an arm's own substrate.

    Subclasses implement `_play(who, pcm)` (blocking playout of one persona
    line into the room), `invite()`, and `_shutdown()`; audio the assistant
    produces is pushed into `_feed_assistant_pcm` as s16le mono at
    `SAMPLE_RATE`, and the arm's exact spoken text into `note_assistant_text`.
    """

    #: Named in run evidence, so a reader knows which transport carried it.
    substrate = "abstract"

    def __init__(
        self,
        *,
        room_name: str,
        bank: VoiceBank,
        assistant_identities: tuple[str, ...],
        transcribe_assistant: bool = True,
    ) -> None:
        if not assistant_identities:
            raise ValueError("at least one assistant identity is required")
        self.room_name = room_name
        self.bank = bank
        self.assistant_identities = tuple(assistant_identities)
        self.assistant_identity = self.assistant_identities[0]
        self._transcribe = transcribe_assistant
        #: The director replaces this with its recorder-feeding callback.
        self._on_utterance = lambda _u: None
        #: Whether captured audio and noted text count. A substrate where the
        #: arm speaks before the scene (a chat bot greeting its channel) sets
        #: this False until `arm()`; one answered silently leaves it True.
        self._armed = True
        self._lock = threading.Lock()
        self._closed = threading.Event()
        #: Corroboration: all assistant audio the transport carried, and its
        #: duration, so a reader can confirm the tapped lines were voiced.
        self._audio = bytearray()
        self._audio_seconds = 0.0
        self._utterance_count = 0

    # ------------------------------------------------------------- capture

    def arm(self) -> None:
        """Score from here: drop anything captured before the scene."""
        with self._lock:
            self._audio = bytearray()
            self._audio_seconds = 0.0
        self._armed = True

    def note_assistant_text(self, text: str, who: str | None = None) -> None:
        """One line the arm spoke, taken from its own TTS input.

        This is the utterance: emitted when the arm speaks it, with the exact
        words the arm chose. The transport timestamp is the speak-point (the
        arm synthesises and streams in the same breath); the audio carried on
        the substrate corroborates it.
        """
        text = (text or "").strip()
        if not text or not self._armed:
            return
        now = _utcnow()
        with self._lock:
            self._utterance_count += 1
        self._on_utterance(
            Utterance(
                who=who or self.assistant_identity,
                text=text,
                spoken_at=now,
                ended_at=now,
                source="arm_text",
            ),
        )

    def _feed_assistant_pcm(self, who: str, pcm: bytes) -> None:
        """Assistant audio as it arrives — corroboration, not the scored text."""
        del who
        if not pcm or not self._armed:
            return
        with self._lock:
            self._audio.extend(pcm)
            self._audio_seconds += len(pcm) / (SAMPLE_RATE * SAMPLE_WIDTH)

    # ------------------------------------------------------------- speaking

    def speak(self, who: str, text: str) -> Utterance:
        """Render `who`'s line and play it into the room; block until done."""
        pcm = self.bank.render(who, text)
        spoken_at = _utcnow()
        self._play(who, pcm)
        return Utterance(who=who, text="", spoken_at=spoken_at, ended_at=_utcnow())

    def _play(self, who: str, pcm: bytes) -> None:
        raise NotImplementedError

    # ------------------------------------------------------------ interface

    def invite(self) -> RoomInvite:
        raise NotImplementedError

    def metering(self) -> dict[str, Any]:
        return self.bank.metering()

    def _cross_check_transcript(self) -> str:
        with self._lock:
            audio = bytes(self._audio)
        if not audio or not self._transcribe:
            return ""
        return stt.transcribe(audio)

    def evidence(self) -> dict[str, Any]:
        return {
            "substrate": self.substrate,
            "room_name": self.room_name,
            "assistant_identities": list(self.assistant_identities),
            "persona_tts": self.metering(),
            "assistant_audio_seconds": round(self._audio_seconds, 2),
            "assistant_utterances": self._utterance_count,
            "assistant_transcript_crosscheck": self._cross_check_transcript(),
        }

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self._shutdown()
        except Exception:  # noqa: BLE001 - teardown is best-effort
            pass

    def _shutdown(self) -> None:
        raise NotImplementedError
