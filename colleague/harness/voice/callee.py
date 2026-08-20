"""The callee an arm can dial: a number the harness owns, answered by a persona.

`meeting` measures joining a room; `callflow` measures placing a call. The
arm's own telephony path stays whole — its comms layer POSTs the dial to a
provider, a voice agent is dispatched into a room, and somebody answers on
the far leg. The harness plays the *provider and the callee*, never the
caller:

- **The exchange** is a local HTTP server standing where the telephony
  gateway stands. `POST /phone/send-call` is the dial: it is recorded (the
  number dialled is scoring evidence), and if the number rings a line the
  harness owns and the scenario says somebody is in, the callee answers.
  `POST /phone/dispatch-livekit-agent` is served the way the comms service
  serves it — the LiveKit agent dispatch the arm's own call script requests —
  including the lesson the meet bridge learned the hard way: only a dispatch
  with **no job assigned** may be deleted as stale; an assigned dispatch gets
  more time (deleting one over a slow boot seated three agents in one room).
  Every other `/phone/*` POST (recording start, status writes) is accepted
  and kept as evidence.

- **The leg** is the same `VoiceRoom` the meeting track owns — persona TTS
  tracks in, arm-exact utterance capture out, the capture joining with token
  kind "egress" so an arm's livekit-agents auto-link never lands on the
  recorder. The one difference from `meeting`: the *arm* names the room (it
  arrives on the dial), so the leg is stood up per call rather than minted
  per scenario.

- **A ring-out** is the provider's no-answer status webhook. The exchange
  accepts the dial, nobody joins, and after `ring_out_s` the status is pushed
  through `status_sink` — whatever surface the arm's adapter registered for
  provider callbacks — so the arm learns nobody picked up the way it would in
  production, not by the harness whispering into its prompt.

The rule that shapes all of it is unchanged: the harness must never supply
the capability the track measures. Nothing here speaks for the arm, dials
for the arm, or hands the arm a text channel into the call.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from colleague.harness.voice.availability import probe
from colleague.harness.voice.room import VoiceRoom, _LoopThread
from colleague.harness.voice.server import ServerHandle, ensure_server
from colleague.harness.voice.transport import VoiceUnavailable
from colleague.harness.voice.tts import VoiceBank, build_provider

#: How long the phone "rings" before the callee picks up. Long enough that a
#: dial and its answer are distinct moments in the record, short enough that
#: no arm's patience is tested by the harness.
RING_S = 1.5
#: How long an unanswered line rings before the provider reports no-answer.
RING_OUT_S = 18.0
#: The dispatch-until-joined window. unify's import chain alone takes tens of
#: seconds; the meet bridge settled on the same order of patience.
DISPATCH_DEADLINE_S = 240.0
#: A dispatch older than this with no job assigned is stale and re-issued.
DISPATCH_STALE_S = 45.0


def _digits(number: str) -> str:
    return re.sub(r"\D", "", number or "")


def _same_number(a: str, b: str) -> bool:
    """Digit-wise match tolerant of +44 / 0 prefixes and spacing."""
    da, db = _digits(a), _digits(b)
    if not da or not db:
        return False
    if da == db:
        return True
    tail = min(len(da), len(db), 9)
    return tail >= 7 and da[-tail:] == db[-tail:]


@dataclass(frozen=True)
class CallInvite:
    """What an arm's dial adapter needs to point the arm at the callee.

    Nothing in here joins, speaks, or reports for the arm: `number` is who to
    call, `comms_url` is where the arm's own comms layer POSTs its dial, and
    `livekit_url` is the room server that call lands on — the same
    infrastructure access a fixture base URL is.
    """

    number: str
    comms_url: str
    livekit_url: str
    callee_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "comms_url": self.comms_url,
            "livekit_url": self.livekit_url,
            "callee_id": self.callee_id,
        }


class _ExchangeHandler(BaseHTTPRequestHandler):
    server_version = "colleague-exchange/1"

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode() or "{}")
        except Exception:  # noqa: BLE001 - a provider tolerates junk bodies
            body = {}
        callee = self.server.callee  # type: ignore[attr-defined]
        self._json(200, callee._handle_post(self.path, body))

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._json(404, {"error": "the exchange has no GET surface"})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


class HarnessCallee:
    """One scenario's callee: the number, the exchange, and the answered leg.

    Built by `build_callee`. The runner attaches the arm's dial adapter with
    `invite()`, waits on `wait_for_call()` for a live line (dialled, answered,
    and the arm's agent actually on it), and plays the scene through
    `leg` — a `VoiceRoom` the voice director drives unchanged.
    """

    def __init__(
        self,
        *,
        scenario: str,
        number: str,
        server: ServerHandle,
        bank: VoiceBank,
        answers: bool = True,
        first_speaker: str | None = None,
        transcribe_assistant: bool = True,
        ring_s: float = RING_S,
        ring_out_s: float = RING_OUT_S,
    ) -> None:
        self.scenario = scenario
        self.number = number
        self.server = server
        self.bank = bank
        self.answers = answers
        self.first_speaker = first_speaker
        self._transcribe = transcribe_assistant
        self._ring_s = ring_s
        self._ring_out_s = ring_out_s

        #: The provider's status webhook into the arm's adapter, set by the
        #: runner from whatever hooks the adapter returned at attach time.
        self.status_sink: Callable[[str], None] | None = None

        self.leg: VoiceRoom | None = None
        self._leg_lock = threading.Lock()
        self._answered = threading.Event()
        self._rang_out = threading.Event()
        self._noted_before_answer: list[str] = []
        self._timers: list[threading.Timer] = []
        self._loop: _LoopThread | None = None

        self.dials: list[dict[str, Any]] = []
        self.dispatches: list[dict[str, Any]] = []
        self.posts: list[dict[str, Any]] = []
        self.moves: list[dict[str, Any]] = []
        self._unpaired: dict[str, list[str]] = {}

        self._http = ThreadingHTTPServer(("127.0.0.1", 0), _ExchangeHandler)
        self._http.callee = self  # type: ignore[attr-defined]
        self._http_thread = threading.Thread(
            target=self._http.serve_forever,
            name="call-exchange",
            daemon=True,
        )
        self._http_thread.start()

    # ------------------------------------------------------------- surface

    @property
    def comms_url(self) -> str:
        return f"http://127.0.0.1:{self._http.server_address[1]}"

    def invite(self, callee_id: str = "") -> CallInvite:
        return CallInvite(
            number=self.number,
            comms_url=self.comms_url,
            livekit_url=self.server.url,
            callee_id=callee_id,
        )

    # ------------------------------------------------------------ exchange

    def _handle_post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if path == "/phone/send-call":
            return self._on_dial(body)
        if path == "/phone/dispatch-livekit-agent":
            return self._on_dispatch(body)
        # Recording starts, status writes: a provider accepts them; the
        # record keeps them.
        self.posts.append({"path": path, "body": body})
        return {"success": True}

    def _on_dial(self, body: dict[str, Any]) -> dict[str, Any]:
        to = str(body.get("To") or "")
        entry = {
            "from": str(body.get("From") or ""),
            "to": to,
            "room_name": str(body.get("room_name") or ""),
            "at": time.time(),
        }
        if not _same_number(to, self.number):
            entry["outcome"] = "wrong_number"
            self.dials.append(entry)
            return {
                "success": False,
                "error": f"Failed to initiate call to {to}",
            }
        sid = f"colleague-{self.scenario}-{len(self.dials)}"
        entry["call_sid"] = sid
        if not self.answers:
            entry["outcome"] = "ringing_out"
            self.dials.append(entry)
            self._later(self._ring_out_s, self._ring_out)
            return {"success": True, "call_sid": sid}
        entry["outcome"] = "answering"
        self.dials.append(entry)
        self._later(self._ring_s, self._answer, entry["room_name"])
        return {"success": True, "call_sid": sid}

    def _on_dispatch(self, body: dict[str, Any]) -> dict[str, Any]:
        entry = {
            "agent_name": str(body.get("livekit_agent_name") or ""),
            "room_name": str(body.get("room_name") or ""),
            "at": time.time(),
            "state": "accepted",
        }
        self.dispatches.append(entry)
        threading.Thread(
            target=self._dispatch_until_joined,
            args=(entry,),
            name="call-dispatch",
            daemon=True,
        ).start()
        return {"success": True}

    def _later(self, delay: float, fn: Callable[..., None], *args: Any) -> None:
        timer = threading.Timer(delay, fn, args=args)
        timer.daemon = True
        self._timers.append(timer)
        timer.start()

    # ------------------------------------------------------------ the leg

    def _answer(self, room_name: str) -> None:
        with self._leg_lock:
            if self._answered.is_set():
                return
            try:
                self.leg = self._stand_leg(room_name)
            except Exception as exc:  # noqa: BLE001 - kept as evidence
                self.posts.append(
                    {"path": "<answer failed>", "body": f"{type(exc).__name__}: {exc}"},
                )
                return
            for text in self._noted_before_answer:
                self.leg.note_assistant_text(text)
            self._noted_before_answer.clear()
            self._answered.set()
        # The provider's answered webhook: on an outbound call the arm's
        # voice agent holds its opener until the provider says the callee
        # picked up (call.py waits on `call_answered`), so a callee that
        # answers without saying so leaves the arm silent forever — found
        # live on the first straight_path run.
        self._push_status("answered")

    def _push_status(self, status: str) -> None:
        sink = self.status_sink
        if sink is None:
            return
        try:
            sink(status)
        except Exception as exc:  # noqa: BLE001 - kept as evidence
            self.posts.append(
                {
                    "path": f"<status {status} delivery failed>",
                    "body": f"{type(exc).__name__}: {exc}",
                },
            )

    def _stand_leg(self, room_name: str) -> VoiceRoom:
        avail = probe()
        room = VoiceRoom(
            room_name=room_name,
            url=self.server.url,
            api_key=self.server.api_key,
            api_secret=self.server.api_secret,
            bank=self.bank,
            assistant_identities=("assistant",),
            on_assistant_utterance=lambda _u: None,  # the director replaces this
            transcribe_assistant=self._transcribe and avail.stt_provider != "none",
        ).start()
        if self.first_speaker:
            room.prejoin_speaker(self.first_speaker)
        return room

    def _maybe_move(self, room_name: str) -> None:
        """Re-answer in the room a dispatch names, if the dial's differs.

        Both room names come from the arm (the dial from its comms layer, the
        dispatch from its call script); they agree in every healthy run. If
        they ever diverge, the leg follows the room the agent will actually
        join — provided nobody is on the line yet.
        """
        with self._leg_lock:
            leg = self.leg
            if leg is None or leg.room_name == room_name:
                return
            if leg.assistant_joined.is_set():
                return
            self.moves.append({"from": leg.room_name, "to": room_name})
            self._answered.clear()
            self.leg = None
        leg.close()
        self._answer(room_name)

    def _ring_out(self) -> None:
        if self._answered.is_set():
            return
        self._rang_out.set()
        self._push_status("no-answer")

    # ----------------------------------------------------------- dispatch

    def _dispatch_until_joined(self, entry: dict[str, Any]) -> None:
        """The comms service's half of the dispatch, done honestly.

        Create the dispatch once the worker has registered, then wait for a
        participant that is neither harness apparatus nor a persona speaker.
        A dispatch that produces no join within its window is deleted and
        re-issued **only when no job is assigned** — deleting a dispatch does
        not kill a job a slow-booting worker has already taken, and the meet
        track paid for that lesson with a three-agent chorus.
        """
        if self.answers:
            self._maybe_move(entry["room_name"])
        loop = self._ensure_loop()
        try:
            joined = loop.run(
                self._dispatch_async(entry["agent_name"], entry["room_name"]),
                timeout=DISPATCH_DEADLINE_S + 30,
            )
        except Exception as exc:  # noqa: BLE001 - kept as evidence
            entry["state"] = f"failed: {type(exc).__name__}: {exc}"
            return
        entry["state"] = f"joined: {joined}" if joined else "never joined"

    def _ensure_loop(self) -> _LoopThread:
        with self._leg_lock:
            if self._loop is None:
                self._loop = _LoopThread()
            return self._loop

    async def _dispatch_async(self, agent_name: str, room_name: str) -> str:
        import asyncio

        from livekit import api as lk_api

        url = self.server.url.replace("ws://", "http://").replace("wss://", "https://")
        lk = lk_api.LiveKitAPI(url, self.server.api_key, self.server.api_secret)
        dispatch_id = ""
        dispatch_born = 0.0
        try:
            loop_time = asyncio.get_event_loop().time
            deadline = loop_time() + DISPATCH_DEADLINE_S
            while loop_time() < deadline:
                try:
                    resp = await lk.room.list_participants(
                        lk_api.ListParticipantsRequest(room=room_name),
                    )
                    for p in resp.participants:
                        if p.identity == "harness-capture" or p.identity.startswith(
                            "persona-",
                        ):
                            continue
                        return p.identity
                except Exception:  # noqa: BLE001 - room may not exist yet
                    pass
                if dispatch_id and loop_time() - dispatch_born > DISPATCH_STALE_S:
                    assigned = True
                    try:
                        listed = await lk.agent_dispatch.list_dispatch(room_name)
                        assigned = any(
                            getattr(d, "id", "") == dispatch_id
                            and bool(getattr(getattr(d, "state", None), "jobs", ()))
                            for d in listed
                        )
                    except Exception:  # noqa: BLE001 - unreadable ≠ stale
                        pass
                    if assigned:
                        dispatch_born = loop_time()
                    else:
                        try:
                            await lk.agent_dispatch.delete_dispatch(
                                dispatch_id,
                                room_name,
                            )
                        except Exception:  # noqa: BLE001 - already gone is fine
                            pass
                        dispatch_id = ""
                if not dispatch_id:
                    try:
                        created = await lk.agent_dispatch.create_dispatch(
                            lk_api.CreateAgentDispatchRequest(
                                agent_name=agent_name,
                                room=room_name,
                                metadata="",
                            ),
                        )
                        dispatch_id = getattr(created, "id", "") or "created"
                        dispatch_born = loop_time()
                    except Exception:  # noqa: BLE001 - worker not registered yet
                        pass
                await asyncio.sleep(2)
        finally:
            await lk.aclose()
        return ""

    # ------------------------------------------------------------- runner

    def note_assistant_text(self, text: str) -> None:
        """The arm's exact spoken text, buffered until the line is answered."""
        with self._leg_lock:
            leg = self.leg
            if leg is None:
                if (text or "").strip():
                    self._noted_before_answer.append(text)
                return
        leg.note_assistant_text(text)

    def wait_for_call(self, timeout: float = DISPATCH_DEADLINE_S) -> VoiceRoom | None:
        """A live line: dialled, answered, and the arm's agent on it.

        Returns None when the line rang out (the no-answer scenarios), when
        no dial ever arrived, or when the arm's agent never made it into the
        room — the caller reads the evidence to tell those apart.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._rang_out.is_set():
                return None
            leg = self.leg if self._answered.is_set() else None
            if leg is not None and leg.assistant_joined.wait(timeout=0.5):
                return leg
            if leg is None:
                time.sleep(0.25)
        return None

    def hang_up(self) -> None:
        """The callee puts the phone down; the arm's agent sees the leg drop."""
        with self._leg_lock:
            leg = self.leg
            self.leg = None
            self._answered.clear()
        if leg is not None:
            # Text the arm handed over that never paired with a captured
            # audio segment is kept: it is what tells a capture failure
            # apart from an arm that genuinely never spoke.
            with leg._lock:
                self._unpaired = {
                    who: [t for t, _ in queue]
                    for who, queue in leg._noted_texts.items()
                    if queue
                }
            leg.close()

    # ----------------------------------------------------------- lifecycle

    def evidence(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "answers": self.answers,
            "dials": list(self.dials),
            "dispatches": [dict(d) for d in self.dispatches],
            "rang_out": self._rang_out.is_set(),
            "moves": list(self.moves),
            "unpaired_arm_texts": {k: list(v) for k, v in self._unpaired.items()},
            "other_posts": list(self.posts),
            "url": self.server.url,
            "persona_tts": self.bank.metering(),
        }

    def close(self) -> None:
        for timer in self._timers:
            timer.cancel()
        self.hang_up()
        try:
            self._http.shutdown()
            self._http.server_close()
        except Exception:  # noqa: BLE001 - teardown is best-effort
            pass
        if self._loop is not None:
            self._loop.close()


def build_callee(
    *,
    scenario: str,
    number: str,
    answers: bool = True,
    first_speaker: str | None = None,
) -> HarnessCallee:
    """A callee for this scenario, or `VoiceUnavailable` with the reason."""
    if not number:
        raise VoiceUnavailable("the scenario declares no callee number to own")
    avail = probe()
    if not avail.usable:
        raise VoiceUnavailable(avail.reason or "voice transport unavailable")
    try:
        server = ensure_server()
    except RuntimeError as exc:
        raise VoiceUnavailable(str(exc)) from exc
    return HarnessCallee(
        scenario=scenario,
        number=number,
        server=server,
        bank=VoiceBank(build_provider(avail.tts_provider)),
        answers=answers,
        first_speaker=first_speaker,
    )
