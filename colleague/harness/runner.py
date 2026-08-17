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
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from colleague.arms.sessions import build as build_session
from colleague.harness.capability import Outcome, ScenarioResult, Steering, summarize
from colleague.harness.interlocutor import Interlocutor
from colleague.harness.roleplay import RolePlayDirector
from colleague.harness.scoring import infra_failure
from colleague.harness.session import ArmSession, Reply, RunHandle, Unsupported


class _Resumed(RunHandle):
    """A continuation of an open session, presented as an ordinary run."""

    def __init__(self, session: ArmSession, text: str, sender: str | None) -> None:
        self._session = session
        self._text = text
        self._sender = sender
        self._reply: Reply | None = None

    def wait(self, timeout: float = 900.0) -> Reply:
        if self._reply is None:
            try:
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
) -> ArmSession:
    if arm == "mock":
        return build_session("mock", mode=mode)
    if arm in ("unify", "unify-cm"):
        return build_session(
            arm,
            run_id=run_id,
            track=track,
            results_dir=results_dir,
        )
    return build_session(
        arm,
        results_dir=results_dir,
        run_id=run_id,
        timeout_s=timeout_s,
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
        "scenarios": [],
    }

    shared_session: ArmSession | None = None
    if session_scope == "track":
        shared_session = _session_for(
            arm,
            track=track,
            run_id=run_id,
            results_dir=results_dir,
            timeout_s=timeout_s,
            mode=mode,
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

            if shared_fixture is not None:
                fixture = shared_fixture
                fixture.reset_observations()
            else:
                fixture = fixture_module.build(seed=seed, port=port).start()
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
            own_session = bool(live.get("fresh_session"))
            session = (None if own_session else shared_session) or _session_for(
                arm,
                track=track,
                run_id=f"{run_id}-{name}",
                results_dir=results_dir / name,
                timeout_s=timeout_s,
                mode=mode,
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
            print(f"[{track}/{arm}] scenario {name} — fixture {fixture.base_url}")

            try:
                if shared_session is None or own_session:
                    session.setup()

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
                pool = fixture.state.get("personas")
                if pool is not None:
                    default_who = str(live.get("clarify_persona") or "daniel")
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
                    handle = _Resumed(session, live["request"], live.get("sender"))
                else:
                    handle = session.begin(
                        live["request"],
                        persist=bool(live.get("persist")),
                        context=live.get("context"),
                        sender=live.get("sender"),
                        images=live.get("images"),
                    )

                inter: Interlocutor | None = None
                if turns:

                    def deliver(turn, _h=handle):
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
                director: RolePlayDirector | None = None
                scene = (
                    scenario_module.scene(name)
                    if hasattr(scenario_module, "scene")
                    else None
                )
                if scene is not None:

                    def deliver_line(sender, text, _h=handle):
                        return _h.interject(text, sender=sender)

                    director = RolePlayDirector(
                        fixture=fixture,
                        scene=scene,
                        deliver=deliver_line,
                    ).start()

                reply = handle.wait(timeout=timeout_s)
                if director is not None:
                    reply = _finish_scene(
                        director,
                        session=session,
                        handle=handle,
                        reply=reply,
                        timeout_s=timeout_s,
                    )
                    record["roleplay"] = director.journal()
                if inter is not None:
                    inter.stop()
                    record["interlocutor"] = inter.journal()
                record["reply"] = reply.as_dict()

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
                    record["clarifications"] = session.clarifications()
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

            record["evidence"] = fixture.evidence()
            record["clarifications"] = session.clarifications()
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
    (results_dir / "results.json").write_text(
        json.dumps(results, indent=2, default=str),
    )
    print(f"\n[{track}/{arm}] {results_dir / 'results.json'}")
    print(json.dumps(results["summary"]["by_outcome"], indent=2))

    credited = results["summary"]["credited"]
    scoreable = results["summary"]["scoreable"]
    return 0 if scoreable and credited == scoreable else 1


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
