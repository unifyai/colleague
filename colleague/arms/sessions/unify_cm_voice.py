"""The unify-cm arm's voice surface: its own agent, into the harness's room.

The CM's multi-party room is `unify_meet` — a LiveKit room its fast brain
(`unify/conversation_manager/medium_scripts/call.py`) joins as a participant,
running a structured `silence | defer | smalltalk | continuation | hang_up`
decision per turn with a group-call block at two or more other participants.
That machinery is the thing `meeting` exists to measure over voice, so the
bridge drives it whole rather than reimplementing any of it:

- `cm.call_manager.start_unify_meet(...)` — the production entry point — is
  called with the harness room's name and a participant roster. With no
  persistent worker in this in-process boot it takes its own subprocess
  fallback (`_start_call_subprocess`), spawning `call.py dev <room> ...`
  wired to the CM through the real IPC socket, exactly as the CM does when
  its worker pool is down.
- The spawned worker registers with the harness's LiveKit server under the
  room's name and waits for a dispatch. In production that dispatch comes
  from the comms service; here the comms service does not exist (its POST
  fails non-fatally, as `dispatch_livekit_agent` is written to), so the
  bridge issues the same dispatch through the LiveKit API directly.
- The assistant's utterance text is taken from the arm itself: every line
  the fast brain speaks is published as `OutboundUnifyMeetUtterance` on
  `app:comms:unify_meet_utterance` (the subprocess's events republish onto
  the CM broker through the socket server), and its `content` is the exact
  string the TTS was given. The bridge hands that to the room's capture, so
  scoring reads the arm's own words — never a transcription of them.

Deliberately not pinned: the fast brain's model *is* pinned to the bench
model (`UNIFY_MODEL`), overriding the product's smaller default — rule 6,
identical model across arms. The product ships a mini model in this seat for
latency; if the bench model makes unify slower to the floor, that is a real
consequence of the rule and belongs in the write-up, stated, not hidden.

Metering caveat, stated: the fast brain runs in the worker subprocess, whose
LLM calls do not pass through the in-process ledger. Slow-brain calls remain
metered; the worker's own logs are the evidence for fast-brain spend until
the ledger learns to reach across processes.

This module is the delimited voice extension of `unify_cm_session.py`; the
session file itself carries only the two-line delegation, because another
stream owns its text-side behaviour.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Callable

#: The LiveKit dev server's well-known credentials, valid only on loopback.
#: The harness's `voice.server` starts that server; the CM needs API access
#: to it because dispatching its own agent is how its surface joins a room.
_DEV_URL = "ws://127.0.0.1:7880"
_DEV_KEY = "devkey"
_DEV_SECRET = "secret"

_UTTERANCE_CHANNEL = "app:comms:unify_meet_utterance"


class UnifyCMVoiceBridge:
    """One joined room per bridge; built by the session's `join_voice_room`."""

    def __init__(self, session: Any) -> None:
        self._session = session
        self._on_text: Callable[[str], None] | None = None
        self._orig_publish: Any = None
        self._room_name: str = ""
        self._joined = False

    # ------------------------------------------------------------------ join

    def join(
        self,
        invite: Any,
        *,
        on_text: Callable[[str], None],
        personas: list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        session = self._session
        assert session._loop is not None and session._cm is not None
        wanted = tuple(getattr(invite, "assistant_identities", ()) or ())
        if len(wanted) > 1:
            # Two CM instances on one call is exactly what MeetFloor exists
            # for, but this bridge boots one CM and dispatches one agent.
            # Joining once and letting the second seat stay silently empty
            # would score the floor protocol without ever exercising it.
            from colleague.harness.session import Unsupported

            raise Unsupported(
                "the unify-cm bridge fields one assistant instance per call; "
                f"this scene wants {len(wanted)} ({', '.join(wanted)})",
            )
        self._on_text = on_text
        self._room_name = invite.room_name

        self._prime_voice_env(invite.url)
        self._tap_utterances()
        session._loop.run(self._start_meet(list(personas)), timeout=120)
        joined_as = session._loop.run(
            self._dispatch_until_joined(list(personas)),
            timeout=240,
        )
        self._joined = True
        return {"room": self._room_name, "identity": joined_as, "surface": "unify_meet"}

    def _prime_voice_env(self, url: str) -> None:
        """Environment the CM's dispatch path and its worker subprocess read.

        LIVEKIT_* is infrastructure access to the harness's room server, the
        voice analogue of a fixture base URL. The fast brain is pinned to the
        bench model — the same pin `_prime_environment` applies to the slow
        brain — because rule 6 wants one model across arms; the product's own
        default in this seat is a smaller model, and the consequence of the
        pin (whatever it is) belongs in results, not in a quiet divergence.
        """
        os.environ["LIVEKIT_URL"] = url
        if url == _DEV_URL:
            os.environ.setdefault("LIVEKIT_API_KEY", _DEV_KEY)
            os.environ.setdefault("LIVEKIT_API_SECRET", _DEV_SECRET)
        bench_model = (os.environ.get("UNIFY_MODEL") or "").strip()
        if bench_model:
            for key in (
                "UNIFY_CONVERSATION_FAST_BRAIN_MODEL",
                "UNITY_CONVERSATION_FAST_BRAIN_MODEL",
            ):
                if not (os.environ.get(key) or "").strip():
                    os.environ[key] = bench_model

    def _tap_utterances(self) -> None:
        """Compose over the session's broker tap to hand utterance text out.

        The worker's events reach the CM broker through the IPC socket
        server's republish (`domains/ipc_socket.py`), so wrapping
        `event_broker.publish` sees every spoken line exactly once.
        """
        cm = self._session._cm
        self._orig_publish = cm.event_broker.publish
        orig = self._orig_publish
        on_text = self._on_text

        async def tapping_publish(channel: str, message: str) -> int:
            if channel == _UTTERANCE_CHANNEL and on_text is not None:
                try:
                    content = str(json.loads(message).get("content") or "")
                except Exception:  # noqa: BLE001 - non-JSON payloads pass through
                    content = ""
                if content.strip():
                    on_text(content)
            return await orig(channel, message)

        cm.event_broker.publish = tapping_publish

    async def _start_meet(self, personas: list[str]) -> None:
        session = self._session
        cm = session._cm
        boss = session._contact_dict(session._M.SESSION_DETAILS.boss_contact_id)
        roster = self._roster(personas, boss)
        await cm.call_manager.start_unify_meet(
            boss,
            boss,
            self._room_name,
            opening_config=None,
            call_session_id=None,
            participants=roster,
        )

    def _roster(
        self,
        personas: list[str],
        boss: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """The room roster the fast brain reads people from, humans only.

        Built from the same seeded contacts the text tracks use, so the
        arm's world and the room's cast agree.
        """
        roster: list[dict[str, Any]] = []
        seen: set[Any] = set()
        for pid in personas:
            contact = self._session._correspondents.get(pid)
            if not contact or contact.get("contact_id") in seen:
                continue
            seen.add(contact.get("contact_id"))
            name = " ".join(
                s
                for s in (contact.get("first_name"), contact.get("surname"))
                if s and str(s).strip()
            )
            roster.append(
                {
                    "kind": "human",
                    "display_name": name or pid.title(),
                    "contact_id": contact.get("contact_id"),
                },
            )
        if boss.get("contact_id") not in seen:
            roster.append(
                {
                    "kind": "human",
                    "display_name": f"{boss.get('first_name', '')} {boss.get('surname', '')}".strip(),
                    "contact_id": boss.get("contact_id"),
                },
            )
        return roster

    async def _dispatch_until_joined(self, personas: list[str]) -> str:
        """Issue the LiveKit dispatch the comms service would have, and wait.

        The worker registers under the room's name (no call session id, so
        `call.py`'s per-assistant naming is bypassed and the name is
        predictable). Dispatch attempts are retried while the worker boots —
        unify's import chain takes tens of seconds — and stop at the first
        success, so a slow boot never produces two agents in the room.
        """
        from livekit import api as lk_api

        harness_identities = {"harness-capture"} | {f"persona-{p}" for p in personas}
        url = (
            os.environ["LIVEKIT_URL"]
            .replace("ws://", "http://")
            .replace(
                "wss://",
                "https://",
            )
        )
        lk = lk_api.LiveKitAPI(
            url,
            os.environ["LIVEKIT_API_KEY"],
            os.environ["LIVEKIT_API_SECRET"],
        )
        try:
            dispatched = False
            deadline = asyncio.get_event_loop().time() + 210
            while asyncio.get_event_loop().time() < deadline:
                try:
                    resp = await lk.room.list_participants(
                        lk_api.ListParticipantsRequest(room=self._room_name),
                    )
                    for p in resp.participants:
                        if p.identity not in harness_identities:
                            return p.identity
                except Exception:  # noqa: BLE001 - room may not exist yet
                    pass
                if not dispatched:
                    try:
                        await lk.agent_dispatch.create_dispatch(
                            lk_api.CreateAgentDispatchRequest(
                                agent_name=self._room_name,
                                room=self._room_name,
                                metadata="",
                            ),
                        )
                        dispatched = True
                    except Exception:  # noqa: BLE001 - worker not registered yet
                        pass
                await asyncio.sleep(2)
        finally:
            await lk.aclose()
        raise RuntimeError(
            f"the CM's voice agent never joined room {self._room_name!r} "
            "(worker registered: "
            + ("yes, dispatch created" if dispatched else "no dispatch accepted")
            + ")",
        )

    # ----------------------------------------------------------------- leave

    def leave(self) -> None:
        session = self._session
        if session._loop is None or session._cm is None:
            return
        try:
            session._loop.run(self._end(), timeout=60)
        except Exception:  # noqa: BLE001 - teardown is best-effort
            pass
        if self._orig_publish is not None:
            session._cm.event_broker.publish = self._orig_publish
            self._orig_publish = None
        self._joined = False

    async def _end(self) -> None:
        cm = self._session._cm
        try:
            await cm.call_manager.end_call("scenario end")
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(1.0)
        try:
            await cm.call_manager.cleanup_call_proc()
        except Exception:  # noqa: BLE001
            pass
