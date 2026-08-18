"""Persona voices — the harness rendering the *people*, never the assistant.

A scripted beat is rendered once and cached by content hash, because the same
line is spoken byte-for-byte on every repeat and re-synthesising it wastes
tokens and adds jitter. An elicited or reworded line (a live role answering
the assistant) is rendered fresh, since its text is not known in advance.

The provider is a declared, swappable module. Cartesia is used when a key is
present; macOS `say` is the offline fallback so the transport can run with no
third-party account, the same discipline as the local fixture servers. Every
byte a provider produces is PCM: signed 16-bit little-endian, mono, at
`SAMPLE_RATE`, which is what the room publishes.

Persona tokens/seconds are the *environment's* cost and are metered here,
apart from the arm, exactly as `PersonaPool` meters the persona model.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import urllib.request
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The one audio format the room and every provider agree on.
SAMPLE_RATE = 48000
CHANNELS = 1
SAMPLE_WIDTH = 2  # bytes; s16le

CARTESIA_URL = "https://api.cartesia.ai/tts/bytes"
CARTESIA_VERSION = "2025-04-16"
CARTESIA_MODEL = os.environ.get("COLLEAGUE_TTS_MODEL", "sonic-2")

#: Distinct Cartesia voices, so speaker attribution in the room is a real
#: problem. Assigned round-robin to personas as they first speak.
_CARTESIA_VOICES = (
    "47c38ca4-5f35-497b-b1a3-415245fb35e1",  # Daniel — masculine
    "829ccd10-f8b3-43cd-b8a0-4aeaa81f3b30",  # Linda — feminine
    "30894953-bcce-41fe-892c-15ce19c843ff",  # Parker — masculine
    "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4",  # Skylar — feminine
    "62ae83ad-4f6a-430b-af41-a9bede9286ca",  # Gemma — feminine
)

#: Distinct macOS `say` voices for the offline path.
_SAY_VOICES = ("Daniel", "Samantha", "Rishi", "Karen", "Fred", "Moira")


class TTSProvider:
    """Text to PCM. Subclasses declare a name and render one clip."""

    name = "abstract"
    sample_rate = SAMPLE_RATE

    def voices(self) -> tuple[str, ...]:
        raise NotImplementedError

    def _render(self, text: str, voice: str) -> bytes:
        raise NotImplementedError


class NullTTS(TTSProvider):
    """Silence of the right duration — for tests that need no real audio."""

    name = "null"

    def voices(self) -> tuple[str, ...]:
        return tuple(f"null-{i}" for i in range(6))

    def _render(self, text: str, voice: str) -> bytes:
        # ~60ms per word of silence, so timing still advances plausibly.
        words = max(1, len(text.split()))
        samples = int(self.sample_rate * 0.06 * words)
        return b"\x00\x00" * samples


class SayTTS(TTSProvider):
    """macOS `say`, rendered to s16le@48k. Offline, distinct system voices."""

    name = "say"

    def voices(self) -> tuple[str, ...]:
        return _SAY_VOICES

    def _render(self, text: str, voice: str) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = tmp.name
        try:
            subprocess.run(
                [
                    "say",
                    "-v",
                    voice,
                    "--data-format=LEI16@48000",
                    "-o",
                    path,
                    text,
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
            with wave.open(path, "rb") as w:
                frames = w.readframes(w.getnframes())
            return frames
        finally:
            Path(path).unlink(missing_ok=True)


class CartesiaTTS(TTSProvider):
    """Cartesia sonic, s16le@48k over HTTP. Reads CARTESIA_API_KEY from env."""

    name = "cartesia"

    def __init__(self) -> None:
        self._key = os.environ["CARTESIA_API_KEY"]

    def voices(self) -> tuple[str, ...]:
        return _CARTESIA_VOICES

    def _render(self, text: str, voice: str) -> bytes:
        payload = {
            "model_id": CARTESIA_MODEL,
            "transcript": text,
            "voice": {"mode": "id", "id": voice},
            "language": "en",
            "output_format": {
                "container": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": SAMPLE_RATE,
            },
        }
        req = urllib.request.Request(
            CARTESIA_URL,
            data=json.dumps(payload).encode(),
            headers={
                "X-API-Key": self._key,
                "Cartesia-Version": CARTESIA_VERSION,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.read()


def build_provider(name: str) -> TTSProvider:
    if name == "cartesia":
        return CartesiaTTS()
    if name == "say":
        return SayTTS()
    if name == "null":
        return NullTTS()
    raise ValueError(f"unknown TTS provider {name!r}")


@dataclass
class VoiceBank:
    """A provider plus a per-persona voice assignment and a content cache.

    The cache keys on (provider, voice, text) so a scripted beat is rendered
    once per run and reused across repeats. It also holds the metering: how
    many clips and how many seconds of audio the environment produced, kept
    apart from the arm.
    """

    provider: TTSProvider
    _voice_by_who: dict[str, str] = field(default_factory=dict)
    _cache: dict[str, bytes] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    clips: int = 0
    cached_hits: int = 0
    seconds: float = 0.0

    def voice_for(self, who: str) -> str:
        with self._lock:
            if who not in self._voice_by_who:
                pool = self.provider.voices()
                self._voice_by_who[who] = pool[len(self._voice_by_who) % len(pool)]
            return self._voice_by_who[who]

    def render(self, who: str, text: str) -> bytes:
        voice = self.voice_for(who)
        key = hashlib.sha256(
            f"{self.provider.name}|{voice}|{text}".encode(),
        ).hexdigest()
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            with self._lock:
                self.cached_hits += 1
            return cached
        pcm = self.provider._render(text, voice)
        with self._lock:
            self._cache[key] = pcm
            self.clips += 1
            self.seconds += len(pcm) / (SAMPLE_RATE * SAMPLE_WIDTH)
        return pcm

    def metering(self) -> dict[str, Any]:
        with self._lock:
            return {
                "provider": self.provider.name,
                "clips_rendered": self.clips,
                "cache_hits": self.cached_hits,
                "audio_seconds": round(self.seconds, 3),
                "voices": dict(self._voice_by_who),
            }
