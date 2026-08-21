"""OpenClaw's voice-call extension as a `meeting` voice arm.

OpenClaw's voice surface is its voice-call extension: a webhook server and a
carrier media stream, doing its own TTS into the stream and its own STT out
of it, with each caller turn driving a full agent turn. The harness plays the
carrier (`colleague.harness.voice.phone_room`): it POSTs the provider's
inbound webhook to the extension's local server, connects the Twilio-shaped
media stream the extension answers with, and streams G.711 µ-law both ways.
Everything on the carrier side is the harness; answering, hearing, deciding
to speak and speaking are the arm's own machinery.

This arm reuses the Gateway session's whole envelope — the managed Gateway
process, the recording proxy, the operator WebSocket client, the state-dir
isolation and post-run defuse (`openclaw_gateway_session`). It adds the
voice-call plugin to the config for a voice run only, rings an inbound call,
and lets the extension's classic streaming pipeline carry the scene.

Two facts from the map shape it:

- The extension hands the harness no live utterance text — the bot transcript
  is a polled store, timestamped after playback — so the assistant's words
  are transcribed by the declared model (Deepgram nova-3), the README's
  audio-only path, with the store's exact transcript kept as a cross-check.
- Each voice turn is a full agent run on the call's session. `sessionScope`
  is pinned to ``main`` so that session is ``agent:main:main`` — the same key
  this arm's opening turn primes over the Gateway — and the model is pinned to
  the bench model through ``voice-call.responseModel``, so a voice answer is
  the product's real call behaviour on the pinned model.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from colleague.arms.openclaw import (
    BENCH_MODEL,
    write_openclaw_config,
)
from colleague.arms.sessions import register
from colleague.arms.sessions.openclaw_gateway_session import (
    OpenClawGatewaySession,
    _free_port,
)
from colleague.harness.capability import PROFILES
from colleague.harness.session import Unsupported

_DEFAULT_CAST = ["daniel", "priya", "bob"]

#: The call session `sessionScope: "main"` resolves to for the default agent.
#: The opening turn is primed on this same key so the call inherits its
#: context (the arm having read /notes).
_MAIN_SESSION_KEY = "agent:main:main"

_CALLER_NUMBER = "+15551230001"
_CALLEE_NUMBER = "+15559990002"

#: A local TTS the arm speaks with, and the exact-text tap. tts-local-cli
#: feeds the spoken text on stdin (no {{text}} placeholder) and reads WAV from
#: stdout, then resamples to telephony µ-law itself. `say` is keyless and
#: offline. The wrapper also appends the exact string the arm chose to say —
#: NUL-separated — to a tap file the session pairs into the room, the same
#: faithful capture as unify-cm's utterance tap: the arm's own words at the
#: point it speaks from text, not a transcription of the audio.
_TTS_WRAPPER = """\
#!/bin/sh
text=$(cat)
printf '%s\\0' "$text" >> "{tap_path}"
tmp="$(mktemp).aiff"
say -o "$tmp" -- "$text" 2>/dev/null || true
ffmpeg -nostdin -loglevel error -y -i "$tmp" -ar 22050 -ac 1 -f wav pipe:1
rm -f "$tmp"
"""


class OpenClawVoiceSession(OpenClawGatewaySession):
    arm = "openclaw-voice"
    profile = PROFILES["openclaw-voice"]

    def __init__(self, **kw: Any) -> None:
        # Share the call's session so the opening turn's context (having read
        # /notes) is in scope when the call generates its answers.
        kw.setdefault("session_key", _MAIN_SESSION_KEY)
        super().__init__(**kw)
        self._cast: list[str] = list(_DEFAULT_CAST)
        self._serve_port = _free_port()
        self._room: Any = None
        self._tts_wrapper: Path | None = None
        self._tap_path: Path | None = None
        self._tap_stop = threading.Event()
        self._tap_thread: threading.Thread | None = None

    # ── config: the CLI arm's envelope, plus the voice-call plugin ────

    def setup(self) -> None:
        # Reproduce the parent's setup, but write the config with the
        # voice-call plugin enabled. (The parent writes it without; rather
        # than call super().setup() and rewrite, assemble it here.)
        from colleague.arms.openclaw import OPENCLAW_REPO, GatewayProcess
        from colleague.arms.openclaw_gateway import GatewayClient

        if not (OPENCLAW_REPO / "dist").is_dir():
            raise SystemExit(
                "OpenClaw build output missing — run `pnpm install && pnpm build` "
                f"in {OPENCLAW_REPO}",
            )
        self.state_dir = self.results_dir / "openclaw_state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.workspace = self.results_dir / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)

        self._tap_path = self.state_dir / "spoken_tap"
        self._tts_wrapper = self.state_dir / "tts_say.sh"
        self._tts_wrapper.write_text(
            _TTS_WRAPPER.replace("{tap_path}", str(self._tap_path)),
            encoding="utf-8",
        )
        self._tts_wrapper.chmod(0o755)

        write_openclaw_config(
            self.state_dir,
            proxy_base_url=self.proxy_base_url,
            workspace=self.workspace,
            model=BENCH_MODEL,
            gateway_auth_token=self._token,
            extra=self._voice_config(),
        )
        self._gateway = GatewayProcess(
            state_dir=self.state_dir,
            gateway_port=self.gateway_port,
            log_path=self.results_dir / "gateway.log",
        )
        self._gateway.start()
        self._client = GatewayClient(
            f"ws://127.0.0.1:{self.gateway_port}",
            token=self._token,
            on_event=self._on_event,
            log=self._log,
        )
        self._client.connect()

    def _voice_config(self) -> dict[str, Any]:
        return {
            "tts": {
                "provider": "tts-local-cli",
                "providers": {
                    "tts-local-cli": {
                        "command": str(self._tts_wrapper),
                        "outputFormat": "wav",
                    },
                },
            },
            "plugins": {
                "enabled": True,
                # voice-call needs its STT (deepgram registers the realtime
                # transcription provider) and TTS (tts-local-cli registers the
                # speech provider) siblings loaded, or streaming has no ears
                # and no voice.
                "allow": ["voice-call", "deepgram", "tts-local-cli"],
                "entries": {
                    "voice-call": {
                        "enabled": True,
                        "config": {
                            "provider": "twilio",
                            "fromNumber": _CALLEE_NUMBER,
                            "twilio": {
                                "accountSid": "AC" + "0" * 32,
                                "authToken": "colleague-fixture-token",
                            },
                            "publicUrl": "https://oc-fixture.example",
                            "skipSignatureVerification": True,
                            "serve": {
                                "port": self._serve_port,
                                "bind": "127.0.0.1",
                                "path": "/voice/webhook",
                            },
                            "streaming": {
                                "enabled": True,
                                "provider": "deepgram",
                                "streamPath": "/voice/stream",
                                "providers": {
                                    "deepgram": {"apiKey": "${DEEPGRAM_API_KEY}"},
                                },
                            },
                            "sessionScope": "main",
                            "inboundPolicy": "open",
                            "inboundGreeting": " ",
                            "responseModel": f"openrouter/{BENCH_MODEL}",
                            "maxConcurrentCalls": 4,
                            "maxDurationSeconds": 1800,
                            "staleCallReaperSeconds": 0,
                        },
                    },
                },
            },
        }

    def seed_participants(self, participants: list[dict[str, Any]]) -> None:
        names = [str(p.get("id") or "").strip() for p in participants if p.get("id")]
        if names:
            self._cast = names

    # ── the voice transport (an inbound call on the arm's own surface) ─

    def build_voice_transport(
        self,
        *,
        scenario: str,
        assistant_identities: tuple[str, ...] = ("assistant",),
    ) -> Any:
        from colleague.harness.voice.availability import probe
        from colleague.harness.voice.phone_room import PhoneCallRoom
        from colleague.harness.voice.transport import VoiceUnavailable
        from colleague.harness.voice.tts import VoiceBank, build_provider

        if len(assistant_identities) > 1:
            raise Unsupported(
                "the openclaw-voice bridge fields one call with one assistant; "
                f"this scene wants {len(assistant_identities)} assistants",
            )
        avail = probe()
        if avail.tts_provider == "none":
            raise VoiceUnavailable(avail.reason or "no persona TTS provider")
        # The arm's own words are transcribed (it exposes no live text tap);
        # that needs the declared STT model to be configured.
        if avail.stt_provider == "none":
            raise VoiceUnavailable(
                "openclaw-voice exposes no live utterance text, so its replies "
                "must be transcribed by the declared model, but no "
                "DEEPGRAM_API_KEY is set",
            )
        bank = VoiceBank(build_provider(avail.tts_provider))
        room = PhoneCallRoom(
            room_name=f"colleague-{scenario}-phone",
            bank=bank,
            assistant_identities=assistant_identities,
            webhook_url=f"http://127.0.0.1:{self._serve_port}/voice/webhook",
            stream_base=f"ws://127.0.0.1:{self._serve_port}",
            from_number=_CALLER_NUMBER,
            to_number=_CALLEE_NUMBER,
            transcribe_assistant=True,
        )
        self._room = room
        return _SubstrateTransport(room, self)

    def join_voice_room(
        self,
        invite: Any,
        *,
        on_text: Any,
        personas: list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Ring the arm: POST the inbound webhook and connect the media stream."""
        if self._room is None:
            raise Unsupported("no voice room was built for this scenario")
        # A moment for the extension's webhook server to be listening after the
        # Gateway booted the voice-call service.
        self._await_webhook_server()
        info = self._room.ring()
        self._start_tap_tail()
        return {"surface": "openclaw_voice_call", **info}

    def _start_tap_tail(self) -> None:
        """Feed each spoken line the TTS wrapper taps to the room, in order.

        Seeked to the tap file's current end so any greeting attempt before
        the call is skipped; a NUL record is one utterance the arm voiced.
        """
        tap = self._tap_path
        room = self._room
        if tap is None or room is None:
            return
        start_at = tap.stat().st_size if tap.exists() else 0

        def tail() -> None:
            pos = start_at
            buf = b""
            while not self._tap_stop.wait(0.15):
                try:
                    if not tap.exists() or tap.stat().st_size <= pos:
                        continue
                    with open(tap, "rb") as fh:
                        fh.seek(pos)
                        chunk = fh.read()
                        pos = fh.tell()
                except OSError:
                    continue
                buf += chunk
                while b"\x00" in buf:
                    rec, buf = buf.split(b"\x00", 1)
                    text = rec.decode("utf-8", "replace").strip()
                    if text:
                        room.note_assistant_text(text)

        self._tap_thread = threading.Thread(
            target=tail, name="openclaw-tts-tap", daemon=True,
        )
        self._tap_thread.start()

    def _await_webhook_server(self, timeout: float = 60.0) -> None:
        import socket

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(
                    ("127.0.0.1", self._serve_port), timeout=2,
                ):
                    return
            except OSError:
                time.sleep(1.0)
        raise RuntimeError(
            f"the voice-call webhook server never bound :{self._serve_port} "
            "(see the gateway log)",
        )

    #: An inbound voice response is a full agent turn, which is slow (tens of
    #: seconds). The scene ends before a late answer is spoken, so the call is
    #: held open this long after the scene to capture the arm's audio — else a
    #: correct-but-late answer would be scored as silence rather than DEGRADED.
    _DRAIN_S = 45.0

    def leave_voice_room(self) -> None:
        room = self._room
        if room is None:
            return
        # Keep the call and its capture alive while any in-flight response is
        # spoken; the scorer reads the fixture recorder after this returns, so
        # audio captured during the drain still counts.
        time.sleep(self._DRAIN_S)
        try:
            room.close()
        except Exception:  # noqa: BLE001 - teardown is best-effort
            pass

    # ── teardown ──────────────────────────────────────────────────────

    def _pull_call_transcript(self) -> list[dict[str, Any]]:
        """The store's bot transcript, kept as a cross-check on the transcribed
        audio. Best-effort: `voicecall tail` prints the persisted CallRecords."""
        from colleague.arms.openclaw import extract_json, run_openclaw

        try:
            code, out = run_openclaw(
                ["voicecall", "tail", "--limit", "50"],
                state_dir=self.state_dir,
                gateway_port=self.gateway_port,
                log_path=self.results_dir / "gateway.log",
                timeout_s=30,
            )
            if code != 0:
                return [{"raw": out[-4000:]}] if out else []
            data = extract_json(out)
            if isinstance(data, dict):
                calls = data.get("calls") or data.get("entries") or []
                return calls if isinstance(calls, list) else [data]
            if isinstance(data, list):
                return data
            return [{"raw": out[-4000:]}] if out.strip() else []
        except Exception:  # noqa: BLE001 - evidence is best-effort
            return []

    def close(self) -> None:
        self._tap_stop.set()
        if self._tap_thread is not None:
            self._tap_thread.join(timeout=2)
        if self._room is not None:
            try:
                self._room.close()
            except Exception:  # noqa: BLE001
                pass
        self._call_transcript = self._pull_call_transcript()
        self._room = None
        super().close()

    def artifacts(self) -> dict[str, Any]:
        return {
            **super().artifacts(),
            "cast": list(self._cast),
            "serve_port": self._serve_port,
            "call_transcript": getattr(self, "_call_transcript", []),
        }


class _SubstrateTransport:
    def __init__(self, room: Any, session: OpenClawVoiceSession) -> None:
        self.room = room
        self.invite = room.invite()
        self._session = session

    def evidence(self) -> dict[str, Any]:
        return {
            **self.room.evidence(),
            "store_transcript": self._session._pull_call_transcript(),
        }

    def close(self) -> None:
        # The session owns the room's lifetime; see the hermes-voice note.
        return None


register("openclaw-voice", OpenClawVoiceSession)
