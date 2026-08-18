"""The voice transport: a room, persona voices, capture, and a director.

`meeting` was written for voice and built on a text room, with the scenes,
roles, checks and scorer kept medium-agnostic. This package is the transport
swap — a beat plays through a persona's audio track at the same waypoint, the
assistant joins the room and speaks through its own voice, and the harness
captures both with timestamps so the fixture recorder witnesses every line
exactly as it did in text.

Everything here is optional and lazily imported: the `livekit` SDK, the TTS
and STT providers and their credentials all live in the environment the unify
arm already runs in, not in `colleague`'s (empty) dependency set. With none of
them present, `availability.probe()` reports why, and a run degrades to the
text room loudly rather than pretending it was voice. See `README.md`.
"""

from __future__ import annotations

from colleague.harness.voice.availability import VoiceAvailability, probe

__all__ = ["VoiceAvailability", "probe"]
