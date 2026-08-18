"""A LiveKit room the harness owns: persona voices in, assistant voice out.

Each **person** is a separate LiveKit participant publishing its own audio
track, so who-said-what is a real problem an arm must solve, not a courtesy
the harness performs. The **assistant** joins as its own participant through
its own voice surface (never a harness path), and one capture participant
listens to it: energy segmentation gives every assistant utterance a
`[spoken_at, ended_at]` interval, and the text is taken from the arm when the
arm hands it over, or transcribed when it does not.

The LiveKit SDK is asyncio and confined to this module; the room runs on its
own event-loop thread and exposes blocking calls, so the threaded role-play
director drives it exactly as it drives the text room.
"""

from __future__ import annotations

import asyncio
import audioop
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from colleague.harness.voice import stt
from colleague.harness.voice.tts import SAMPLE_RATE, SAMPLE_WIDTH, VoiceBank

#: 20ms frames at 48k mono — LiveKit's native tick.
_FRAME_SAMPLES = SAMPLE_RATE // 50
_FRAME_BYTES = _FRAME_SAMPLES * SAMPLE_WIDTH

#: Energy segmentation of the assistant's audio. Deliberately simple: this is
#: for utterance *bounds* (in-time, overlap), never for turn-taking quality.
_SILENCE_RMS = 350
_SILENCE_HANG_S = 0.6  # bridge gaps shorter than this within one utterance
_MIN_UTTERANCE_S = 0.2


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Utterance:
    """One spoken line, with the transport timestamps scoring needs."""

    who: str
    text: str
    spoken_at: str
    ended_at: str
    source: str = "audio"  # "arm_text" (exact) | "transcript" | "audio"
    transcript: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class RoomInvite:
    """What an arm needs to join the room as itself."""

    url: str
    token: str
    identity: str
    room_name: str

    def as_dict(self) -> dict[str, Any]:
        return {"url": self.url, "identity": self.identity, "room_name": self.room_name}


class _LoopThread:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="voice-room",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=10)

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.call_soon(self._ready.set)
        self.loop.run_forever()

    def run(self, coro, timeout: float = 120.0):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=timeout)

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=5)


class VoiceRoom:
    """The room, its persona speakers, and the capture of the assistant.

    Built and driven from a worker thread; all LiveKit work happens on an
    internal event loop. `speak` blocks until the persona's line has played,
    so the director's waypoint timing is honest.
    """

    def __init__(
        self,
        *,
        room_name: str,
        url: str,
        api_key: str,
        api_secret: str,
        bank: VoiceBank,
        assistant_identity: str | None = None,
        assistant_identities: tuple[str, ...] | None = None,
        on_assistant_utterance: Callable[[Utterance], None],
        transcribe_assistant: bool = False,
    ) -> None:
        self.room_name = room_name
        self.url = url
        self._api_key = api_key
        self._api_secret = api_secret
        self.bank = bank
        idents = tuple(assistant_identities or ())
        if assistant_identity:
            idents = (assistant_identity, *idents)
        if not idents:
            raise ValueError("at least one assistant identity is required")
        self.assistant_identities = idents
        #: The primary identity, used as the default join target and the
        #: default addressee of noted text.
        self.assistant_identity = idents[0]
        self._on_utterance = on_assistant_utterance
        self._transcribe = transcribe_assistant
        self._loop = _LoopThread()
        self._speakers: dict[str, Any] = {}
        self._capture: Any = None
        #: Per-assistant-identity queue of (text, at) the arm handed over.
        self._noted_texts: dict[str, list[tuple[str, str]]] = {i: [] for i in idents}
        self._lock = threading.Lock()

    # ------------------------------------------------------------- tokens

    def _token(self, identity: str, *, publish: bool, subscribe: bool) -> str:
        from livekit import api

        grants = api.VideoGrants(
            room_join=True,
            room=self.room_name,
            can_publish=publish,
            can_subscribe=subscribe,
            can_publish_data=True,
        )
        return (
            api.AccessToken(self._api_key, self._api_secret)
            .with_identity(identity)
            .with_name(identity)
            .with_grants(grants)
            .to_jwt()
        )

    def invite(self, identity: str | None = None) -> RoomInvite:
        """A join token for the arm, as the assistant identity by default."""
        ident = identity or self.assistant_identity
        return RoomInvite(
            url=self.url,
            token=self._token(ident, publish=True, subscribe=True),
            identity=ident,
            room_name=self.room_name,
        )

    def _assistant_alias(self, identity: str) -> str | None:
        """Which declared assistant a room participant is, or None for cast.

        An arm need not join with the invite's identity — unify's agent
        dispatch mints its own — so anyone who is not the harness capture
        and not a persona speaker is an assistant. With one declared
        assistant every such participant is it; with several, an exact
        identity match wins and an unknown identity is reported as itself,
        which scoring will surface rather than misattribute.
        """
        if identity == "harness-capture" or identity.startswith("persona-"):
            return None
        if identity in self.assistant_identities:
            return identity
        if len(self.assistant_identities) == 1:
            return self.assistant_identities[0]
        return identity

    # --------------------------------------------------------------- boot

    def start(self) -> "VoiceRoom":
        self._loop.run(self._start_capture(), timeout=30)
        return self

    async def _start_capture(self) -> None:
        from livekit import rtc

        room = rtc.Room()

        @room.on("track_subscribed")
        def _on_sub(track, publication, participant):  # noqa: ANN001
            alias = self._assistant_alias(participant.identity)
            if alias is None:
                return
            if track.kind != rtc.TrackKind.KIND_AUDIO:
                return
            asyncio.create_task(self._read_assistant(track, alias))

        await room.connect(
            self.url,
            self._token("harness-capture", publish=False, subscribe=True),
            options=rtc.RoomOptions(auto_subscribe=True),
        )
        self._capture = room

    async def _read_assistant(self, track: Any, who: str) -> None:
        from livekit import rtc

        stream = rtc.AudioStream(track, sample_rate=SAMPLE_RATE, num_channels=1)
        speaking = False
        seg = bytearray()
        started: str = ""
        last_voice = 0.0
        async for ev in stream:
            frame = ev.frame
            data = bytes(frame.data)
            rms = audioop.rms(data, SAMPLE_WIDTH) if data else 0
            now = time.monotonic()
            if rms >= _SILENCE_RMS:
                if not speaking:
                    speaking = True
                    started = _utcnow()
                    seg = bytearray()
                seg.extend(data)
                last_voice = now
            elif speaking:
                seg.extend(data)
                if now - last_voice >= _SILENCE_HANG_S:
                    self._emit_segment(bytes(seg), started, who)
                    speaking = False
                    seg = bytearray()
        if speaking and seg:
            self._emit_segment(bytes(seg), started, who)

    def _emit_segment(self, pcm: bytes, started: str, who: str) -> None:
        dur = len(pcm) / (SAMPLE_RATE * SAMPLE_WIDTH)
        if dur < _MIN_UTTERANCE_S:
            return
        ended = _utcnow()
        # Prefer the arm's own text when it handed us one; the segment gives
        # the timing either way.
        with self._lock:
            queue = self._noted_texts.get(who) or []
            noted = queue.pop(0) if queue else None
        if noted is not None:
            text, _ = noted
            source = "arm_text"
            transcript = stt.transcribe(pcm) if self._transcribe else ""
        else:
            transcript = stt.transcribe(pcm)
            text = transcript
            source = "transcript" if transcript else "audio"
        self._on_utterance(
            Utterance(
                who=who,
                text=text,
                spoken_at=started,
                ended_at=ended,
                source=source,
                transcript=transcript,
            ),
        )

    def note_assistant_text(self, text: str, who: str | None = None) -> None:
        """The arm's own utterance text (its TTS input), paired to the audio.

        Called by an adapter that exposes the string it spoke. The text is
        authoritative for scoring; the captured audio segment supplies the
        timestamps. Order-preserving: the nth noted line pairs with the nth
        detected segment of the same assistant identity.
        """
        text = (text or "").strip()
        if not text:
            return
        ident = who or self.assistant_identity
        with self._lock:
            self._noted_texts.setdefault(ident, []).append((text, _utcnow()))

    # ------------------------------------------------------------- speak

    def speak(self, who: str, text: str) -> Utterance:
        """Render `who`'s line and play it; block until playout completes."""
        pcm = self.bank.render(who, text)
        return self._loop.run(self._speak(who, pcm), timeout=180)

    async def _speak(self, who: str, pcm: bytes) -> Utterance:
        speaker = await self._ensure_speaker(who)
        spoken_at = _utcnow()
        source = speaker["source"]
        for i in range(0, len(pcm), _FRAME_BYTES):
            chunk = pcm[i : i + _FRAME_BYTES]
            if len(chunk) < _FRAME_BYTES:
                chunk = chunk + b"\x00" * (_FRAME_BYTES - len(chunk))
            await source.capture_frame(_audio_frame(chunk))
        with_playout = getattr(source, "wait_for_playout", None)
        if with_playout is not None:
            await source.wait_for_playout()
        return Utterance(who=who, text="", spoken_at=spoken_at, ended_at=_utcnow())

    async def _ensure_speaker(self, who: str) -> dict[str, Any]:
        if who in self._speakers:
            return self._speakers[who]
        from livekit import rtc

        room = rtc.Room()
        await room.connect(
            self.url,
            self._token(f"persona-{who}", publish=True, subscribe=False),
            options=rtc.RoomOptions(auto_subscribe=False),
        )
        source = rtc.AudioSource(SAMPLE_RATE, 1)
        track = rtc.LocalAudioTrack.create_audio_track(f"{who}-voice", source)
        await room.local_participant.publish_track(
            track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
        )
        entry = {"room": room, "source": source, "track": track}
        self._speakers[who] = entry
        # A moment for the assistant to subscribe before the first frame.
        await asyncio.sleep(0.3)
        return entry

    # ------------------------------------------------------------ teardown

    def close(self) -> None:
        try:
            self._loop.run(self._close(), timeout=30)
        except Exception:  # noqa: BLE001 - teardown is best-effort
            pass
        self._loop.close()

    async def _close(self) -> None:
        for entry in self._speakers.values():
            try:
                await entry["room"].disconnect()
            except Exception:  # noqa: BLE001
                pass
        if self._capture is not None:
            try:
                await self._capture.disconnect()
            except Exception:  # noqa: BLE001
                pass

    def metering(self) -> dict[str, Any]:
        return self.bank.metering()


def _audio_frame(chunk: bytes):
    from livekit import rtc

    return rtc.AudioFrame(chunk, SAMPLE_RATE, 1, len(chunk) // SAMPLE_WIDTH)
