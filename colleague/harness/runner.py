"""One runner for every track.

A track supplies three things and gets a driver for free:

    fixture.build(seed=, port=)     -> FixtureServer
    scenario.scenarios(base_url)    -> [{name, context, request, ...}]
    scenario.score(name, fixture)   -> ScenarioResult

Optionally it also supplies ``scenario.turns(name, ...)`` returning scripted
interlocutor turns, ``scenario.scene(name)`` returning a role-played scene
(people who carry the conversation themselves, see `harness/roleplay.py`),
and ``SESSION_SCOPE`` to say whether the arm session is rebuilt per scenario
(the default) or held across the whole track — which `continuity` needs,
since a session surviving between requests is the thing under test.

Each scenario gets a fresh fixture, so the recorder contains only that
scenario's side effects and scoring never has to filter by time.
"""

from __future__ import annotations

import json
import os
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO

from colleague.arms.sessions import build as build_session
from colleague.harness.attachments import find_deliverable, post_deliverable
from colleague.harness.capability import Outcome, ScenarioResult, Steering, summarize
from colleague.harness.cost import delta as cost_delta
from colleague.harness.cost import total as total_cost
from colleague.harness.interlocutor import Interlocutor
from colleague.harness.roleplay import RolePlayDirector
from colleague.harness.scoring import infra_failure, resolve_recipient
from colleague.harness.session import ArmSession, Reply, RunHandle, Unsupported

#: Safety cap on persona↔arm rounds per scenario — a cap, not a score:
#: hitting it resolves the scenario on whatever the fixture witnessed, and
#: the ledger shows what the ping-pong cost.
PERSONA_ROUNDS = int(os.environ.get("COLLEAGUE_PERSONA_ROUNDS", "6"))


def _collect_deliverable(
    *,
    session: ArmSession,
    fixture: Any,
    reply: Reply,
    record: dict[str, Any],
    staged: list[str],
    since: float,
) -> dict[str, Any]:
    """Bridge a workspace arm's produced file to the fixture's /deliver.

    Runs only when nothing was bridged already (an arm whose product sends
    files on its own channel is its own bridge). The search never returns a
    file the harness staged — handing back the inputs is not delivering —
    and workspace *discovery* is limited to files written during this
    scenario, so a slept week cannot resubmit last week's report by doing
    nothing. Finding no file is evidence for the scorer, not an error.
    """
    workspace = getattr(session, "workspace", None)
    if workspace is None:
        return {"found": False, "why": "arm has no workspace to collect from"}
    staged_paths = {Path(p).resolve() for p in staged}
    received = {
        Path(p).resolve()
        for p in getattr(session, "received_attachments", set()) or set()
    }
    off_limits = staged_paths | received

    # Search the whole visible conversation for a named path: the final
    # reply, plus anything the arm said in resumed persona rounds.
    texts = [reply.text or ""]
    for entry in record.get("conversation") or []:
        for key in ("text", "reply"):
            value = entry.get(key)
            if isinstance(value, str):
                texts.append(value)

    found, how = find_deliverable(
        "\n".join(texts),
        [Path(workspace)],
        ignore=lambda p: p in off_limits,
        since=since,
    )
    if found is None:
        return {"found": False, "why": "no produced file named or discovered"}
    try:
        post_deliverable(
            fixture.base_url,
            found,
            via=f"collected:{how}",
            note=(reply.text or "")[:200],
        )
    except Exception as exc:  # noqa: BLE001 - recorded, then scored as absent
        return {"found": True, "how": how, "error": f"{type(exc).__name__}: {exc}"}
    return {"found": True, "how": how, "path": str(found)}


class _Resumed(RunHandle):
    """A continuation of an open session, presented as an ordinary run."""

    def __init__(
        self,
        session: ArmSession,
        text: str,
        sender: str | None,
        attachments: list[str] | None = None,
    ) -> None:
        self._session = session
        self._text = text
        self._sender = sender
        self._attachments = attachments
        self._reply: Reply | None = None

    def wait(self, timeout: float = 900.0) -> Reply:
        if self._reply is None:
            try:
                if self._attachments:
                    self._reply = self._session.resume(
                        self._text,
                        sender=self._sender,
                        attachments=self._attachments,
                    )
                else:
                    self._reply = self._session.resume(self._text, sender=self._sender)
            except Exception as exc:  # noqa: BLE001 - surfaced in the run file
                self._reply = Reply(
                    text="",
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
        return self._reply

    def interject(self, text: str, *, sender: str | None = None) -> dict[str, Any]:
        raise Unsupported("a resumed turn is not separately steerable here")


def _session_for(
    arm: str,
    *,
    track: str,
    run_id: str,
    results_dir: Path,
    timeout_s: float,
    mode: str = "ideal",
    transport: str = "text",
    human_hourly_rate_usd: float = 30.0,
    human_participant_id: str = "anonymous",
    human_input_fn: Callable[[str], str] | None = None,
    human_output: TextIO | None = None,
    human_event_sink: Callable[[dict[str, Any]], None] | None = None,
) -> ArmSession:
    if arm == "mock":
        # run_id keys the mock's durable store; without it a restart
        # session cannot find the week the shared session banked.
        # results_dir gives the plan a real workspace, so a track whose
        # deliverable is a produced file proves the same collection path
        # the CLI arms use rather than bypassing it.
        return build_session("mock", mode=mode, run_id=run_id, results_dir=results_dir)
    if arm == "human":
        return build_session(
            "human",
            results_dir=results_dir,
            hourly_rate_usd=human_hourly_rate_usd,
            participant_id=human_participant_id,
            input_fn=human_input_fn or input,
            output=human_output,
            event_sink=human_event_sink,
        )
    if arm == "unify-cm":
        return build_session(
            arm,
            run_id=run_id,
            track=track,
            results_dir=results_dir,
        )
    # The transport is boot-time information for arms whose product needs a
    # different configuration to field a call at all (the OpenClaw Gateway
    # only carries its voice-call plugin on a voice run, so text tracks keep
    # exactly the tool surface their published results used).
    return build_session(
        arm,
        results_dir=results_dir,
        run_id=run_id,
        timeout_s=timeout_s,
        transport=transport,
    )


def run_track(
    *,
    track: str,
    arm: str,
    fixture_module: Any,
    scenario_module: Any,
    results_root: Path,
    seed: int | None = None,
    port: int = 0,
    timeout_s: float = 900.0,
    only: str | None = None,
    mode: str = "ideal",
    transport: str = "text",
    human_hourly_rate_usd: float = 30.0,
    human_participant_id: str = "anonymous",
    human_input_fn: Callable[[str], str] | None = None,
    human_output: TextIO | None = None,
    human_event_sink: Callable[[dict[str, Any]], None] | None = None,
) -> int:
    # The suffix is load-bearing. run_id is the aggregate's dedupe key, and
    # parallel repeats of one scenario start within the same second — so a
    # timestamp alone collapsed 9 of 42 legitimate results into their
    # neighbours and reported the survivors as the whole sweep.
    run_id = (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        + f"-{arm}-{uuid.uuid4().hex[:6]}"
    )
    results_dir = results_root / run_id
    results_dir.mkdir(parents=True, exist_ok=True)
    seed = (
        seed if seed is not None else getattr(fixture_module, "DEFAULT_SEED", 20260801)
    )
    session_scope = getattr(scenario_module, "SESSION_SCOPE", "scenario")

    results: dict[str, Any] = {
        "track": track,
        "arm": arm,
        "run_id": run_id,
        "seed": seed,
        "session_scope": session_scope,
        # What actually carried the scenes. Overwritten per scenario when
        # voice was asked for and could not be provided, so a text result is
        # never read as a voice one and the two are never merged silently.
        "transport": transport,
        "scenarios": [],
    }

    shared_session: ArmSession | None = None
    world_rebooted = False
    if session_scope == "track":
        shared_session = _session_for(
            arm,
            track=track,
            run_id=run_id,
            results_dir=results_dir,
            timeout_s=timeout_s,
            mode=mode,
            transport=transport,
            human_hourly_rate_usd=human_hourly_rate_usd,
            human_participant_id=human_participant_id,
            human_input_fn=human_input_fn,
            human_output=human_output,
            human_event_sink=human_event_sink,
        )
        shared_session.setup()
        results["profile"] = shared_session.profile.name

    # A track-scoped session needs a track-scoped fixture: a warm session that
    # remembers a base URL must not be punished for the harness moving it.
    shared_fixture = (
        fixture_module.build(seed=seed, port=port).start()
        if session_scope == "track"
        else None
    )

    outcomes: list[ScenarioResult] = []
    try:
        for spec in scenario_module.scenarios("http://placeholder"):
            name = spec["name"]
            if only and name != only:
                continue
            # A voice-only scene measures something a text delivery cannot
            # carry (a call's tolerance for delay; two assistants' audio
            # overlapping). Under the text transport it is skipped for real
            # arms rather than mismeasured — but still runs for the mock, so
            # the self-test proves its scorer discriminates.
            if spec.get("voice_only") and transport != "voice" and arm != "mock":
                print(f"[{track}/{arm}] scenario {name} — skipped (voice-only)")
                continue

            if shared_fixture is not None:
                fixture = shared_fixture
                fixture.reset_observations()
            else:
                fixture = fixture_module.build(seed=seed, port=port).start()
            # Returned artifacts land in the results tree, per scenario —
            # the recorder's sequence numbers reset with the observations,
            # so the directory must scope the filenames instead.
            fixture.state["artifact_dir"] = str(results_dir / "deliverables" / name)
            # Scenario text is regenerated against the live port.
            live = next(
                s
                for s in scenario_module.scenarios(fixture.base_url)
                if s["name"] == name
            )
            # A scenario may demand a clean session even under track scope.
            # `teaching/untaught_control` is the reason: it ran third in the
            # shared session and still remembered the walkthrough, so the
            # control that exists to establish what the API alone yields was
            # measuring retention instead — and made the taught result
            # unreadable.
            #
            # `restart` is the opposite shape: a new process over the same
            # durable world. It keeps the run's own id, so an arm whose
            # store is keyed by it (the CM's context tree, the mock's
            # durable store) reattaches, and an arm that kept the week in
            # its prompt has nothing. A restart scenario belongs after the
            # turns it must remember, and nothing may use the shared
            # session once the restart has booted over it.
            #
            # `sleep` is the shape between them: the idle shutdown every
            # real deployment performs between requests that arrive days
            # apart (the CM retires its pod after ten idle minutes;
            # a laptop closes; a gateway process exits). The process dies,
            # the DISK survives: unlike `restart`, a sleep session keeps
            # the run root's results_dir, so an arm's own on-disk
            # continuity — hermes's SQLite session rows, OpenClaw's state
            # dir, prime-agent's session files, the CM's context tree —
            # reattaches exactly as it would for a user reopening
            # yesterday's chat. What does NOT survive is process memory:
            # an open act run, a warm transcript in RAM, a trajectory the
            # model was leaning on instead of its durable stores.
            wants_reboot = bool(live.get("restart") or live.get("sleep"))
            if wants_reboot and shared_session is not None:
                # Two live sessions over one world corrupt each other (two
                # CMs share context roots; two gateways race one state
                # dir), so the shared session dies before the reboot boots.
                results["artifacts"] = shared_session.artifacts()
                shared_session.close()
                shared_session = None
            if wants_reboot:
                world_rebooted = True
            elif world_rebooted and not live.get("fresh_session"):
                raise RuntimeError(
                    f"scenario {name!r} would reuse the shared session, but "
                    "an earlier sleep/restart scenario already booted over "
                    "its world — every scenario after the first sleep or "
                    "restart must itself declare sleep, restart, or "
                    "fresh_session",
                )
            own_session = bool(live.get("fresh_session") or wants_reboot)
            session = (None if own_session else shared_session) or _session_for(
                arm,
                track=track,
                run_id=run_id if wants_reboot else f"{run_id}-{name}",
                results_dir=results_dir if live.get("sleep") else results_dir / name,
                timeout_s=timeout_s,
                mode=mode,
                transport=transport,
                human_hourly_rate_usd=human_hourly_rate_usd,
                human_participant_id=human_participant_id,
                human_input_fn=human_input_fn,
                human_output=human_output,
                human_event_sink=human_event_sink,
            )
            if arm == "mock":
                session.bind(
                    fixture=fixture,
                    scenario=name,
                    plan=scenario_module.mock_plan,
                )
            record: dict[str, Any] = {
                "name": name,
                "note": live.get("note", ""),
                "profile": session.profile,
            }
            # A track-scoped session accumulates clarifications across
            # scenarios; a scorer asking "did the arm ask during *this* one"
            # must see only the ones raised from here on.
            clarifications_before = len(session.clarifications())
            cost_before = session.cost_snapshot()
            scenario_started = time.monotonic()
            # Wall-clock epoch for deliverable collection: only files written
            # during this scenario qualify for workspace discovery, so a
            # slept week can never hand back last week's report by doing
            # nothing. (A path the arm explicitly names is exempt.)
            scenario_epoch = time.time()
            print(f"[{track}/{arm}] scenario {name} — fixture {fixture.base_url}")

            voice_t: Any = None
            try:
                if shared_session is None or own_session:
                    session.setup()

                # The human workbench gets the same live fixture the scenario
                # text documents. It adds generic GET/POST controls, never an
                # answer-bearing helper, so the scorer still witnesses the
                # exact same external actions as every programmatic arm.
                if hasattr(session, "bind_fixture"):
                    session.bind_fixture(fixture, name)

                # A scenario may author a participant surface — the same ask
                # in office language plus typed forms (see the track's
                # human.py). Only the human workbench carries the attribute;
                # assigning every scenario means a shared session cannot leak
                # one scenario's surface into the next.
                if hasattr(session, "surface"):
                    session.surface = live.get("surface")

                # An arm whose product delivers through its own channel (the
                # CM arm sends to contact Bob rather than calling the
                # fixture's API) declares a delivery bridge: messages to a
                # persona are re-posted to the fixture's reply endpoint, so
                # the fixture remains the only witness scoring reads.
                if hasattr(session, "bind_delivery"):
                    session.bind_delivery(fixture.base_url, fixture.post_paths)

                # An arm with a real contact store gets an environment that
                # contains the people the roster text describes. Text-only
                # arms are unaffected; without this, a store-backed arm's
                # (correct) lookup of a named colleague finds nothing — one
                # burned 52 calls hunting an ID for a Bob that existed only
                # as prose.
                cast = getattr(scenario_module, "PARTICIPANTS", None)
                if cast and hasattr(session, "seed_participants"):
                    session.seed_participants(
                        [
                            {
                                "id": p.id,
                                "name": p.name,
                                "role": p.role,
                                "email": p.email,
                                "standing": p.standing,
                                "teams": list(p.teams),
                            }
                            for p in cast
                        ],
                    )

                # The arm asks through its own channel; the fixture provides
                # none. Whoever the arm addressed answers, when its channel
                # names someone; otherwise whoever the scenario has cast.
                # The pool is the persona engine: one person per cast member,
                # alive for the whole track, answering on every channel —
                # the clarification hook is one more channel into the same
                # person, not a separate answering brain.
                pool = fixture.state.get("personas")
                default_who = str(live.get("clarify_persona") or "daniel")
                if pool is not None:
                    # The deterministic validation path must not require
                    # model calls: the mock arm (which is what the self-test
                    # runs) always meets the scripted implementation.
                    if arm == "mock":
                        pool.force_scripted()
                    pool.bind_ledger(
                        results_dir / "persona_ledger.jsonl",
                        run_id=run_id,
                    )
                    # Per-scenario window: evidence, the DEGRADED trigger and
                    # the leak guard read only this scenario's exchanges.
                    # Overrides are how a control meets an information-free
                    # stand-in instead of the person who knows the spec.
                    pool.begin_scenario(name)
                    pool.apply_overrides(live.get("persona_overrides"))
                    session.on_clarification(
                        lambda q, who=None, _w=default_who, _p=pool: _p.answer(
                            who or _w,
                            q,
                        ),
                    )
                    results.setdefault("profile", session.profile.name)

                turns = []
                if hasattr(scenario_module, "turns"):
                    turns = scenario_module.turns(name) or []

                # The scene, if any, is needed before the first turn: a voice
                # run speaks it through the room rather than interjecting it,
                # and the opening request may differ (a room API that offers
                # /say has no business existing on a call).
                scene = (
                    scenario_module.scene(name)
                    if hasattr(scenario_module, "scene")
                    else None
                )
                request_text = live["request"]
                if transport == "voice" and scene is not None:
                    if live.get("voice_call"):
                        voice_t, why = _voice_call_setup(session, live, name, scene)
                    else:
                        voice_t, why = _voice_setup(session, live, name)
                    record["transport"] = (
                        "voice" if voice_t else f"text (voice unavailable: {why})"
                    )
                    results["transport"] = record["transport"]
                    if voice_t is None and live.get("voice_call"):
                        # A meeting scene degrades to the text room; a phone
                        # call has no text to degrade to — POSTed lines scored
                        # as a call is the category error the track exists to
                        # avoid. Nothing is measured, loudly.
                        raise RuntimeError(
                            f"a phone call cannot degrade to text "
                            f"(voice unavailable: {why})",
                        )
                    if voice_t is not None:
                        # The fixture knows the room is a call, so a text
                        # path that must not exist on a call (meeting's /say)
                        # can refuse and record the attempt.
                        fixture.state["transport"] = "voice"
                        if live.get("voice_request"):
                            request_text = live["voice_request"]
                    if voice_t is not None and live.get("voice_call"):
                        # The dial adapter is armed before the opening turn:
                        # the call is placed inside it, through the arm's own
                        # comms path pointed at the exchange. The hooks flow
                        # the other way — the provider's status callbacks
                        # (no-answer) reach the arm through whatever surface
                        # the adapter registered.
                        hooks = (
                            session.attach_call_surface(
                                voice_t.invite(str(live.get("callee") or "")),
                                on_text=voice_t.note_assistant_text,
                            )
                            or {}
                        )
                        voice_t.status_sink = hooks.get("deliver_status")
                else:
                    record["transport"] = "text"

                # Document-scale I/O: a scenario that declares `attachments`
                # has the fixture stage its files (generated seeded, into the
                # regenerable corpus/ tree — never uploaded by CI), and every
                # surface receives them through its own best mechanism. The
                # deliverable is expected back the same way; see collection
                # below.
                staged: list[str] = []
                if live.get("attachments"):
                    staged = [
                        str(p)
                        for p in fixture_module.stage_attachments(
                            fixture=fixture,
                            scenario=name,
                            dest=results_dir / "corpus" / name,
                        )
                    ]
                    record["attachments"] = [Path(p).name for p in staged]

                # The scenario's scripted stimulus is the persona's own
                # authored speech: seeding it into their memory is what makes
                # "you already said it" literally true when they later
                # restate the brief, the feedback, or the amendment.
                if pool is not None and live.get("sender"):
                    pool.note_authored(str(live["sender"]), request_text)

                # A continuation goes through the arm's own resume path when
                # it has one. Arms without persistent sessions fall back to a
                # cold turn, which is exactly the cost `continuity` measures —
                # so this is not a special case, it is the measurement.
                #
                # A continuation that has to be *steerable* — scripted turns
                # or a scene arrive while it runs — needs a live handle. An
                # arm whose begin() is a turn on its standing session and whose
                # steering is live gets one; any other arm keeps the blocking
                # resume, whose handle refuses interjections, and the scenario
                # resolves UNSUPPORTED — which is the truthful outcome.
                steerable = bool(turns) or hasattr(scenario_module, "scene")
                live_channel = (
                    session.profile.steering == Steering.LIVE_INTERJECT
                    and session.profile.persistent_sessions
                )
                if (
                    live.get("continue")
                    and hasattr(session, "resume")
                    and not (steerable and live_channel)
                ):
                    handle = _Resumed(
                        session,
                        request_text,
                        live.get("sender"),
                        attachments=staged or None,
                    )
                else:
                    handle = session.begin(
                        request_text,
                        persist=bool(live.get("persist")),
                        context=live.get("context"),
                        sender=live.get("sender"),
                        images=live.get("images"),
                        attachments=staged or None,
                    )

                inter: Interlocutor | None = None
                if turns:

                    def deliver(turn, _h=handle, _p=pool):
                        if _p is not None:
                            _p.note_authored(turn.sender, turn.text)
                        try:
                            return _h.interject(turn.text, sender=turn.sender)
                        except Unsupported as exc:
                            return {
                                "delivered": False,
                                "mode": "unsupported",
                                "why": str(exc),
                            }

                    inter = Interlocutor(
                        fixture=fixture,
                        profile=session.profile,
                        turns=turns,
                        deliver=deliver,
                    ).start()

                # A scene: role-played people who speak in order, react to
                # what the assistant says, and stop when the scene is done.
                # Over voice the beats are spoken through the room after the
                # opening turn has settled; over text they are interjected
                # while it runs.
                director: RolePlayDirector | None = None
                if scene is not None and voice_t is None:
                    # A text scene is a group room. An arm with a native
                    # room surface may be told so before the lines arrive:
                    # they then reach it as room traffic (per-sender,
                    # group-addressed) rather than a stream of DMs. The
                    # opening request was already delivered 1:1 — the
                    # invitation is a message; the conversation is the room.
                    # Arms without the hook are unaffected.
                    if cast and hasattr(session, "open_room"):
                        session.open_room(participants=[p.id for p in cast])

                    def deliver_line(sender, text, _h=handle):
                        return _h.interject(text, sender=sender)

                    director = RolePlayDirector(
                        fixture=fixture,
                        scene=scene,
                        deliver=deliver_line,
                    ).start()

                reply = handle.wait(timeout=timeout_s)
                if voice_t is not None and scene is not None:
                    if live.get("voice_call"):
                        reply, journal = _run_call_scene(
                            voice_t,
                            session=session,
                            handle=handle,
                            scene=scene,
                            fixture=fixture,
                            reply=reply,
                            timeout_s=timeout_s,
                        )
                    else:
                        reply, journal = _run_voice_scene(
                            voice_t,
                            session=session,
                            handle=handle,
                            scene=scene,
                            fixture=fixture,
                            reply=reply,
                            timeout_s=timeout_s,
                        )
                    record["roleplay"] = journal
                    record["voice"] = voice_t.evidence()
                elif director is not None:
                    reply = _finish_scene(
                        director,
                        session=session,
                        handle=handle,
                        reply=reply,
                        timeout_s=timeout_s,
                    )
                    record["roleplay"] = director.journal()
                    if hasattr(session, "close_room"):
                        session.close_room()
                if inter is not None:
                    inter.stop()
                    record["interlocutor"] = inter.journal()

                # The people keep listening after the arm's turn resolves: a
                # question the arm put to a persona through any channel — its
                # reply, a bridged product send — gets that person's answer
                # back as ordinary inbound traffic, and the exchange loops
                # until nobody has anything left to say (or the round cap).
                # This is the duplex the clarification hook always faked: in
                # real operation a clarification IS a message on a channel.
                if pool is not None and reply.ok:
                    convo: list[dict[str, Any]] = []
                    reply = _persona_conversation(
                        session=session,
                        fixture=fixture,
                        pool=pool,
                        counterpart=str(live.get("sender") or default_who),
                        reply=reply,
                        journal=convo,
                    )
                    if convo:
                        record["conversation"] = convo
                record["reply"] = reply.as_dict()

                # The returned artifact. An arm whose product sends files on
                # its channel has already bridged them to /deliver; for a
                # workspace arm the harness is the bridge — the reply names a
                # path, or the newest file produced this scenario is taken,
                # and either way the bytes land with the fixture, the only
                # witness scoring reads.
                if (
                    live.get("expects_deliverable", bool(staged))
                    and fixture.recorder.count("deliver") == 0
                ):
                    record["deliverable_collection"] = _collect_deliverable(
                        session=session,
                        fixture=fixture,
                        reply=reply,
                        record=record,
                        staged=staged,
                        since=scenario_epoch,
                    )

                # A track may need more turns after the first completes.
                if hasattr(scenario_module, "followup"):
                    record["followup"] = scenario_module.followup(
                        name,
                        session=session,
                        fixture=fixture,
                        timeout_s=timeout_s,
                    )

                # Before scoring at all: did the run actually happen? An arm
                # that catches its own LLM failure and returns the message as
                # text is indistinguishable, to a scorer, from an arm that
                # did nothing — which is how an out-of-credit tenant produced
                # a full set of plausible-looking failures.
                marker = infra_failure(reply.text, reply.error)
                if marker:
                    result = ScenarioResult(
                        name,
                        Outcome.ERROR,
                        {"marker": marker, "reply": reply.text[:500]},
                        f"infrastructure failure ({marker}) — nothing was measured",
                    )
                elif reply.error.startswith(("timed out after", "no response within")):
                    # A scenario timeout is not a statement about the arm: the
                    # first unify sweep timed out on a broken provider path and
                    # its FAILs read as a teaching-track result. The error
                    # string stays in the run file, so a genuinely-hung arm is
                    # still visible — it just is not a scored loss.
                    result = ScenarioResult(
                        name,
                        Outcome.ERROR,
                        {"reply_error": reply.error},
                        "scenario timed out — nothing conclusive was measured",
                    )
                else:
                    # The scorer sees how the correction was delivered, so an
                    # arm with no steering mechanism resolves to UNSUPPORTED
                    # rather than being marked wrong for a capability it never
                    # had.
                    record["clarifications"] = session.clarifications()[
                        clarifications_before:
                    ]
                    # Every persona exchange this scenario, whichever channel
                    # carried it, with its label. DEGRADED pricing keys off
                    # the `restated` labels here — a spec re-supply over the
                    # product's message channel costs the same as one over
                    # the clarification hook.
                    if pool is not None:
                        record["persona"] = pool.exchanges()
                    result = scenario_module.score(name, fixture, record=record)
            except Unsupported as exc:
                result = ScenarioResult(
                    name,
                    Outcome.UNSUPPORTED,
                    {},
                    f"{session.profile.name} has no mechanism: {exc}",
                )
            except Exception as exc:  # noqa: BLE001 - recorded in the run file
                record["traceback"] = traceback.format_exc()[-4000:]
                # ERROR, not FAIL: nothing was measured, so this is not a
                # statement about the arm.
                result = ScenarioResult(
                    name,
                    Outcome.ERROR,
                    {},
                    f"harness error: {type(exc).__name__}: {exc}",
                )

            if voice_t is not None:
                voice_t.close()
            record["evidence"] = fixture.evidence()
            record["clarifications"] = session.clarifications()[clarifications_before:]
            pool = fixture.state.get("personas")
            if pool is not None:
                record["persona"] = pool.exchanges()
                # The leak guard: a persona reply that carried a forbidden
                # token was withheld from delivery and voids the cell —
                # neither a PASS the leak would gift nor a FAIL the arm never
                # earned. Repeats provide replacement samples.
                leaks = pool.leaks()
                if leaks:
                    result = ScenarioResult(
                        name,
                        Outcome.INVALID,
                        {
                            "leaks": [
                                {
                                    "persona": e.get("persona"),
                                    "channel": e.get("channel"),
                                    "tokens": e.get("leaked"),
                                }
                                for e in leaks
                            ],
                        },
                        "a persona reply carried forbidden content — the "
                        "cell is void; nothing about the arm was measured",
                    )
            record["cost"] = cost_delta(
                cost_before,
                session.cost_snapshot(),
                elapsed_seconds=time.monotonic() - scenario_started,
            )
            record["result"] = result.as_dict()
            results["scenarios"].append(record)
            outcomes.append(result)
            print(f"[{track}/{arm}] {name}: {result.outcome.value} {result.reason}")

            if shared_fixture is None:
                fixture.stop()
            if shared_session is None or own_session:
                session.close()
                record["artifacts"] = session.artifacts()
    finally:
        if shared_fixture is not None:
            shared_fixture.stop()
        if shared_session is not None:
            results["artifacts"] = shared_session.artifacts()
            shared_session.close()

    results["summary"] = summarize(outcomes)
    results["cost"] = total_cost(
        [s.get("cost") or {} for s in results["scenarios"]],
    )
    # The environment's own spend, beside the arm's figures and never added
    # to them. Per-scenario detail is in each scenario's evidence; the
    # ledger file (persona_ledger.jsonl) carries every exchange.
    results["persona_exchanges"] = sum(
        len((s.get("evidence") or {}).get("persona_exchanges") or [])
        for s in results["scenarios"]
    )
    results["persona_tokens"] = sum(
        int((s.get("evidence") or {}).get("persona_tokens") or 0)
        for s in results["scenarios"]
    )
    (results_dir / "results.json").write_text(
        json.dumps(results, indent=2, default=str),
    )
    print(f"\n[{track}/{arm}] {results_dir / 'results.json'}")
    print(json.dumps(results["summary"]["by_outcome"], indent=2))

    credited = results["summary"]["credited"]
    scoreable = results["summary"]["scoreable"]
    return 0 if scoreable and credited == scoreable else 1


def _persona_conversation(
    *,
    session: ArmSession,
    fixture: Any,
    pool: Any,
    counterpart: str,
    reply: Reply,
    journal: list[dict[str, Any]],
) -> Reply:
    """Let the people answer what the arm sent them, until quiet or the cap.

    Two sources feed the loop:

    * **Bridged product channels.** A fixture that witnesses arm→person
      messages (a delivery bridge re-posting sends, a documented reply
      route) declares them in ``fixture.state["persona_channels"]`` —
      recorder kind → ``{"who": <payload key>, "text": <payload key>,
      "channel": <name>}``. Tracks whose fixtures already answer inline
      (custody's pushback on ``/reply``) simply do not declare the kind.
    * **The reply channel itself.** The arm's turn text goes to whoever the
      scenario has talking to it — for CLI harnesses the conversation loop
      is the product's only channel, so the persona is simply the
      interlocutor there; for the unify arm, sends to the boss contact
      surface as the turn's reply text by design.

    Every message gets the persona's structured reply; ``silent`` is a real
    answer (a person does not acknowledge every FYI) and delivers nothing.
    A non-silent reply goes back through the arm's own resume path as an
    ordinary inbound message from that person — for a slept world this may
    legitimately wake a new boot, which is what a message arriving days
    later does. Messages the clarification hook already answered are not
    answered twice.
    """
    channels = dict(fixture.state.get("persona_channels") or {})
    cast = [p.participant for p in pool.personas.values()]
    seen: dict[str, int] = {kind: 0 for kind in channels}
    latest = reply
    # Scripted personas have no judgment to bring to unsolicited chat: the
    # deterministic path keeps exactly the turn structure the mock plans
    # were written against, while bridged channel traffic still routes.
    offer_chat = pool.impl != "scripted"
    for _ in range(PERSONA_ROUNDS):
        answered = {
            str(c.get("question") or "").strip() for c in session.clarifications()
        }
        inbound: list[tuple[str, str, str]] = []
        for kind, spec in channels.items():
            entries = fixture.recorder.all(kind)
            for e in entries[seen.get(kind, 0) :]:
                payload = e.get("payload") or {}
                who = resolve_recipient(
                    payload.get(str(spec.get("who") or "to")),
                    cast,
                )
                text = str(payload.get(str(spec.get("text") or "text")) or "")
                if (
                    who in pool.personas
                    and text.strip()
                    and text.strip() not in answered
                ):
                    inbound.append((who, text, str(spec.get("channel") or kind)))
            seen[kind] = len(entries)
        if offer_chat:
            text = (latest.text or "").strip()
            if text and counterpart in pool.personas and text not in answered:
                inbound.append((counterpart, text, "chat"))
            offer_chat = False
        if not inbound:
            break

        outgoing: list[tuple[Any, dict[str, Any]]] = []
        for who, text, channel in inbound:
            r = pool.reply(who, text, channel=channel)
            entry: dict[str, Any] = {
                "persona": who,
                "channel": channel,
                "label": r.label,
                "mode": r.mode,
                "delivered": False,
            }
            if r.leaked:
                entry["leaked"] = True
            journal.append(entry)
            if r.deliverable:
                outgoing.append((r, entry))
        if not outgoing:
            break
        if not hasattr(session, "resume"):
            # One-shot arms have no way to receive the answer. The person
            # spoke; nobody was there. Recorded as exactly that.
            for _r, entry in outgoing:
                entry["delivery"] = "no_resume_path"
            break
        delivered_any = False
        for r, entry in outgoing:
            try:
                latest = session.resume(r.text, sender=r.persona)
                entry["delivered"] = True
                entry["delivery"] = "resumed_turn"
                delivered_any = True
            except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
                entry["delivery"] = f"delivery_failed: {type(exc).__name__}: {exc}"
        if not delivered_any:
            break
        # Each delivered answer produced a fresh arm turn; its reply is a
        # new message to the counterpart, and its side effects are new
        # channel traffic — both are the next round's inbound.
        offer_chat = pool.impl != "scripted"
    return latest


def _voice_setup(session: ArmSession, live: dict[str, Any], name: str):
    """The voice transport for one scenario, or (None, why) to degrade.

    The distinction matters and is deliberate:

    - The **arm** has no way to join a room by audio → `Unsupported` raises
      out of here, and the scenario resolves UNSUPPORTED. Falling back to the
      text room would quietly score an arm's chat behaviour as if it had been
      on a call.
    - The **environment** cannot provide voice (no LiveKit, no TTS) → the
      scenario degrades to the text room and the reason is recorded on the
      run, so a text result is never read as a voice one.
    """
    if not (hasattr(session, "join_voice_room") and session.profile.supports("voice")):
        raise Unsupported(
            "no voice surface: this arm cannot join a room as an audio participant",
        )
    from colleague.harness.voice.transport import VoiceUnavailable, build_transport

    idents = tuple(live.get("assistant_identities") or ("assistant",))
    try:
        # An arm whose voice surface lives on its own substrate (hermes's
        # Discord voice, OpenClaw's phone call) assembles the harness-owned
        # room *on that substrate* — persona speakers and capture included —
        # and hands back the same transport shape. LiveKit remains the
        # default for arms without a substrate of their own (unify's
        # `unify_meet` room IS LiveKit, so the default is its product room).
        builder = getattr(session, "build_voice_transport", None)
        if builder is not None:
            return builder(scenario=name, assistant_identities=idents), ""
        return (
            build_transport(scenario=name, assistant_identities=idents),
            "",
        )
    except VoiceUnavailable as exc:
        return None, str(exc)


def _voice_call_setup(session: ArmSession, live: dict[str, Any], name: str, scene: Any):
    """The callee for one call scenario, or (None, why) — same split as rooms.

    An arm with no way to place a call resolves UNSUPPORTED; an environment
    that cannot stand the callee up cannot fall back to text at all (the
    caller refuses instead), because a call has no text form.
    """
    if not (
        hasattr(session, "attach_call_surface") and session.profile.supports("voice")
    ):
        raise Unsupported(
            "no telephony surface: this arm cannot place a phone call",
        )
    from colleague.harness.voice.callee import build_callee
    from colleague.harness.voice.transport import VoiceUnavailable

    try:
        return (
            build_callee(
                scenario=name,
                number=str(live.get("callee_number") or ""),
                answers=live.get("answers", True) is not False,
                first_speaker=scene.beats[0].who if scene.beats else None,
            ),
            "",
        )
    except VoiceUnavailable as exc:
        return None, str(exc)


def _run_call_scene(
    callee: Any,
    *,
    session: ArmSession,
    handle: RunHandle,
    scene: Any,
    fixture: Any,
    reply: Reply,
    timeout_s: float,
) -> tuple[Reply, list[dict[str, Any]]]:
    """Answer the arm's call, play the scene on the line, and drain.

    The opening turn has already completed (`reply`) — for a dialling arm
    that turn is where the call was placed. The callee answers through the
    exchange; the scene starts only once the arm's agent is actually on the
    line; afterwards the callee hangs up (the far leg dropping is how the arm
    learns the call is over) and the session is drained again so the
    post-call work — the outcome report — is in the record.
    """
    from colleague.harness.voice.director import VoiceRolePlayDirector

    journal: list[dict[str, Any]] = []
    room = callee.wait_for_call(timeout=min(300.0, timeout_s))
    if room is not None and scene.beats:
        director = VoiceRolePlayDirector(
            fixture=fixture,
            scene=scene,
            room=room,
        ).start()
        try:
            director.wait(timeout=timeout_s)
        finally:
            director.stop()
        journal = director.journal()
    else:
        # Nobody answered (or nobody dialled): there is no room to direct.
        # The fixture still learns the transport ran and the scene is over.
        fixture.state["transport"] = "voice"
        fixture.state["roleplay_done"] = True
    callee.hang_up()
    # The far leg dropping reaches the arm across a pipeline of its own
    # moments — the agent's disconnect detection, an IPC event, a debounced
    # brain run, an actor POSTing the outcome — and a single quiescence check
    # can land in any of the gaps between them. So the drain is a bounded
    # window: keep draining until the outcome is on the record or the window
    # closes. Time, not capability — an arm that never reports still never
    # reports, and the scorer reads exactly that.
    latest = reply
    deadline = time.monotonic() + 90.0
    while True:
        time.sleep(3.0)
        try:
            drained = handle.wait(timeout=timeout_s)
            if drained.ok or not latest.ok:
                latest = drained
        except Exception:  # noqa: BLE001 - the opening reply stands
            break
        if fixture.recorder.all("outcome") or time.monotonic() >= deadline:
            break
    detach = getattr(session, "detach_call_surface", None)
    if detach is not None:
        try:
            detach()
        except Exception:  # noqa: BLE001 - teardown is best-effort
            pass
    return latest, journal


def _run_voice_scene(
    voice_t: Any,
    *,
    session: ArmSession,
    handle: RunHandle,
    scene: Any,
    fixture: Any,
    reply: Reply,
    timeout_s: float,
) -> tuple[Reply, list[dict[str, Any]]]:
    """Join the arm to the room, play the scene through it, and drain.

    The opening turn has already completed (`reply`), so the arm knows the
    situation before anyone speaks. The arm joins through its own voice
    surface with the invite; the personas speak through their tracks; the
    room's capture feeds the fixture recorder. Afterwards the arm leaves and
    the session is drained once more so work commanded during the call is in
    the record.
    """
    from colleague.harness.voice.director import VoiceRolePlayDirector

    personas = sorted({b.who for b in scene.beats})
    session.join_voice_room(
        voice_t.invite,
        on_text=voice_t.room.note_assistant_text,
        personas=personas,
    )
    director = VoiceRolePlayDirector(
        fixture=fixture,
        scene=scene,
        room=voice_t.room,
    ).start()
    try:
        director.wait(timeout=timeout_s)
    finally:
        director.stop()
        leave = getattr(session, "leave_voice_room", None)
        if leave is not None:
            try:
                leave()
            except Exception:  # noqa: BLE001 - teardown is best-effort
                pass
    latest = reply
    try:
        drained = handle.wait(timeout=timeout_s)
        if drained.ok or not latest.ok:
            latest = drained
    except Exception:  # noqa: BLE001 - the opening reply stands
        pass
    return latest, director.journal()


def _finish_scene(
    director: RolePlayDirector,
    *,
    session: ArmSession,
    handle: RunHandle,
    reply: Reply,
    timeout_s: float,
) -> Reply:
    """Let a scene play out against whatever channel the arm has.

    Live-interject arms received every line while the first turn ran and
    keep processing on their own loop; the arm is drained again once the
    roles are done so late answers are in the record. Arms with no way in
    left lines *pending*; those are fed as continuation turns through the
    arm's resume path — a queued delivery, recorded as one — or recorded as
    not delivered when there is no such path either.
    """
    director.wait(timeout=timeout_s)
    latest = reply
    while True:
        said = director.pop_pending()
        if said is None:
            break
        if hasattr(session, "resume"):
            latest = session.resume(said.text, sender=said.who)
            director.note_delivered(said, "resumed_turn")
        else:
            director.note_delivered(said, "not_delivered")
    director.stop()
    # A second drain for arms that took lines live after the first wait.
    try:
        drained = handle.wait(timeout=timeout_s)
        if drained.ok or not latest.ok:
            latest = drained
    except Exception:  # noqa: BLE001 - the first reply stands
        pass
    return latest


def env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))
