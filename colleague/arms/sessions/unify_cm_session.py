"""The unify arm: the ConversationManager, the door a person talks through.

An earlier "v0" arm drove `CodeActActor.act` directly, which skipped the
layer this benchmark is about: senders as first-class contacts, replies as
Sent events addressed to someone, silence as an explicit `wait` decision,
and mid-task steering as brain tools bound to a specific in-flight action.
This adapter boots a real ConversationManager in-process -- the same recipe
the CM integration tests and the OSS sandbox use -- and feeds it inbound
message events, with a real CodeActActor doing the dispatched work.

Driving mode is the stepped one from `tests/conversation_manager/
cm_test_driver.py`, vendored here because `tests/` is not an importable
package from this repo: each inbound event is handled, then the slow brain
runs until it calls `wait`. Actor work dispatched during a step runs
genuinely async on the loop; its completion flows back through the event
broker and the CM's own background event loop, which is exactly the
production path. `RunHandle.wait` therefore drains in layers -- inbound queue
empty, brain quiescent (debouncer idle, no pending LLM requests), in-flight
actions resolved or parked awaiting input -- before assembling the turn's
reply from the Sent events addressed to the triggering contact.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import os
import re
import threading
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from colleague.arms.sessions import register
from colleague.harness.capability import PROFILES
from colleague.harness.session import ArmSession, Reply, RunHandle, compose

REQUIRED_ENV = ("ORCHESTRA_URL", "UNIFY_KEY")

#: Same fake identity the CM test-suite pins so the send tools exist at all:
#: `prompt_builders` gates `send_email` / `send_sms` on a non-blank assistant
#: email/number, and a blank `ASSISTANT_NUMBER=` in .env defeats setdefault.
_ASSISTANT_IDENTITY = {
    "ASSISTANT_EMAIL": "assistant@test.example.com",
    "ASSISTANT_NUMBER": "+15550001000",
    "ASSISTANT_WHATSAPP_NUMBER": "+15550001000",
}

#: Every track's roster names one person as "the person you work for":
#: Daniel Okafor. The CM has a *structural* boss — the contact behind
#: `SESSION_DETAILS.boss_contact_id`, whose row is rendered into the system
#: prompt's identity block ("{user_name} is my boss and priority"). Left
#: alone, that row is provisioned from the operator's own Orchestra account
#: (`get_user_basic_info()`) and the operator's `.env` USER_* values, so the
#: brain works for the wrong person while the roster's boss arrives as mere
#: message text. First observed as custody refusals deferring to the
#: operator by name ("without authorization from <operator>").
_BOSS_FIRST_NAME = "Daniel"
_BOSS_SURNAME = "Okafor"
_BOSS_EMAIL = "daniel@northwind.example"
#: Sender ids/spellings the tracks use for the boss; all resolve to the
#: boss contact instead of minting a lookalike correspondent.
_BOSS_SENDER_KEYS = {"daniel", "daniel okafor", _BOSS_EMAIL}

#: Force-set (never setdefault): the operator's shell or repo `.env` must
#: not reach SESSION_DETAILS.user under any circumstance.
_BOSS_IDENTITY_ENV = {
    "USER_ID": "",
    "USER_FIRST_NAME": _BOSS_FIRST_NAME,
    "USER_SURNAME": _BOSS_SURNAME,
    "USER_EMAIL": _BOSS_EMAIL,
    "USER_NUMBER": "",
    "USER_WHATSAPP_NUMBER": "",
}

#: Events whose content constitutes a message delivered to a correspondent.
_MESSAGE_SENT_TYPES = (
    "UnifyMessageSent",
    "SMSSent",
    "WhatsAppSent",
    "EmailSent",
    "ApiMessageSent",
)

#: Additional egress worth keeping as turn evidence, but not reply text.
_EVIDENCE_TYPES = _MESSAGE_SENT_TYPES + ("PhoneCallSent", "ActorHandleStarted")

_STEERING_PREFIXES = ("interject", "stop", "pause", "resume", "ask", "act")


def require_env() -> None:
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        raise SystemExit(
            f"missing required environment: {', '.join(missing)}. "
            "The unify-cm arm runs against staging Orchestra in an isolated "
            "context.",
        )


def _prime_environment() -> None:
    """Env that must be set before any unify module is imported.

    unify's SETTINGS and SESSION_DETAILS read the environment once, at
    import/instantiation time; anything set later is silently ignored. The
    CM test conftest learned each of these the hard way (its own comments
    tell the stories); this mirrors them.
    """
    for key, value in _ASSISTANT_IDENTITY.items():
        if not (os.environ.get(key) or "").strip():
            os.environ[key] = value
    # Production persists the Comms stream (EVENTBUS_PUBLISHING_ENABLED=true
    # in deployment; the setting defaults off for tests), and conversation
    # hydration after a pod reboot reads exactly that stream. A person-shaped
    # benchmark models production, and the sleeping weeks reboot the CM
    # between requests — without this, a rebooted week finds no persisted
    # conversation and wakes amnesiac (2026-08-22: weeks 2–4 failed, hunting
    # for a spec that lived in the unpersisted week-1 exchange). setdefault
    # so an operator can still study the amnesiac regime deliberately.
    os.environ.setdefault("EVENTBUS_PUBLISHING_ENABLED", "true")
    # The benchmark's boss identity, before SESSION_DETAILS instantiates and
    # before the CM's load_dotenv() can pull the operator's own USER_* values
    # out of the unify repo's .env (load_dotenv never overrides existing
    # keys, so setting these first is what keeps the pollution out).
    for key, value in _BOSS_IDENTITY_ENV.items():
        os.environ[key] = value
    os.environ.setdefault("UNITY_CONVERSATION_JOB_NAME", "test_job")
    # The CM boot binds authoritative ownership when a platform assistant id
    # is present, and refuses to start without the matching Orchestra record.
    # This arm runs the deliberately unassigned benchmark context; a stray
    # ASSISTANT_ID from the unify repo's .env (which the CM's own
    # load_dotenv() pulls in later, without overriding existing keys) would
    # demand a record that does not exist. Pin it empty unless the operator
    # explicitly exported one.
    os.environ.setdefault("ASSISTANT_ID", "")
    # The sanctioned way to run the CM under a pre-bound context root:
    # SETTINGS.TEST makes resolve_runtime_context_root() honor the active
    # context this arm binds in setup(). Without it, bind_runtime_context_root
    # treats the unassigned-identity root "default/0" as authoritative and
    # routes lazily-resolved storage to the PROJECT root — cross-run contact
    # pollution, duplicate boss rows, and doubled default/0 path segments.
    # The CM conftest pins this too (tests/conversation_manager/conftest.py).
    os.environ.setdefault("TEST", "true")
    # No orchestrator respawns this process; never let the CM shut itself
    # down between scenario turns.
    os.environ.setdefault("UNITY_INACTIVITY_TIMEOUT_SECONDS", "0")
    os.environ.setdefault("UNITY_MEMORY_ENABLED", "false")
    # Pin the slow brain to the bench model. SLOW_BRAIN_MODEL has a non-empty
    # deployment default, so without this the conversation layer would run a
    # different model from the actor and the arm's token column would mix two
    # models nobody chose.
    if not (os.environ.get("UNITY_CONVERSATION_SLOW_BRAIN_MODEL") or "").strip():
        bench_model = (os.environ.get("UNIFY_MODEL") or "").strip()
        if bench_model:
            os.environ["UNITY_CONVERSATION_SLOW_BRAIN_MODEL"] = bench_model


class _LoopThread:
    """An asyncio loop living on its own thread."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run,
            name="unify-cm-loop",
            daemon=True,
        )
        self._ready = threading.Event()
        self._thread.start()
        self._ready.wait(timeout=10)

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.call_soon(self._ready.set)
        self.loop.run_forever()

    def run(self, coro, timeout: float = 900.0):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=timeout)

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=5)


#: Mirrors the contextvar trick in cm_test_driver: the patched
#: `request_llm_run` must capture requests made by the step's own task tree
#: while letting genuinely-background handlers (the CM's `wait_for_events`
#: task) fall through to the real scheduling path.
_step_llm_requests: contextvars.ContextVar[list | None] = contextvars.ContextVar(
    "_cm_step_llm_requests",
    default=None,
)


class _Inbound:
    """One queued inbound message and the bookkeeping to score its turn."""

    def __init__(self, kind: str, turn: int, event: Any, contact_id: int) -> None:
        self.kind = kind
        self.turn = turn
        self.event = event
        self.contact_id = contact_id
        self.done = threading.Event()
        self.error: str = ""
        self.egress_start = 0
        self.tools_start = 0
        # Egress index past which clarification questions have been answered.
        self.clar_seen = 0
        self.clar_rounds = 0


class UnifyCMRunHandle(RunHandle):
    """One inbound turn making its way through the ConversationManager."""

    def __init__(self, session: "UnifyCMSession", item: _Inbound) -> None:
        self._session = session
        self._item = item

    def wait(self, timeout: float = 900.0) -> Reply:
        return self._session._wait_turn(self._item, timeout)

    def interject(self, text: str, *, sender: str | None = None) -> dict[str, Any]:
        return self._session._interject(text, sender=sender)

    def stop(self) -> None:
        self._session._stop_in_flight()

    @property
    def done(self) -> bool:
        return self._item.done.is_set()


class UnifyCMSession(ArmSession):
    profile = PROFILES["unify-cm"]

    #: The conversational runner wants every turn's LLM calls attributed to
    #: `turn_<n>`, so `begin` marks a ledger boundary itself. A fire-series
    #: driver owns its own labels (`setup`, `fire_3`, `message_4`) and flips
    #: this off so its per-fire attribution is not fragmented by turn marks.
    auto_turn_boundaries = True

    #: Cap on brain steps within one stepped turn (the test driver uses 5;
    #: multi-send turns in the wild occasionally need more).
    MAX_BRAIN_STEPS = 8
    #: Bounded clarification rounds per turn, so a chatty closing question
    #: cannot ping-pong with the responder forever.
    MAX_CLARIFICATION_ROUNDS = 3
    #: Ceiling on a single stepped inbound event, independent of wait().
    STEP_TIMEOUT = 600.0

    def __init__(
        self,
        *,
        run_id: str | None = None,
        track: str = "colleague",
        project: str | None = None,
        ledger: Any = None,
        results_dir: Any = None,
    ) -> None:
        self.run_id = run_id or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H-%M-%SZ",
        )
        self.track = track
        self.project = project or os.environ.get("COLLEAGUE_PROJECT", "Benchmarks")
        self.ledger = ledger
        self._proxy: Any = None
        self.results_dir = Path(results_dir) if results_dir else None
        self.context = ""
        self._loop: _LoopThread | None = None
        self._cm: Any = None
        self._M: SimpleNamespace | None = None  # cached unify modules/classes
        self._queue: asyncio.Queue | None = None
        self._consumer: asyncio.Task | None = None
        self._processing = False
        self._llm_active = 0
        self._egress_log: list[dict[str, Any]] = []
        self._tool_log: list[str] = []
        self._turn_records: list[dict[str, Any]] = []
        self._correspondents: dict[str, dict[str, Any]] = {}
        self._responder = None
        self._clarifications: list[dict[str, Any]] = []
        self._turns = 0
        self._delivery_url: str | None = None
        self._say_url: str | None = None
        self._bridged: list[dict[str, Any]] = []
        #: Shared teams provisioned for this run: team name -> team id.
        self._teams: dict[str, int] = {}
        #: The one group room this session sits in, when a track opens one.
        self._room: dict[str, Any] | None = None

    # ---------------------------------------------------------------- bridge

    def bind_delivery(self, base_url: str, post_paths: list[str]) -> None:
        """Bridge CM-channel messages to the fixture's reply endpoint.

        For this arm, sending to contact Bob IS replying to Bob — the CM's
        channel is its delivery mechanism, exactly as the in-memory outbound
        transport is its wire. The fixture stays the only witness: messages
        the brain sends to a persona are re-posted to the fixture's /reply,
        so scoring never has to trust adapter instrumentation. First live
        sweep motivation: custody replies with textbook judgement scored
        `replied: False` because they never touched the fixture.
        """
        self._delivery_url = (
            base_url.rstrip("/") + "/reply" if "/reply" in post_paths else None
        )
        self._say_url = base_url.rstrip("/") + "/say" if "/say" in post_paths else None
        self._bridged = []

    def _bridge_delivery(self, contact_id: Any, text: str) -> None:
        if not self._delivery_url or not text.strip():
            return
        # Never bridge the boss. Messages to the requester are the arm's
        # answer channel — already captured as Reply.text, the CM analogue
        # of a CLI arm's stdout, which no fixture ever witnesses. Bridging
        # them turns a well-behaved acknowledgement into a scored delivery:
        # first seen when "Got it. I'm reading the briefing now and won't
        # reply to anyone yet" failed custody/briefing's did_not_reply_yet.
        # Personas (bob, carol, ...) still bridge: for them, the CM channel
        # IS the delivery, which is the bridge's whole purpose.
        try:
            if contact_id == self._M.SESSION_DETAILS.boss_contact_id:
                return
        except AttributeError:
            pass
        sender_key = next(
            (
                key
                for key, c in self._correspondents.items()
                if c.get("contact_id") == contact_id and key != "__boss__"
            ),
            None,
        )
        if sender_key is None:
            return
        try:
            body = json.dumps({"to": sender_key, "text": text}).encode()
            req = urllib.request.Request(
                self._delivery_url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
        except Exception as exc:  # noqa: BLE001 - bridge is evidence, not control flow
            status = f"error: {exc}"
        self._bridged.append(
            {"to": sender_key, "text": text[:200], "status": status},
        )

    # ------------------------------------------------------------------ boot

    def setup(self) -> None:
        require_env()
        _prime_environment()
        self._loop = _LoopThread()

        import unify as unify_pkg
        import unisdk
        from unify.common.context_registry import ContextRegistry
        from unify.manager_registry import ManagerRegistry
        from unify.session_details import (
            UNASSIGNED_ASSISTANT_CONTEXT,
            UNASSIGNED_USER_CONTEXT,
        )

        self.context = (
            f"colleague/{self.track}/{self.run_id}"
            f"/{UNASSIGNED_USER_CONTEXT}/{UNASSIGNED_ASSISTANT_CONTEXT}"
        )
        unisdk.activate(self.project)
        # Meter at the HTTP boundary, exactly as every other arm: a recording
        # proxy in front of OpenRouter, reached through unillm's own gateway
        # override (UNILLM_LLM_GATEWAY_URL redirects every openrouter/-model
        # call's api_base; the key rides through to the real provider). One
        # capture mechanism for the whole benchmark — provider cost on every
        # response, verbatim request bodies beside it — and the vendor's arm
        # holds no privileged in-process hook the other arms lack. unillm
        # skips client-side credit deduction for gateway-routed calls, which
        # is correct here too: the spend lands on the same OpenRouter key,
        # at the same price sheet, as every other arm's. The env must be in
        # place before the first LLM call anywhere in the boot, so this
        # precedes unify's own init.
        if self.ledger is None and self.results_dir is not None:
            from colleague.arms.proxy import RecordingProxy
            from colleague.harness.ledger import PhaseLedger

            key = os.environ.get("OPENROUTER_API_KEY", "")
            if not key:
                raise SystemExit(
                    "OPENROUTER_API_KEY is required: the unify arm meters "
                    "through the recording proxy in front of OpenRouter.",
                )
            self.results_dir.mkdir(parents=True, exist_ok=True)
            self._proxy = RecordingProxy(
                port=0,
                ledger_path=self.results_dir / "proxy_ledger.jsonl",
                capture_requests_path=self.results_dir / "llm_requests.jsonl",
            ).start()
            os.environ["UNILLM_LLM_GATEWAY_URL"] = self._proxy.base_url
            os.environ["UNILLM_LLM_GATEWAY_KEY"] = key
            self.ledger = PhaseLedger(self.results_dir / "proxy_ledger.jsonl")

        unisdk.create_context(self.context)
        unisdk.set_context(self.context, relative=False)
        ManagerRegistry.clear()
        ContextRegistry.clear()
        unify_pkg.init(project_name=self.project)

        # LiveKit refuses to register its plugins off the main thread, and the
        # CM main module imports them transitively. Import it here, on the
        # calling thread, so the loop-thread boot only sees warm modules.
        import unify.conversation_manager.main  # noqa: F401

        self._loop.run(self._boot(), timeout=900)


    async def _boot(self) -> None:
        """Standalone CM boot, on the loop thread.

        The recipe is `tests/conversation_manager/conftest.py` with the two
        substitutions the benchmark needs: a real CodeActActor instead of
        SimulatedActor, and the sandbox's in-memory outbound transport so
        nothing anywhere needs GCP.
        """
        from unify.conversation_manager import (
            get_conversation_manager,
            start_async,
            stop_async,
        )
        from unify.conversation_manager.domains import managers_utils
        from unify.conversation_manager.event_broker import (
            get_event_broker,
            reset_event_broker,
        )

        # A previous session in this process may not have closed cleanly.
        if get_conversation_manager() is not None:
            try:
                await stop_async(reason="colleague re-init")
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
        reset_event_broker()
        # managers_utils caches the broker at import time; after a reset the
        # actor watchers would otherwise publish results into a dead broker
        # and the brain would never hear about completed work. The sandbox
        # does this same repoint.
        managers_utils.event_broker = get_event_broker()

        cm = await start_async(
            project_name=self.project,
            enable_comms_manager=False,  # no GCP Pub/Sub
            apply_test_mocks=True,  # stub outbound HTTP comms
        )

        # Belt and braces: even with the comms stubs, prefer the in-memory
        # outbound transport so `send_unify_message` never reaches for GCP.
        try:
            from unify.conversation_manager.domains.comms_utils import (
                set_outbound_transport,
            )
            from unify.gateway.outbound_inmemory import InMemoryOutboundTransport

            set_outbound_transport(InMemoryOutboundTransport())
        except Exception:  # noqa: BLE001 - transport is a fallback path here
            pass

        # The same actor the v0 arm dispatches to directly -- the comparison
        # between the two arms is then purely about the conversation layer.
        from unify.actor.code_act_actor import CodeActActor
        from unify.actor.environments import StateManagerEnvironment
        from unify.function_manager.primitives import Primitives
        from unify.manager_registry import ManagerRegistry

        self.primitives = Primitives()
        actor = CodeActActor(
            environments=[StateManagerEnvironment(self.primitives)],
            function_manager=ManagerRegistry.get_function_manager(),
            guidance_manager=ManagerRegistry.get_guidance_manager(),
            knowledge_manager=ManagerRegistry.get_knowledge_manager(),
        )

        await managers_utils.init_conv_manager(cm, actor=actor)
        if not cm.initialized:
            raise RuntimeError("ConversationManager managers failed to initialize")

        # The brain correctly defers with "my desktop is still booting" when
        # these are unset; every flow test flips them, and so do we.
        cm.vm_ready = True
        cm.file_sync_complete = True

        from unify.conversation_manager import events as ev
        from unify.conversation_manager.domains.event_handlers import EventHandler
        from unify.session_details import SESSION_DETAILS

        self._M = SimpleNamespace(
            ev=ev,
            EventHandler=EventHandler,
            SESSION_DETAILS=SESSION_DETAILS,
            stop_async=stop_async,
            reset_event_broker=reset_event_broker,
        )
        self._cm = cm

        # Align the boss contact row with the roster's boss. This row — not
        # SESSION_DETAILS.user — is what brain.py renders into the system
        # prompt's identity block, and ContactManager provisions it from the
        # operator's Orchestra account (`get_user_basic_info()`), so without
        # this the brain structurally works for the operator, not Daniel.
        # Not cosmetic: a custody run refused an entitled disclosure citing
        # "authorization from <operator>" before this was pinned.
        boss = self._contact_dict(SESSION_DETAILS.boss_contact_id)
        if (boss.get("first_name") or "").strip() != _BOSS_FIRST_NAME or (
            boss.get("email_address") or ""
        ).strip() != _BOSS_EMAIL:
            cm.contact_manager.update_contact(
                contact_id=SESSION_DETAILS.boss_contact_id,
                first_name=_BOSS_FIRST_NAME,
                surname=_BOSS_SURNAME,
                email_address=_BOSS_EMAIL,
                should_respond=True,
            )

        self._install_taps()
        self._queue = asyncio.Queue()
        self._consumer = asyncio.create_task(self._consume())

    def _install_taps(self) -> None:
        """Record egress and tool calls on the paths stepping cannot see.

        Actor completions are published by watcher tasks after the stepped
        turn has ended; the CM's own `wait_for_events` task consumes them and
        schedules background brain runs through the debouncer. Those runs
        send real replies, so both the broker's publish and `_run_llm` get a
        recording wrapper. The stepped driver saves/restores publish around
        each step, so step-local events (which it swallows) are recorded by
        the step itself and never double-counted here.
        """
        cm = self._cm
        ev = self._M.ev

        orig_publish = cm.event_broker.publish

        async def recording_publish(channel: str, message: str) -> int:
            try:
                evt = ev.Event.from_json(message)
            except Exception:  # noqa: BLE001 - non-event payloads pass through
                evt = None
            if evt is not None:
                self._record_egress(evt)
            return await orig_publish(channel, message)

        cm.event_broker.publish = recording_publish

        orig_run_llm = cm._run_llm

        async def recording_run_llm(trace_meta=None):
            self._llm_active += 1
            try:
                names = await orig_run_llm(trace_meta=trace_meta)
            finally:
                self._llm_active -= 1
            if names:
                self._tool_log.extend(names)
            return names

        cm._run_llm = recording_run_llm

    # ------------------------------------------------------- correspondents

    def register_correspondent(self, sender: str | None = None) -> dict[str, Any]:
        """Public wrapper so smoke checks can seed a contact without a turn."""
        assert self._loop is not None, "call setup() first"
        return self._loop.run(self._ensure_correspondent(sender), timeout=120)

    def seed_participants(self, people: list[dict[str, Any]]) -> None:
        """Make the contact store contain the people the roster describes.

        The roster is the scenario's world. For a text-only arm that world
        lives entirely in the prompt, but this arm has a real contact store
        its actor consults — and a store that lacks the named colleagues
        portrays a different world than the words do. The attribution run
        proved it: the actor (correctly) asked ContactManager for "Bob
        Ferrall, contractor on the platform team", found nothing, and spent
        52 calls hunting an internal ID for a person who existed only as
        prose. Full rows (surname, role, standing as bio) also make exact
        and semantic lookups land the way they would in production.
        """
        assert self._loop is not None, "call setup() first"
        self._loop.run(self._seed_participants(people), timeout=300)

    async def _provision_teams(self, people: list[dict[str, Any]]) -> None:
        """Give the assistant the roster's shared-team memberships, for real.

        The membership track measures write-time scoping — `personal |
        team:<id>` — and an assistant with no memberships cannot exercise
        it: ContextRegistry refuses `team:` destinations for non-members,
        so every fact lands in the personal root and every later answer is
        judgement. The roster and `/channels` already tell every arm who is
        in each team; this provisions that same world into the CM's native
        structures — one shared team per roster team name — through the
        CM's own membership path (`AssistantUpdateEvent`, update_kind
        "membership"), which binds SESSION_DETAILS.team_ids, the prompt's
        accessible-teams block, and the ContextRegistry team roots in one
        move. Nothing here says who may hear what: the descriptions carry
        only the membership facts every arm gets in prose.

        Team ids are minted per run, so the `Teams/<id>` roots are as
        throwaway as the run context itself — no other run resolves them.
        """
        if self._teams:
            return
        names: list[str] = []
        members: dict[str, list[str]] = {}
        for person in people:
            who = str(person.get("name") or person.get("id") or "").strip()
            for team in person.get("teams") or ():
                name = str(team).strip()
                if not name:
                    continue
                if name not in members:
                    names.append(name)
                    members[name] = []
                if who:
                    members[name].append(who)
        if not names:
            return

        base = int(datetime.now(timezone.utc).timestamp()) % 1_000_000_000
        minted: dict[str, int] = {}
        summaries: list[dict[str, Any]] = []
        for offset, name in enumerate(names):
            team_id = base + offset
            minted[name] = team_id
            summaries.append(
                {
                    "team_id": team_id,
                    "name": name,
                    "description": (
                        f"Shared team for the {name} channel. "
                        f"Members: {', '.join(members[name])}."
                    ),
                },
            )

        # AssistantUpdateEvent is one dataclass for every session-config
        # delta, so its identity fields are required arguments even though
        # the handler's membership branch reads only the team and contact
        # fields. Echo the live identity, making this a pure membership
        # delta whichever fields a handler version looks at.
        sd = self._M.SESSION_DETAILS
        event = self._M.ev.AssistantUpdateEvent(
            api_key=sd.unify_key,
            medium="text",
            assistant_id=str(sd.assistant.agent_id or ""),
            user_id=str(sd.user.id or ""),
            assistant_first_name=sd.assistant.first_name,
            assistant_surname=sd.assistant.surname,
            assistant_age=sd.assistant.age,
            assistant_nationality=sd.assistant.nationality,
            assistant_about=sd.assistant.about,
            assistant_number=sd.assistant.number,
            assistant_email=sd.assistant.email,
            user_first_name=sd.user.first_name,
            user_surname=sd.user.surname,
            user_number=sd.user.number,
            user_email=sd.user.email,
            voice_id=str(sd.voice.id or ""),
            update_kind="membership",
            team_ids=sorted(minted.values()),
            team_summaries=summaries,
            self_contact_id=sd.self_contact_id,
            boss_contact_id=sd.boss_contact_id,
        )
        await self._M.EventHandler.handle_event(event, self._cm)
        # Only a delivered membership counts: contact seeding below keys off
        # this map, and a team home it names must be one ContextRegistry
        # will accept.
        self._teams.update(minted)

    async def _seed_participants(self, people: list[dict[str, Any]]) -> None:
        cm = self._cm
        await self._provision_teams(people)
        for person in people:
            pid = str(person.get("id") or "").strip().lower()
            if not pid or pid in self._correspondents:
                continue
            name = str(person.get("name") or "").strip()
            first, _, surname = name.partition(" ")
            teams = [str(t) for t in (person.get("teams") or []) if str(t).strip()]
            bio = ". ".join(
                s.strip().rstrip(".")
                for s in (
                    person.get("role"),
                    f"Member of: {', '.join(teams)}" if teams else "",
                    person.get("standing"),
                )
                if s and str(s).strip()
            )
            email = str(person.get("email") or "").strip().lower()
            if pid in _BOSS_SENDER_KEYS or email == _BOSS_EMAIL:
                contact_id = self._M.SESSION_DETAILS.boss_contact_id
                # Also purges any bio the boss row inherited from the
                # operator's platform account during provisioning.
                cm.contact_manager.update_contact(
                    contact_id=contact_id,
                    bio=bio or None,
                    should_respond=True,
                )
            else:
                existing = cm.contact_manager.filter_contacts(
                    filter=f"email_address == '{email}'",
                )["contacts"]
                if existing:
                    contact_id = existing[0].contact_id
                    cm.contact_manager.update_contact(
                        contact_id=contact_id,
                        surname=surname or None,
                        bio=bio or None,
                        should_respond=True,
                    )
                else:
                    # Personal store only, never a team Contacts table: the
                    # benchmark's isolated stores number contacts per table,
                    # so a team-store row takes id 0 — the reserved self id —
                    # and inbound identity collapses (a Tomasz ask arrives as
                    # contact 0, which also matches a Finance-table row). The
                    # sender→team mapping lives in the bio's `Member of:`
                    # line and the team descriptions naming members.
                    outcome = cm.contact_manager._create_contact(
                        first_name=first or pid.title(),
                        surname=surname or None,
                        email_address=email or f"{pid}@colleague.example",
                        bio=bio or None,
                        should_respond=True,
                    )
                    contact_id = outcome["details"]["contact_id"]
            contact = self._contact_dict(contact_id)
            self._correspondents[pid] = contact
            if name:
                self._correspondents.setdefault(name.lower(), contact)

    async def _ensure_correspondent(self, sender: str | None) -> dict[str, Any]:
        """Sender name -> contact dict, creating the contact lazily.

        The default sender is the boss (contact_id 1, auto-created by
        ContactManager), and so is any spelling of the roster's boss —
        "daniel" must BE the structural boss, not a lookalike contact,
        or the brain treats the person the roster says it works for as
        just another correspondent. Named personas become ordinary
        contacts with `should_respond=True`; their response policy is
        left to the ContactManager default, which is part of what the
        tracks measure.
        """
        key = (sender or "").strip().lower() or "__boss__"
        cached = self._correspondents.get(key)
        if cached is not None:
            return cached

        cm = self._cm
        if key == "__boss__" or key in _BOSS_SENDER_KEYS:
            contact_id = self._M.SESSION_DETAILS.boss_contact_id
            cm.contact_manager.update_contact(
                contact_id=contact_id,
                should_respond=True,
            )
        else:
            local = re.sub(r"[^a-z0-9.]+", ".", key).strip(".") or "persona"
            email = f"{local}@colleague.example"
            existing = cm.contact_manager.filter_contacts(
                filter=f"email_address == '{email}'",
            )["contacts"]
            if existing:
                contact_id = existing[0].contact_id
            else:
                first_name = re.sub(r"[^\w .'-]+", "", (sender or "").strip())
                outcome = cm.contact_manager._create_contact(
                    first_name=(first_name or "Persona").title(),
                    email_address=email,
                    should_respond=True,
                )
                contact_id = outcome["details"]["contact_id"]
            cm.contact_manager.update_contact(
                contact_id=contact_id,
                should_respond=True,
            )

        contact = self._contact_dict(contact_id)
        self._correspondents[key] = contact
        return contact

    def _contact_dict(self, contact_id: int) -> dict[str, Any]:
        rows = self._cm.contact_manager.filter_contacts(
            filter=f"contact_id == {contact_id}",
        )["contacts"]
        if rows:
            return rows[0].model_dump(mode="json")
        return {"contact_id": contact_id, "first_name": "", "surname": ""}

    # ------------------------------------------------------------- text room

    def open_room(self, *, participants: list[str] = ()) -> None:
        """Mark the session as sitting in one group room until closed.

        The meeting track's text room used to reach the CM as a stream of
        1:1 events, so the product's own room discipline — the group-chat
        turn-taking protocol, "exactly one of us should answer",
        reply-in-the-room routing — never engaged: the CM believed every
        overheard line was a DM addressed to it. Room lines therefore enter
        as what they are: `UnifyMessageReceived` with a `group_id` and the
        room's member contact ids, per-sender attributed. `mentions` stays
        empty on purpose — noticing you were addressed by name is what
        `addressed_by_name` measures, and the name reaches every arm as
        prose; a parsed mention would be the fixture supplying the
        capability under test. The id is minted per run, like team ids;
        the room is as throwaway as the session.
        """
        ids: list[int] = []
        for pid in participants:
            contact = self._correspondents.get(str(pid).strip().lower())
            if contact and contact.get("contact_id") is not None:
                ids.append(int(contact["contact_id"]))
        self._room = {
            "group_id": int(datetime.now(timezone.utc).timestamp()) % 1_000_000_000,
            "participant_ids": ids,
        }

    def close_room(self) -> None:
        self._room = None

    def _bridge_room_say(self, text: str) -> None:
        """Room replies bridge to /say: the CM's room channel IS the room.

        Same principle as `_bridge_delivery`: the fixture stays the only
        witness. A send addressed to the room's group_id is the CM-native
        way of speaking into the room, so it posts where the room hears.
        """
        if not self._say_url or not text.strip():
            return
        try:
            body = json.dumps({"text": text}).encode()
            req = urllib.request.Request(
                self._say_url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
        except Exception as exc:  # noqa: BLE001 - bridge is evidence, not control flow
            status = f"error: {exc}"
        self._bridged.append({"to": "__room__", "text": text[:200], "status": status})

    # ------------------------------------------------------------ turn entry

    def begin(
        self,
        text: str,
        *,
        persist: bool = False,
        context: str | None = None,
        sender: str | None = None,
        images: list[str] | None = None,
    ) -> RunHandle:
        """Enqueue an inbound message and return before the turn finishes.

        `persist` is accepted and ignored: the ConversationManager is
        inherently persistent across turns in one process, which is the point
        of this surface. The roster/context preamble is composed into the
        message text -- the track design keeps that channel identical across
        arms.

        `images` are frames of the sender's shared screen. They enter through
        the CM's own screenshot buffer -- the path a shared screen takes from
        the fast brain -- attributed to the sender and paired with the
        message, so the slow brain sees them the way it sees any share.
        """
        assert self._loop is not None and self._cm is not None, "call setup() first"
        self._turns += 1
        if self.ledger is not None and self.auto_turn_boundaries:
            self.ledger.boundary(f"turn_{self._turns}")
        if images:
            self._buffer_frames(images, text, sender)
        item = self._loop.run(
            self._enqueue("begin", compose(context, text), sender, self._turns),
            timeout=120,
        )
        return UnifyCMRunHandle(self, item)

    def _buffer_frames(self, images: list[str], text: str, sender: str | None) -> None:
        """Hand shared-screen frames to the CM as user screenshots.

        Each frame is paired with the utterance it accompanies, so the buffer
        keeps all of them (unpaired frames of one source collapse to the
        newest, which would drop every step of a demonstration but the last).
        """
        import base64
        from datetime import datetime, timezone

        who = (sender or "").strip() or _BOSS_FIRST_NAME
        total = len(images)
        for k, path in enumerate(images, start=1):
            b64 = base64.b64encode(Path(path).read_bytes()).decode()
            self._cm._buffer_screenshot(
                json.dumps(
                    {
                        "b64": b64,
                        "utterance": f"[frame {k} of {total}] {text}",
                        "source": "user",
                        "filepath": str(path),
                        "attribution": who,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                ),
            )

    def resume(self, text: str, *, sender: str | None = None) -> Reply:
        """Continue the standing session; the CM never stopped being one."""
        return self.begin(text, sender=sender).wait()

    def _interject(self, text: str, *, sender: str | None = None) -> dict[str, Any]:
        """Another inbound event through the same pipeline, mid-turn.

        Whether the brain routes it into the right in-flight action (its
        `interject_*` tool) or answers over it is exactly the measured
        behaviour; the evidence is the turn's tool-call record.
        """
        assert self._loop is not None, "call setup() first"
        self._loop.run(
            self._enqueue("interject", text, sender, self._turns),
            timeout=120,
        )
        return {"delivered": True, "mode": "live_interject"}

    async def _enqueue(
        self,
        kind: str,
        content: str,
        sender: str | None,
        turn: int,
    ) -> _Inbound:
        contact = await self._ensure_correspondent(sender)
        room = self._room
        if room is not None:
            event = self._M.ev.UnifyMessageReceived(
                contact=contact,
                content=content,
                group_id=room["group_id"],
                participant_contact_ids=list(room["participant_ids"]) or None,
            )
        else:
            event = self._M.ev.UnifyMessageReceived(contact=contact, content=content)
        item = _Inbound(kind, turn, event, int(contact.get("contact_id", -1)))
        item.egress_start = len(self._egress_log)
        item.clar_seen = item.egress_start
        item.tools_start = len(self._tool_log)
        await self._queue.put(item)
        return item

    # -------------------------------------------------------- stepped drive

    async def _consume(self) -> None:
        """Process inbound events sequentially, one stepped turn each."""
        while True:
            item = await self._queue.get()
            if item is None:
                self._queue.task_done()
                return
            self._processing = True
            try:
                await asyncio.wait_for(
                    self._step_until_wait(item),
                    timeout=self.STEP_TIMEOUT,
                )
            except Exception as exc:  # noqa: BLE001 - surfaced on the turn
                item.error = f"{type(exc).__name__}: {exc}"
            finally:
                self._processing = False
                item.done.set()
                self._queue.task_done()

    async def _step_until_wait(self, item: _Inbound) -> None:
        """Vendored CMStepDriver.step_until_wait, against the live CM.

        Handles the inbound event, then runs the slow brain until it calls
        `wait`. Events the brain publishes during the step are applied to
        local state directly (not forwarded -- the background `wait_for_events`
        task also subscribes and would double-handle them). LLM-run requests
        from the step's own task tree are captured and looped on; requests
        from unrelated background tasks fall through to the real scheduler.
        """
        cm = self._cm
        ev = self._M.ev
        handle_event = self._M.EventHandler.handle_event

        original_publish = cm.event_broker.publish
        original_request = cm.request_llm_run
        step_requests: list = []
        token = _step_llm_requests.set(step_requests)

        async def publish_wrapper(channel: str, message: str) -> int:
            try:
                evt = ev.Event.from_json(message)
            except Exception:  # noqa: BLE001 - non-event payloads are dropped
                evt = None
            if evt is None:
                return 0
            self._record_egress(evt)
            await handle_event(evt, cm)
            return 0

        async def patched_request(delay=0, is_user_origin=False, **kwargs):
            requests = _step_llm_requests.get()
            if requests is not None:
                requests.append((delay, is_user_origin))
                return "stepped"
            return await original_request(
                delay=delay,
                is_user_origin=is_user_origin,
                **kwargs,
            )

        try:
            cm.event_broker.publish = publish_wrapper
            cm.request_llm_run = patched_request

            await handle_event(item.event, cm)
            llm_requested = bool(step_requests)
            step_requests.clear()

            steps = 0
            while llm_requested and steps < self.MAX_BRAIN_STEPS:
                tool_names = await cm._run_llm()
                steps += 1
                pending = set(cm._pending_steering_tasks)
                if pending:
                    await asyncio.wait(pending, timeout=120)
                llm_requested = bool(step_requests)
                step_requests.clear()
                if "wait" in (tool_names or []) and not llm_requested:
                    break
        finally:
            cm.event_broker.publish = original_publish
            cm.request_llm_run = original_request
            _step_llm_requests.reset(token)

    def _record_egress(self, evt: Any) -> None:
        name = type(evt).__name__
        if name not in _EVIDENCE_TYPES:
            return
        contact = getattr(evt, "contact", None) or {}
        if name == "EmailSent":
            subject = getattr(evt, "subject", "") or ""
            body = getattr(evt, "body", "") or ""
            text = f"{subject}\n{body}".strip()
        else:
            text = str(
                getattr(evt, "content", None) or getattr(evt, "query", "") or "",
            )
        entry: dict[str, Any] = {
            "type": name,
            "contact_id": contact.get("contact_id"),
            "text": text,
        }
        group_id = getattr(evt, "group_id", None)
        if group_id is not None:
            entry["group_id"] = group_id
        self._egress_log.append(entry)
        if name in _MESSAGE_SENT_TYPES:
            room = self._room
            if room is not None and group_id == room["group_id"]:
                self._bridge_room_say(text)
            else:
                self._bridge_delivery(contact.get("contact_id"), text)

    # -------------------------------------------------------------- draining

    def _brain_busy(self) -> bool:
        cm = self._cm
        if self._llm_active:
            return True
        if getattr(cm, "_pending_llm_requests", None):
            return True
        deb = cm.debouncer
        for task in (deb.pending_task, deb.running_task):
            if task is not None and not task.done():
                return True
        steering = getattr(cm, "_pending_steering_tasks", None)
        if steering and any(not t.done() for t in steering):
            return True
        return False

    def _actors_busy(self) -> bool:
        """True while any dispatched action is still owed to the brain.

        An entry whose last recorded action is a `response` is a persistent
        session parked awaiting input -- that is a settled state, not pending
        work. Anything else (including a finished handle whose ActorResult
        has not yet been consumed and popped) counts as busy, because the
        brain has not yet had its chance to react.
        """
        for data in self._cm.in_flight_actions.values():
            actions = data.get("handle_actions") or []
            last = actions[-1] if actions else {}
            if last.get("action_name") == "response":
                continue
            return True
        return False

    def _sender_key_for(self, contact_id: int) -> str | None:
        """The roster id behind a contact — the person a message was for."""
        for key, c in self._correspondents.items():
            if (
                c.get("contact_id") == contact_id
                and key != "__boss__"
                and " " not in key
            ):
                return key
        return None

    def _pending_question(self, item: _Inbound) -> tuple[int, str, int] | None:
        """The newest unanswered question sent to anyone in the cast.

        Not only the triggering contact: an assistant that needs a fact the
        requester does not have will ask the person who does, and that is
        the behaviour a scenario may be scoring. Whoever was asked answers,
        as themselves, through the scenario's persona pool.
        """
        known = {c.get("contact_id") for c in self._correspondents.values()}
        for idx in range(len(self._egress_log) - 1, item.clar_seen - 1, -1):
            entry = self._egress_log[idx]
            if (
                entry["type"] in _MESSAGE_SENT_TYPES
                and entry["contact_id"] in known
                and "?" in entry["text"]
            ):
                return idx, entry["text"], int(entry["contact_id"])
        return None

    async def _drain(self, item: _Inbound, timeout: float) -> bool:
        """Wait for the turn to genuinely end; run the clarification loop.

        Layered quiescence: the inbound queue must be empty, the brain idle
        (no stepped run, no debounced background run, no unflushed request),
        and every in-flight action either resolved-and-consumed or parked
        awaiting input. Between the brain going idle and the actors settling,
        a question addressed to the triggering persona is treated as the
        clarification contract: the scenario's responder answers it as that
        contact's next inbound message, bounded to a few rounds.
        """
        loop_time = asyncio.get_event_loop().time
        deadline = loop_time() + timeout
        quiet_streak = 0
        pending_stall = 0

        while loop_time() < deadline:
            if not item.done.is_set() or self._processing or not self._queue.empty():
                quiet_streak = 0
                await asyncio.sleep(0.25)
                continue

            if self._brain_busy():
                quiet_streak = 0
                # A request can rarely be left queued with nothing to flush
                # it (flush runs after broker events); nudge it ourselves.
                cm = self._cm
                deb = cm.debouncer
                debouncer_idle = all(
                    t is None or t.done() for t in (deb.pending_task, deb.running_task)
                )
                if cm._pending_llm_requests and debouncer_idle and not self._llm_active:
                    pending_stall += 1
                    if pending_stall >= 4:  # ~1s of pure stall
                        pending_stall = 0
                        try:
                            await cm.flush_llm_requests()
                        except Exception:  # noqa: BLE001 - drain must survive
                            pass
                else:
                    pending_stall = 0
                await asyncio.sleep(0.25)
                continue
            pending_stall = 0

            question = self._pending_question(item)
            if (
                question is not None
                and self._responder is not None
                and item.clar_rounds < self.MAX_CLARIFICATION_ROUNDS
            ):
                idx, q_text, asked_id = question
                item.clar_rounds += 1
                item.clar_seen = idx + 1
                who = self._sender_key_for(asked_id)
                answer = await asyncio.to_thread(self._responder, q_text, who)
                self._clarifications.append(
                    {
                        "question": q_text,
                        "answer": str(answer),
                        "who": who,
                        "contact_id": asked_id,
                        "turn": item.turn,
                    },
                )
                sender_contact = self._contact_from_id(asked_id)
                event = self._M.ev.UnifyMessageReceived(
                    contact=sender_contact,
                    content=str(answer),
                )
                clar_item = _Inbound("clar_answer", item.turn, event, asked_id)
                clar_item.egress_start = len(self._egress_log)
                clar_item.clar_seen = clar_item.egress_start
                clar_item.tools_start = len(self._tool_log)
                await self._queue.put(clar_item)
                quiet_streak = 0
                continue

            if self._actors_busy():
                quiet_streak = 0
                await asyncio.sleep(0.3)
                continue

            # Everything looks quiet; insist on it twice in a row so the
            # short gaps between a handle resolving, its watcher publishing,
            # and the background loop reacting cannot read as "done".
            quiet_streak += 1
            if quiet_streak >= 2:
                return True
            await asyncio.sleep(0.4)

        return False

    def _contact_from_id(self, contact_id: int) -> dict[str, Any]:
        for contact in self._correspondents.values():
            if contact.get("contact_id") == contact_id:
                return contact
        return self._contact_dict(contact_id)

    def _wait_turn(self, item: _Inbound, timeout: float) -> Reply:
        try:
            drained = self._loop.run(self._drain(item, timeout), timeout=timeout + 60)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            return Reply(text="", ok=False, error=f"{type(exc).__name__}: {exc}")

        egress = self._egress_log[item.egress_start :]
        sent_to_trigger = [
            e
            for e in egress
            if e["type"] in _MESSAGE_SENT_TYPES and e["contact_id"] == item.contact_id
        ]
        tools = self._tool_log[item.tools_start :]
        steering = [
            t for t in tools if t == "act" or t.split("_", 1)[0] in _STEERING_PREFIXES
        ]
        silent = ("wait" in tools) and not sent_to_trigger
        meta = {
            "turn": item.turn,
            "tool_names": tools,
            "steering": steering,
            "silent": silent,
            "clarification_rounds": item.clar_rounds,
            "egress": egress,
        }
        record = {
            "turn": item.turn,
            "sender_contact_id": item.contact_id,
            "tools": tools,
            "sent_events": len(sent_to_trigger),
            "silent": silent,
            "clarification_rounds": item.clar_rounds,
            "drained": drained,
        }
        if item.error:
            record["error"] = item.error
        self._turn_records.append(record)

        text = "\n\n".join(e["text"] for e in sent_to_trigger if e["text"])
        if item.error:
            return Reply(text=text, ok=False, error=item.error, meta=meta, raw=egress)
        if not drained:
            return Reply(
                text=text,
                ok=False,
                error=f"turn did not quiesce within {timeout}s",
                meta=meta,
                raw=egress,
            )
        return Reply(text=text, ok=True, meta=meta, raw=egress)

    # ---------------------------------------------- standing work (the clock)
    # The fire-series experiments deliver their brief through `begin` like any
    # other turn; whether and how the work comes to recur is the system's own
    # choice. These three methods are the harness's only other involvement:
    # read what the system bound to the clock (observation, never a gate),
    # deliver the due tick for it through the product's own due-task path,
    # and wait for the resulting work to genuinely settle.

    def scheduled_recurrences(self) -> list[dict[str, Any]]:
        """Recurring tasks the system itself has scheduled — evidence only."""
        assert self._loop is not None, "call setup() first"
        return self._loop.run(self._scheduled_recurrences(), timeout=120)

    async def _scheduled_recurrences(self) -> list[dict[str, Any]]:
        from unify.manager_registry import ManagerRegistry

        scheduler = ManagerRegistry.get_task_scheduler()
        out: list[dict[str, Any]] = []
        for task in scheduler._filter_tasks(filter=None, limit=100):
            if task.repeat is None and task.trigger is None:
                continue
            repeat = getattr(task, "repeat", None)
            schedule = getattr(task, "schedule", None)
            out.append(
                {
                    "task_id": task.task_id,
                    "name": getattr(task, "name", None),
                    "description": getattr(task, "description", None),
                    "enabled": getattr(task, "enabled", None),
                    "entrypoint": getattr(task, "entrypoint", None),
                    "repeat": (
                        [r.model_dump(mode="json") for r in repeat] if repeat else None
                    ),
                    "schedule": (
                        schedule.model_dump(mode="json")
                        if schedule is not None
                        else None
                    ),
                },
            )
        return out

    def fire_due_recurrences(
        self,
        *,
        scheduled_for: str | None = None,
    ) -> list[dict[str, Any]]:
        """Play the clock: a due tick for everything the system scheduled.

        In production the passage of time produces a ``TaskDue`` event — from
        Communication's Pub/Sub in hosted deployments, from the in-process
        ``LocalActivationScheduler``'s asyncio timers locally — and the CM's
        handler runs the task through ``TaskScheduler.execute`` under its own
        due-task delegate, registered as a real in-flight action with
        watchers. This compresses only the waiting: the same due path runs,
        for the tasks the *system* created, with the CM's own delegate. The
        hosted staleness validation (revision/execution-row echo checks) is
        skipped because the benchmark's deliberately-unassigned context has
        no Orchestra-projected execution rows to echo. Returns one entry per
        recurring task: started handles, or the error that kept one from
        starting. A system that scheduled nothing gets an empty tick — and
        the sink shows it.
        """
        assert self._loop is not None and self._cm is not None, "call setup() first"
        return self._loop.run(
            self._fire_due_recurrences(scheduled_for),
            timeout=self.STEP_TIMEOUT,
        )

    async def _fire_due_recurrences(
        self,
        scheduled_for: str | None,
    ) -> list[dict[str, Any]]:
        from unify.conversation_manager.domains import task_execution as te
        from unify.conversation_manager.events import TaskDue

        due_at = scheduled_for or datetime.now(timezone.utc).isoformat()
        fired: list[dict[str, Any]] = []
        for task in await self._scheduled_recurrences():
            entry: dict[str, Any] = {
                "task_id": task["task_id"],
                "name": task.get("name"),
                "entrypoint": task.get("entrypoint"),
            }
            if task.get("enabled") is False:
                entry["skipped"] = "disabled"
                fired.append(entry)
                continue
            try:
                event = TaskDue(
                    task_id=int(task["task_id"]),
                    source_task_log_id=0,
                    revision="colleague-clock",
                    scheduled_for=due_at,
                    task_label=str(task.get("name") or ""),
                    task_summary=str(task.get("description") or "")[:280],
                    recurrence_hint="recurring",
                )
                entry["handle_id"] = await te._start_live_task_due_execution(
                    event,
                    self._cm,
                    None,
                )
            except (
                Exception
            ) as exc:  # noqa: BLE001 - a fire that cannot start is a result
                entry["error"] = f"{type(exc).__name__}: {exc}"
            fired.append(entry)
        return fired

    def settle(self, timeout: float = 900.0) -> bool:
        """Wait for the session to genuinely go quiet, outside any turn.

        The same layered drain a turn ends with — inbound queue empty, brain
        idle, every in-flight action resolved or parked — run against a
        synthetic already-delivered item, so a fire-series driver can wait
        out the work a due tick started (and the detached reviews behind it)
        without pretending there was an inbound message.
        """
        assert self._loop is not None, "call setup() first"
        item = _Inbound("settle", self._turns, None, -1)
        item.egress_start = len(self._egress_log)
        item.clar_seen = item.egress_start
        item.tools_start = len(self._tool_log)
        item.done.set()
        try:
            return bool(
                self._loop.run(self._drain(item, timeout), timeout=timeout + 60),
            )
        except Exception:  # noqa: BLE001 - a failed drain reports as unsettled
            return False

    def egress_marker(self) -> int:
        """Current position in the egress log, for `owner_messages_since`."""
        return len(self._egress_log)

    def owner_messages_since(self, marker: int) -> list[dict[str, Any]]:
        """Messages the assistant sent its boss since ``marker``.

        The CM's boss channel is this arm's owner channel: a hold is the
        assistant telling the owner why nothing was delivered, through its
        own send tools. The fire-series scorer applies the same HOLD-marker
        rule to these as to the fixture's ``/owner/notify`` channel.
        """
        try:
            boss_id = self._M.SESSION_DETAILS.boss_contact_id
        except AttributeError:
            return []
        return [
            {"text": e["text"], "type": e["type"]}
            for e in self._egress_log[marker:]
            if e["type"] in _MESSAGE_SENT_TYPES and e["contact_id"] == boss_id
        ]

    # ------------------------------------------------- voice (delimited hook)
    # The implementation lives in `unify_cm_voice.py`; this file carries only
    # the delegation, because another stream owns its text-side behaviour.

    def join_voice_room(self, invite, *, on_text, personas=()) -> dict[str, Any]:
        from colleague.arms.sessions.unify_cm_voice import UnifyCMVoiceBridge

        self._voice_bridge = UnifyCMVoiceBridge(self)
        return self._voice_bridge.join(invite, on_text=on_text, personas=personas)

    def leave_voice_room(self) -> None:
        bridge = getattr(self, "_voice_bridge", None)
        if bridge is not None:
            bridge.leave()
            self._voice_bridge = None

    def attach_call_surface(self, invite, *, on_text) -> dict[str, Any]:
        from colleague.arms.sessions.unify_cm_call import UnifyCMCallBridge

        self._call_bridge = UnifyCMCallBridge(self)
        return self._call_bridge.attach(invite, on_text=on_text)

    def detach_call_surface(self) -> None:
        bridge = getattr(self, "_call_bridge", None)
        if bridge is not None:
            bridge.detach()
            self._call_bridge = None

    # -------------------------------------------------------- clarifications

    def on_clarification(self, responder) -> None:
        self._responder = responder

    def clarifications(self) -> list[dict[str, Any]]:
        return list(self._clarifications)

    # -------------------------------------------------------------- teardown

    def _stop_in_flight(self) -> None:
        if self._loop is None or self._cm is None:
            return
        try:
            self._loop.run(self._stop_in_flight_async(), timeout=120)
        except Exception:  # noqa: BLE001 - teardown is best-effort
            pass

    async def _stop_in_flight_async(self) -> None:
        cm = self._cm
        for data in list(cm.in_flight_actions.values()):
            handle = data.get("handle")
            if handle is None:
                continue
            try:
                if hasattr(handle, "trigger_completion"):
                    handle.trigger_completion()
                elif not handle.done():
                    await asyncio.wait_for(
                        handle.stop(reason="scenario end"),
                        timeout=15,
                    )
            except Exception:  # noqa: BLE001 - stop each without failing rest
                pass
        cm.in_flight_actions.clear()
        cm.completed_actions.clear()

    async def _shutdown(self) -> None:
        if self._consumer is not None:
            await self._queue.put(None)
            try:
                await asyncio.wait_for(self._consumer, timeout=10)
            except Exception:  # noqa: BLE001 - cancel a stuck consumer
                self._consumer.cancel()
        await self._stop_in_flight_async()
        try:
            await self._M.stop_async(reason="scenario end")
        except Exception:  # noqa: BLE001 - teardown is best-effort
            pass
        try:
            self._M.reset_event_broker()
        except Exception:  # noqa: BLE001 - teardown is best-effort
            pass

    def close(self) -> None:
        if self._loop is not None and self._cm is not None:
            try:
                self._loop.run(self._shutdown(), timeout=180)
            except Exception:  # noqa: BLE001 - teardown is best-effort
                pass
        if self._loop is not None:
            self._loop.close()
        # Per-call rows already live in proxy_ledger.jsonl as they happen;
        # what close writes is the phase view over them. The proxy stops
        # last so a straggling in-flight response still lands in the ledger.
        if self.ledger is not None and self.results_dir is not None:
            try:
                self.results_dir.mkdir(parents=True, exist_ok=True)
                (self.results_dir / "phase_summary.json").write_text(
                    json.dumps(self.ledger.segments(), indent=1, default=str),
                    encoding="utf-8",
                )
            except Exception:  # noqa: BLE001 - metering must never break a run
                pass
        if self._proxy is not None:
            try:
                self._proxy.stop()
            except Exception:  # noqa: BLE001 - teardown is best-effort
                pass
            self._proxy = None

    def artifacts(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "context": self.context,
            "project": self.project,
            "turns": list(self._turn_records),
        }
        if self._delivery_url:
            out["delivery_bridge"] = {
                "url": self._delivery_url,
                "forwarded": list(self._bridged),
            }
        if self.ledger is not None:
            try:
                out["llm_segments"] = list(self.ledger.segments())
            except Exception:  # noqa: BLE001 - metering must never break a run
                pass
        return out

    def cost_snapshot(self) -> dict[str, Any]:
        if self.ledger is not None:
            return self.ledger.cost_snapshot()
        # The runner snapshots costs BEFORE setup(), and a sleep-rebooted
        # session shares its run root — and therefore its accumulated proxy
        # ledger — with every session before it. Answering {} here made the
        # before-diff vanish, so each week reported the file's cumulative
        # totals as its own spend (2026-08-22: week 6 read as 163 calls /
        # $3.36 when its true delta was 23 / $0.29). Reading the file
        # directly keeps the baseline honest while still attributing the
        # boot's own calls to the scenario that paid for them.
        if self.results_dir is not None:
            path = self.results_dir / "proxy_ledger.jsonl"
            if path.exists():
                from colleague.harness.ledger import PhaseLedger

                return PhaseLedger(path).cost_snapshot()
        return {}


register("unify-cm", UnifyCMSession)
