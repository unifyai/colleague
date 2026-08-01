"""One runner for every track.

A track supplies three things and gets a driver for free:

    fixture.build(seed=, port=)     -> FixtureServer
    scenario.scenarios(base_url)    -> [{name, context, request, ...}]
    scenario.score(name, fixture)   -> ScenarioResult

Optionally it also supplies ``scenario.turns(name, ...)`` returning scripted
interlocutor turns, and ``SESSION_SCOPE`` to say whether the arm session is
rebuilt per scenario (the default) or held across the whole track — which
`continuity` needs, since a session surviving between requests is the thing
under test.

Each scenario gets a fresh fixture, so the recorder contains only that
scenario's side effects and scoring never has to filter by time.
"""

from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from colleague.arms.sessions import build as build_session
from colleague.harness.capability import Outcome, ScenarioResult, summarize
from colleague.harness.interlocutor import Interlocutor
from colleague.harness.session import ArmSession, Unsupported


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
    if arm == "unify":
        return build_session("unify", run_id=run_id, track=track)
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
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + f"-{arm}"
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

    outcomes: list[ScenarioResult] = []
    try:
        for spec in scenario_module.scenarios("http://placeholder"):
            name = spec["name"]
            if only and name != only:
                continue

            fixture = fixture_module.build(seed=seed, port=port).start()
            # Scenario text is regenerated against the live port.
            live = next(
                s
                for s in scenario_module.scenarios(fixture.base_url)
                if s["name"] == name
            )
            session = shared_session or _session_for(
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
            record: dict[str, Any] = {"name": name, "note": live.get("note", "")}
            print(f"[{track}/{arm}] scenario {name} — fixture {fixture.base_url}")

            try:
                if shared_session is None:
                    session.setup()
                    results.setdefault("profile", session.profile.name)

                turns = []
                if hasattr(scenario_module, "turns"):
                    turns = scenario_module.turns(name) or []

                handle = session.begin(
                    live["request"],
                    persist=bool(live.get("persist")),
                    context=live.get("context"),
                    sender=live.get("sender"),
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

                reply = handle.wait(timeout=timeout_s)
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

                # The scorer sees how the correction was delivered, so an arm
                # with no steering mechanism resolves to UNSUPPORTED rather
                # than being marked wrong for a capability it never had.
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
                result = ScenarioResult(
                    name,
                    Outcome.FAIL,
                    {},
                    f"harness error: {type(exc).__name__}: {exc}",
                )

            record["evidence"] = fixture.evidence()
            record["result"] = result.as_dict()
            results["scenarios"].append(record)
            outcomes.append(result)
            print(f"[{track}/{arm}] {name}: {result.outcome.value} {result.reason}")

            fixture.stop()
            if shared_session is None:
                session.close()
    finally:
        if shared_session is not None:
            results["artifacts"] = shared_session.artifacts()
            shared_session.close()

    results["summary"] = summarize(outcomes)
    (results_dir / "results.json").write_text(
        json.dumps(results, indent=2, default=str)
    )
    print(f"\n[{track}/{arm}] {results_dir / 'results.json'}")
    print(json.dumps(results["summary"]["by_outcome"], indent=2))

    credited = results["summary"]["credited"]
    scoreable = results["summary"]["scoreable"]
    return 0 if scoreable and credited == scoreable else 1


def env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))
