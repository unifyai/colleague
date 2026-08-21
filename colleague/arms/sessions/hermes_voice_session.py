"""hermes-agent's Discord voice channel as a `meeting` voice arm.

hermes joins a guild voice channel through its own `discord.py` client, hears
each speaker on its own SSRC, transcribes with its local Whisper, and speaks
replies back as Opus — that is the surface `meeting` measures over voice for
this arm. The harness stands up a Discord-protocol server on loopback
(`colleague.harness.voice.discord_room`) and runs the real `hermes gateway`
against it: the arm connects, is invited into the voice channel by a persona
saying `/voice join`, and holds the scene as a spoken conversation.

The split is the README's: the room, the persona voices and the capture are
the harness's; joining, hearing, deciding to speak and speaking are hermes's
own machinery, reached only through its documented surfaces (a Discord
message, the `/voice` command, the voice channel). The assistant's exact
words are taken from hermes where it speaks from text — it posts every reply
to the channel as it says it — never a transcription; the bot's own audio is
captured for the transport timestamps and kept as a transcript cross-check.

Nothing in hermes is patched. `discord.py`'s REST base and gateway URL are
class constants a `sitecustomize` shim on `PYTHONPATH` repoints at the
loopback server (`write_sitecustomize`), and the gateway runs `--no-supervise`
so that process — with the shim imported by `site` — is the one that connects.
"""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from colleague.arms.hermes import HERMES_REPO, _hermes_env, defuse_hermes_artifacts
from colleague.arms.sessions import register
from colleague.arms.sessions.cli_base import CliSession
from colleague.harness.capability import PROFILES
from colleague.harness.session import Reply, RunHandle, Unsupported

#: The meeting cast. Provisioned as Discord users in the room so any beat's
#: speaker resolves to a voice-channel member; the `/voice join` issuer must
#: be one of them (it needs a voice state for hermes to find the channel).
_DEFAULT_CAST = ["daniel", "priya", "bob"]

#: hermes imports the world on gateway boot; the connect is not instant.
_READY_TIMEOUT_S = 180.0
_MODEL = None  # resolved from BENCH_MODEL at import


#: A local, offline TTS the arm speaks with, and the exact-text tap. hermes
#: writes the spoken text to {input_path} and expects audio at {output_path};
#: `say` renders it instantly with no network (the network default, edge,
#: risked a multi-minute synthesis stall). Crucially, the wrapper is also the
#: utterance-text tap: it appends the exact string the arm chose to say —
#: NUL-separated, before synthesis — to a tap file the session pairs with the
#: audio. This is the arm's own words at the point it speaks from text, the
#: README's faithful capture, and it excludes everything hermes prints to its
#: channel but never voices (system notices, silent-reasoning lines).
_TTS_WRAPPER = """\
#!/bin/sh
in="$1"; out="$2"
text="$(cat "$in")"
printf '%s\\0' "$text" >> "{tap_path}"
say -o "$out.aiff" -- "$text" 2>/dev/null || true
ffmpeg -nostdin -loglevel error -y -i "$out.aiff" "$out" 2>/dev/null || true
rm -f "$out.aiff"
"""


def _config_yaml(model: str, tts_wrapper: str) -> str:
    return f"""\
model:
  default: "{model}"
  provider: "openrouter"
stt:
  provider: local
tts:
  provider: colleague-say
  providers:
    colleague-say:
      type: command
      command: "{tts_wrapper} {{input_path}} {{output_path}}"
      output_format: wav
group_sessions_per_user: false
approvals:
  mode: "off"
discord:
  require_mention: false
  auto_thread: false
  voice_channel_inactivity_timeout_seconds: 0
  voice_fx:
    enabled: false
"""


class _OpeningHandle(RunHandle):
    """The priming turn's handle.

    The opening message is delivered to prime the channel session (the arm
    reads /notes into its history); its reply is not scored — the scene is.
    hermes voices that opening reply as an audio attachment (a multipart
    upload), which is neither reliable to capture nor worth capturing, so the
    handle simply waits a fixed settle that covers the turn, then proceeds to
    the join. `wait` is idempotent: the runner calls it again after the scene.
    """

    #: Comfortably covers a priming turn (~15-20s of model time) plus margin.
    _SETTLE_S = 45.0

    def __init__(self, session: "HermesVoiceSession") -> None:
        self._session = session
        self._done = threading.Event()

    def wait(self, timeout: float = 900.0) -> Reply:
        if not self._done.is_set():
            time.sleep(min(timeout, self._SETTLE_S))
            self._done.set()
        return Reply(text="", ok=True)

    def interject(self, text: str, *, sender: str | None = None) -> dict[str, Any]:
        raise Unsupported(
            "hermes-voice carries the scene over the voice channel, not as text "
            "interjections; run it with --transport voice",
        )


class HermesVoiceSession(CliSession):
    arm = "hermes-voice"
    profile = PROFILES["hermes-voice"]

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self._cast: list[str] = list(_DEFAULT_CAST)
        self._room: Any = None
        self._proc: subprocess.Popen | None = None
        self._home: Path | None = None
        self._tap_path: Path | None = None
        self._boss = "daniel"
        self._gateway_up = False
        self._tap_stop = threading.Event()
        self._tap_thread: threading.Thread | None = None

    # ── lifecycle ────────────────────────────────────────────────────

    def setup(self) -> None:
        python = HERMES_REPO / ".venv" / "bin" / "python"
        if not python.exists():
            raise SystemExit(f"hermes venv missing — run `uv sync` in {HERMES_REPO}")
        # The arm's voice deps live in hermes's venv, not the harness's; probe
        # that interpreter. (The harness side needs pynacl + PyAV, checked at
        # transport-build time via the availability probe / imports.)
        import subprocess

        probe = subprocess.run(
            [
                str(python),
                "-c",
                "import importlib.util as u,sys;"
                "missing=[m for m in ('discord','nacl','faster_whisper') "
                "if u.find_spec(m) is None];"
                "sys.stdout.write(','.join(missing))",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        missing = (probe.stdout or "").strip()
        if missing:
            raise SystemExit(
                f"hermes venv lacks {missing}: install the messaging+voice extras "
                "(discord.py[voice], pynacl, faster-whisper) in "
                f"{HERMES_REPO}/.venv",
            )
        self._home = self.results_dir / "hermes_home"
        self._home.mkdir(parents=True, exist_ok=True)
        self._tap_path = self._home / "spoken_tap"
        wrapper = self._home / "tts_say.sh"
        wrapper.write_text(
            _TTS_WRAPPER.replace("{tap_path}", str(self._tap_path)),
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        (self._home / "config.yaml").write_text(
            _config_yaml(_MODEL, str(wrapper)),
            encoding="utf-8",
        )

    def seed_participants(self, participants: list[dict[str, Any]]) -> None:
        """The scene's cast, so the room provisions them as voice members."""
        names = [str(p.get("id") or "").strip() for p in participants if p.get("id")]
        if names:
            self._cast = names
            self._boss = names[0]

    # ── the voice transport (the room is on hermes's own substrate) ───

    def build_voice_transport(
        self,
        *,
        scenario: str,
        assistant_identities: tuple[str, ...] = ("assistant",),
    ) -> Any:
        from colleague.harness.voice.availability import probe
        from colleague.harness.voice.discord_room import (
            DiscordVoiceRoom,
            write_sitecustomize,
        )
        from colleague.harness.voice.transport import VoiceUnavailable
        from colleague.harness.voice.tts import VoiceBank, build_provider

        if len(assistant_identities) > 1:
            raise Unsupported(
                "the hermes-voice bridge fields one Discord bot per call; "
                f"this scene wants {len(assistant_identities)} assistants",
            )
        avail = probe()
        # Persona voices need a TTS provider; the rest of LiveKit's probe
        # (a room server, STT for the arm) does not apply to this substrate.
        if avail.tts_provider == "none":
            raise VoiceUnavailable(avail.reason or "no persona TTS provider")

        bank = VoiceBank(build_provider(avail.tts_provider))
        room = DiscordVoiceRoom(
            room_name=f"colleague-{scenario}-discord",
            bank=bank,
            assistant_identities=assistant_identities,
            personas=self._cast,
            transcribe_assistant=avail.stt_provider != "none",
        )
        room.server.start()
        self._room = room

        # Point hermes's discord.py at the loopback server, then boot it.
        shim_dir = self.results_dir / "shim"
        shim_dir.mkdir(parents=True, exist_ok=True)
        write_sitecustomize(
            shim_dir / "sitecustomize.py",
            api_base=room.server.api_base,
            gateway_url=room.server.gateway_url,
        )
        self._spawn_gateway(shim_dir)
        if not room.server.wait_identify(timeout=_READY_TIMEOUT_S):
            raise VoiceUnavailable(
                "hermes gateway never connected to the loopback Discord server",
            )
        # A moment for discord.py to finish READY / on_ready before traffic.
        time.sleep(3.0)
        return _SubstrateTransport(room)

    def _spawn_gateway(self, shim_dir: Path) -> None:
        assert self._home is not None
        env = _hermes_env(
            self._home, self.results_dir / "workspace", self.proxy_base_url,
        )
        (self.results_dir / "workspace").mkdir(parents=True, exist_ok=True)
        # PYTHONPATH carries the sitecustomize shim; the discord flags are set
        # here (env is first-writer-wins over config.yaml in hermes).
        env.update(
            {
                "PYTHONPATH": str(shim_dir),
                "DISCORD_BOT_TOKEN": "colleague-fixture-token",
                "DISCORD_ALLOW_ALL_USERS": "true",
                "DISCORD_REQUIRE_MENTION": "false",
                "DISCORD_AUTO_THREAD": "false",
                "DISCORD_COMMAND_SYNC_POLICY": "off",
            },
        )
        cmd = [
            str(HERMES_REPO / ".venv" / "bin" / "hermes"),
            "gateway",
            "run",
            "--no-supervise",
            "-v",
        ]
        log = open(self.log_path, "a", encoding="utf-8")
        self._proc = subprocess.Popen(
            cmd,
            cwd=str(HERMES_REPO),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        self._gateway_up = True

    # ── turns ─────────────────────────────────────────────────────────

    def begin(
        self,
        text: str,
        *,
        persist: bool = False,
        context: str | None = None,
        sender: str | None = None,
        images: list[str] | None = None,
    ) -> RunHandle:
        """The opening turn: prime the arm before the call.

        Delivered as a Discord message into the channel voice will bind to,
        so what the arm learns (it reads `/notes`) is in the same session the
        voice transcripts land in. Its reply is captured but not scored — the
        scene is what counts.
        """
        del persist, images
        if self._room is None:
            raise Unsupported(
                "hermes-voice requires --transport voice: no channel to prime",
            )
        from colleague.harness.session import compose

        message = compose(context, text)
        self._room.server.deliver_message(message, sender or self._boss)
        return _OpeningHandle(self)

    # ── joining the voice channel ─────────────────────────────────────

    def join_voice_room(
        self,
        invite: Any,
        *,
        on_text: Any,
        personas: list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Invite the arm into the voice channel through its own `/voice`.

        A persona in the channel says `/voice join`; hermes resolves that
        user's voice channel and connects to it. Once the voice handshake is
        done, capture is armed and the director speaks the scene.
        """
        if self._room is None:
            raise Unsupported("no voice room was built for this scenario")
        room = self._room
        room.server.deliver_message("/voice join", self._boss)
        if not room.server.wait_voice_connected(timeout=_READY_TIMEOUT_S):
            # Retry once: a join command can race a not-quite-ready client.
            room.server.deliver_message("/voice join", self._boss)
            if not room.server.wait_voice_connected(timeout=90):
                raise RuntimeError(
                    "hermes never joined the voice channel (see the gateway log)",
                )
        # Give the arm a beat to settle its receiver before the first beat.
        time.sleep(2.0)
        room.arm()
        self._start_tap_tail()
        return {"room": room.room_name, "surface": "discord_voice"}

    def _start_tap_tail(self) -> None:
        """Feed each spoken line the TTS wrapper taps to the room, in order.

        Started only after `arm()`, and seeked to the tap file's current end,
        so the priming turn's spoken reply (before the scene) is skipped and
        only scene utterances pair with scene audio.
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
            target=tail, name="hermes-tts-tap", daemon=True,
        )
        self._tap_thread.start()

    def leave_voice_room(self) -> None:
        room = self._room
        if room is not None:
            try:
                room.server.deliver_message("/voice leave", self._boss)
            except Exception:  # noqa: BLE001 - teardown is best-effort
                pass

    # ── teardown ──────────────────────────────────────────────────────

    def close(self) -> None:
        self._tap_stop.set()
        if self._tap_thread is not None:
            self._tap_thread.join(timeout=2)
        if self._room is not None:
            try:
                self._room.close()
            except Exception:  # noqa: BLE001
                pass
            self._room = None
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._proc = None
        if self._home is not None:
            try:
                defuse_hermes_artifacts(self._home)
            except Exception:  # noqa: BLE001 - teardown is best-effort
                pass
        super().close()

    def artifacts(self) -> dict[str, Any]:
        return {
            **super().artifacts(),
            "home": str(self._home) if self._home else "",
            "cast": list(self._cast),
        }


class _SubstrateTransport:
    """The `VoiceTransport` shape the runner expects, over a substrate room."""

    def __init__(self, room: Any) -> None:
        self.room = room
        self.invite = room.invite()

    def evidence(self) -> dict[str, Any]:
        return self.room.evidence()

    def close(self) -> None:
        # The session owns the room's lifetime (it outlives one scene's
        # transport for teardown/defuse); closing here would kill the gateway
        # mid-drain, so this is a no-op and `session.close()` does the work.
        return None


def _resolve_model() -> str:
    from colleague.arms.hermes import BENCH_MODEL

    return BENCH_MODEL


_MODEL = _resolve_model()

register("hermes-voice", HermesVoiceSession)
