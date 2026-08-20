"""A phone call the harness places: the carrier side of OpenClaw's voice-call.

OpenClaw's voice surface is its voice-call extension: a webhook server plus a
carrier media stream (G.711 µ-law @ 8 kHz in Twilio's Media Streams framing),
with the extension doing its own TTS into the stream and its own STT out of
it. The room on this substrate is therefore *a call*: the harness plays the
carrier — it rings the arm's webhook exactly as Twilio would, connects the
media WebSocket the arm's TwiML asks for, and is thereafter the phone line
itself. Personas are distinct TTS voices mixed onto the caller track (a phone
line is one channel — per-speaker attribution is a real problem the arm must
solve from the audio, which is honest to what a conference call over one line
gives anybody); the assistant's audio is whatever the arm's own pipeline
sends back down the stream.

The fixture-discipline reading: the webhook POST and the media frames are the
*environment* (a call arriving is not a capability of the assistant), while
answering, hearing, deciding to speak and speaking are all the arm's own
machinery — the harness never offers a text path into the call.

Wire specifics follow Twilio Media Streams, which is the dialect OpenClaw's
stream handler speaks: 160-byte / 20 ms base64 µ-law frames in JSON events
(`start` / `media` / `mark` / `stop`), a continuous caller track (silence is
0xff bytes, the µ-law zero), and real-time pacing against an absolute clock.
"""

from __future__ import annotations

import audioop
import base64
import json
import threading
import time
import urllib.parse
import urllib.request
import uuid
from typing import Any
from xml.etree import ElementTree

from colleague.harness.voice.room import RoomInvite
from colleague.harness.voice.substrate import SubstrateVoiceRoom
from colleague.harness.voice.tts import SAMPLE_RATE, VoiceBank

#: G.711 µ-law telephony: 8 kHz, one byte per sample, 20 ms frames.
_PHONE_RATE = 8000
_FRAME_BYTES = 160
_FRAME_S = 0.02
_ULAW_SILENCE = b"\xff" * _FRAME_BYTES


class PhoneCallRoom(SubstrateVoiceRoom):
    """One call, rung and held by the harness against the arm's webhook."""

    substrate = "phone"

    def __init__(
        self,
        *,
        room_name: str,
        bank: VoiceBank,
        assistant_identities: tuple[str, ...],
        webhook_url: str,
        stream_base: str,
        from_number: str,
        to_number: str,
        transcribe_assistant: bool = True,
    ) -> None:
        super().__init__(
            room_name=room_name,
            bank=bank,
            assistant_identities=assistant_identities,
            transcribe_assistant=transcribe_assistant,
        )
        self.webhook_url = webhook_url
        #: The local origin the arm's stream endpoint actually listens on.
        #: The TwiML's stream URL carries the arm's declared *public* origin
        #: (the extension refuses loopback there); the carrier — us — knows
        #: where the server really is, exactly as Twilio knows the tunnel.
        self.stream_base = stream_base.rstrip("/")
        self.from_number = from_number
        self.to_number = to_number
        self.call_sid = "CA" + uuid.uuid4().hex
        self.stream_sid = "MZ" + uuid.uuid4().hex
        self._ws: Any = None
        self._sender: threading.Thread | None = None
        self._receiver: threading.Thread | None = None
        self._stop = threading.Event()
        self._play_lock = threading.Lock()
        self._play_queue: list[bytes] = []
        self._queue_empty = threading.Event()
        self._queue_empty.set()
        self._up_state: Any = None  # audioop.ratecv state, 8k -> 48k
        self._seq = 0
        self._sent_status: list[str] = []
        self.answered_twiml = ""

    # ------------------------------------------------------------ carrier

    def _post_webhook(self, status: str, extra: dict[str, str] | None = None) -> str:
        """One provider status webhook, as Twilio would send it."""
        form = {
            "CallSid": self.call_sid,
            "AccountSid": "AC" + "0" * 32,
            "From": self.from_number,
            "To": self.to_number,
            "Direction": "inbound",
            "CallStatus": status,
            "ApiVersion": "2010-04-01",
            # Replay dedupe on the arm's side keys on content; every webhook
            # must be distinguishable or a repeat is silently swallowed.
            "SequenceNumber": str(len(self._sent_status)),
            **(extra or {}),
        }
        req = urllib.request.Request(
            self.webhook_url,
            data=urllib.parse.urlencode(form).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        self._sent_status.append(status)
        return body

    def ring(self) -> dict[str, Any]:
        """Ring the arm and connect the media stream its TwiML asks for.

        The webhook answer *is* the answer: a carrier that receives TwiML
        plays it, and `<Connect><Stream>` means the call is live with its
        media over the WebSocket. The arm's own inbound policy decides —
        a `<Reject>` here is the arm declining the call, and is surfaced.
        """
        twiml = self._post_webhook("ringing")
        self.answered_twiml = twiml
        stream_path, token = _parse_stream_twiml(twiml)
        if stream_path is None:
            raise RuntimeError(
                f"the arm's webhook answered without a media stream: {twiml[:400]}",
            )
        from websockets.sync.client import connect as ws_connect

        self._ws = ws_connect(
            f"{self.stream_base}{stream_path}",
            max_size=2**22,
            open_timeout=20,
        )
        start = {
            "event": "start",
            "sequenceNumber": "1",
            "streamSid": self.stream_sid,
            "start": {
                "streamSid": self.stream_sid,
                "accountSid": "AC" + "0" * 32,
                "callSid": self.call_sid,
                "tracks": ["inbound"],
                "customParameters": {"token": token} if token else {},
                "mediaFormat": {
                    "encoding": "audio/x-mulaw",
                    "sampleRate": _PHONE_RATE,
                    "channels": 1,
                },
            },
        }
        self._ws.send(json.dumps(start))
        self._sender = threading.Thread(
            target=self._pump_caller_track,
            name="phone-caller-track",
            daemon=True,
        )
        self._receiver = threading.Thread(
            target=self._read_assistant_track,
            name="phone-assistant-track",
            daemon=True,
        )
        self._sender.start()
        self._receiver.start()
        # Mark the call answered deterministically. The arm's own machinery
        # would set `answeredAt` off the first transcript or its greeting, but
        # a status callback pins it now, which is what keeps the stale-call
        # reaper off an answered-but-quiet call. Its TwiML response (hold
        # music, since the stream is already live) is not used.
        try:
            self._post_webhook("in-progress")
        except Exception:  # noqa: BLE001 - answered is best-effort
            pass
        return {"call_sid": self.call_sid, "stream_path": stream_path}

    # ------------------------------------------------------------- uplink

    def _pump_caller_track(self) -> None:
        """The caller track never stops: personas' frames when queued,
        µ-law silence otherwise, paced on an absolute 20 ms clock."""
        t0 = time.monotonic()
        sent = 0
        while not self._stop.is_set():
            with self._play_lock:
                frame = self._play_queue.pop(0) if self._play_queue else None
                if not self._play_queue:
                    self._queue_empty.set()
            payload = frame if frame is not None else _ULAW_SILENCE
            self._seq += 1
            msg = {
                "event": "media",
                "sequenceNumber": str(self._seq + 1),
                "streamSid": self.stream_sid,
                "media": {
                    "track": "inbound",
                    "chunk": str(self._seq),
                    "timestamp": str(int(sent * _FRAME_S * 1000)),
                    "payload": base64.b64encode(payload).decode(),
                },
            }
            try:
                self._ws.send(json.dumps(msg))
            except Exception:  # noqa: BLE001 - the arm hung up; the room ends
                self._stop.set()
                return
            sent += 1
            next_at = t0 + sent * _FRAME_S
            delay = next_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)

    def _play(self, who: str, pcm: bytes) -> None:
        del who  # one caller track; the voice itself distinguishes speakers
        pcm8, _ = audioop.ratecv(pcm, 2, 1, SAMPLE_RATE, _PHONE_RATE, None)
        ulaw = audioop.lin2ulaw(pcm8, 2)
        frames = [
            ulaw[i : i + _FRAME_BYTES].ljust(_FRAME_BYTES, b"\xff")
            for i in range(0, len(ulaw), _FRAME_BYTES)
        ]
        with self._play_lock:
            self._play_queue.extend(frames)
            self._queue_empty.clear()
        # Block until the pump has drained the line's real seconds.
        self._queue_empty.wait(timeout=len(frames) * _FRAME_S + 30)

    # ----------------------------------------------------------- downlink

    def _read_assistant_track(self) -> None:
        while not self._stop.is_set():
            try:
                raw = self._ws.recv(timeout=1.0)
            except TimeoutError:
                continue
            except Exception:  # noqa: BLE001 - closed socket ends the call
                self._stop.set()
                return
            try:
                msg = json.loads(raw)
            except (TypeError, ValueError):
                continue
            event = msg.get("event")
            if event == "media":
                payload = (msg.get("media") or {}).get("payload") or ""
                try:
                    ulaw = base64.b64decode(payload)
                except Exception:  # noqa: BLE001 - a bad frame is dropped
                    continue
                pcm8 = audioop.ulaw2lin(ulaw, 2)
                pcm48, self._up_state = audioop.ratecv(
                    pcm8,
                    2,
                    1,
                    _PHONE_RATE,
                    SAMPLE_RATE,
                    self._up_state,
                )
                self._feed_assistant_pcm(self.assistant_identity, pcm48)
            elif event == "mark":
                # The arm marks the end of a TTS playout. The utterance text
                # is captured from the arm's TTS input (a tap), so a mark needs
                # no action here; the audio is corroboration, accumulated above.
                continue

    # ------------------------------------------------------------ interface

    def invite(self) -> RoomInvite:
        """The invite on this substrate is the ring itself; what the bridge
        needs is the caller identity and the call's name for the record."""
        return RoomInvite(
            url=self.webhook_url,
            token="",
            identity=self.assistant_identity,
            room_name=self.room_name,
            assistant_identities=self.assistant_identities,
        )

    def evidence(self) -> dict[str, Any]:
        return {
            **super().evidence(),
            "call_sid": self.call_sid,
            "from_number": self.from_number,
            "to_number": self.to_number,
        }

    def _shutdown(self) -> None:
        self._stop.set()
        # The carrier's final word first: `completed` finalizes the call on
        # the arm's side with no network call. Order matters — the arm's own
        # hangup path POSTs to the real carrier API and fails on the fixture's
        # credentials, leaving the call un-finalized; closing the media stream
        # would trigger exactly that after a 2 s grace. Finalizing first makes
        # the later grace-driven hangup a no-op on an already-terminal call.
        try:
            self._post_webhook("completed")
        except Exception:  # noqa: BLE001 - the arm may already be down
            pass
        ws = self._ws
        if ws is not None:
            try:
                ws.send(
                    json.dumps(
                        {
                            "event": "stop",
                            "streamSid": self.stream_sid,
                            "stop": {
                                "accountSid": "AC" + "0" * 32,
                                "callSid": self.call_sid,
                            },
                        },
                    ),
                )
            except Exception:  # noqa: BLE001
                pass
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
        for t in (self._sender, self._receiver):
            if t is not None:
                t.join(timeout=3)


def _parse_stream_twiml(twiml: str) -> tuple[str | None, str]:
    """The `<Connect><Stream>` the arm answered with: its path and token.

    The URL's origin is the arm's declared public host and is replaced by the
    carrier's knowledge of where the server is; the path and the token
    parameter are the arm's own.
    """
    try:
        root = ElementTree.fromstring(twiml)
    except ElementTree.ParseError:
        return None, ""
    for stream in root.iter("Stream"):
        url = stream.get("url") or ""
        token = ""
        for param in stream.iter("Parameter"):
            if param.get("name") == "token":
                token = param.get("value") or ""
        path = urllib.parse.urlparse(url).path or "/"
        query = urllib.parse.urlparse(url).query
        if query:
            path = f"{path}?{query}"
        return path, token
    return None, ""
