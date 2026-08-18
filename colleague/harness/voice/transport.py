"""Standing up the voice transport for one scenario, or saying why not.

The runner asks for voice; this module either assembles a `VoiceRoom` (server,
persona voice bank, capture) plus the invite the arm will join with, or
raises `VoiceUnavailable` with the exact reason, which the runner records on
the run so a text result is never read as a voice one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from colleague.harness.voice.availability import probe
from colleague.harness.voice.room import RoomInvite, VoiceRoom
from colleague.harness.voice.server import ServerHandle, ensure_server
from colleague.harness.voice.tts import VoiceBank, build_provider


class VoiceUnavailable(RuntimeError):
    """Voice was asked for and cannot be provided here; the reason is the message."""


@dataclass
class VoiceTransport:
    """One scenario's room, ready for a director and an arm."""

    room: VoiceRoom
    server: ServerHandle
    invite: RoomInvite

    def close(self) -> None:
        self.room.close()

    def evidence(self) -> dict[str, Any]:
        return {
            "room_name": self.room.room_name,
            "url": self.server.url,
            "assistant_identities": list(self.room.assistant_identities),
            "persona_tts": self.room.metering(),
        }


def build_transport(
    *,
    scenario: str,
    assistant_identities: tuple[str, ...] = ("assistant",),
    transcribe_assistant: bool = True,
) -> VoiceTransport:
    """A room for this scenario, or `VoiceUnavailable` with the reason."""
    avail = probe()
    if not avail.usable:
        raise VoiceUnavailable(avail.reason or "voice transport unavailable")

    try:
        server = ensure_server()
    except RuntimeError as exc:
        raise VoiceUnavailable(str(exc)) from exc

    bank = VoiceBank(build_provider(avail.tts_provider))
    room_name = f"colleague-{scenario}-{uuid.uuid4().hex[:8]}"
    room = VoiceRoom(
        room_name=room_name,
        url=server.url,
        api_key=server.api_key,
        api_secret=server.api_secret,
        bank=bank,
        assistant_identities=assistant_identities,
        on_assistant_utterance=lambda _u: None,  # the director replaces this
        transcribe_assistant=transcribe_assistant and avail.stt_provider != "none",
    ).start()
    return VoiceTransport(
        room=room,
        server=server,
        invite=room.invite(),
    )
