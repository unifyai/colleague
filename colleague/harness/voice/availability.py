"""Is the voice transport usable here, and if not, exactly why.

The self-test runs with no LiveKit, no TTS credentials and no model, and must
stay green — so voice never silently substitutes for the text room. A run
that asked for voice and cannot have it degrades to text, and the *reason*
from here is what gets recorded on the run, so a text result is never read as
a voice one.

The probe is cheap and side-effect-free: it checks that the pieces exist, not
that a room can be stood up. Standing one up is the transport's job, and its
own failures are recorded the same way.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VoiceAvailability:
    """What the environment can and cannot do for voice, with reasons."""

    livekit: bool
    room_url: str
    tts_provider: str
    stt_provider: str
    reasons: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        """Enough to render personas and connect a room. STT is optional."""
        return self.livekit and bool(self.room_url) and self.tts_provider != "none"

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons) if self.reasons else ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "usable": self.usable,
            "livekit": self.livekit,
            "room_url": self.room_url,
            "tts_provider": self.tts_provider,
            "stt_provider": self.stt_provider,
            "reason": self.reason,
        }


def _livekit_importable() -> bool:
    return (
        importlib.util.find_spec("livekit") is not None
        and importlib.util.find_spec("livekit.rtc") is not None
        and importlib.util.find_spec("livekit.api") is not None
    )


def _room_url() -> str:
    """A LiveKit URL to join, from env or a local dev server's default.

    `LIVEKIT_URL` is honoured first (a real project, or a dev server on a
    non-default port). Otherwise, if a `livekit-server` binary is on PATH the
    harness can bring one up itself on the dev default, so that URL is offered
    with the dev key/secret the server prints in `--dev`.
    """
    env = (os.environ.get("LIVEKIT_URL") or "").strip()
    if env:
        return env
    if shutil.which("livekit-server"):
        return "ws://127.0.0.1:7880"
    return ""


def _tts_provider() -> tuple[str, str]:
    """The best available persona-voice renderer, and why the others are out."""
    if (os.environ.get("CARTESIA_API_KEY") or "").strip():
        return "cartesia", ""
    if shutil.which("say"):
        # macOS `say` renders offline; distinct system voices per persona.
        return "say", "no CARTESIA_API_KEY; using macOS 'say' (offline)"
    return (
        "none",
        "no CARTESIA_API_KEY and no 'say' binary — cannot render persona voices",
    )


def _stt_provider() -> tuple[str, str]:
    if (os.environ.get("DEEPGRAM_API_KEY") or "").strip():
        return "deepgram", ""
    return (
        "none",
        "no DEEPGRAM_API_KEY — an arm that exposes only audio cannot be transcribed",
    )


def probe() -> VoiceAvailability:
    reasons: list[str] = []

    livekit = _livekit_importable()
    if not livekit:
        reasons.append("the 'livekit' SDK is not importable in this interpreter")

    room_url = _room_url()
    if not room_url:
        reasons.append("no LIVEKIT_URL and no 'livekit-server' on PATH")

    tts_provider, tts_reason = _tts_provider()
    if tts_reason:
        reasons.append(tts_reason)

    stt_provider, stt_reason = _stt_provider()
    if stt_reason:
        reasons.append(stt_reason)

    return VoiceAvailability(
        livekit=livekit,
        room_url=room_url,
        tts_provider=tts_provider,
        stt_provider=stt_provider,
        reasons=tuple(reasons),
    )
