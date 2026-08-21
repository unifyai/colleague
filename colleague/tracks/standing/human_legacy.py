"""Human protocols for the three standing experiments predating ``series``.

These use the experiments' existing fixtures and exact scorers. They share
the same operator/builder distinction as ``series.human_arm``; this module is
compatibility glue, not a second scoring implementation.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO

from colleague.arms.sessions.human_session import HumanSession
from colleague.harness.cost import delta as cost_delta
from colleague.harness.cost import total as total_cost


class Protocol:
    def __init__(
        self,
        *,
        name: str,
        directory: Path,
        fixture: Any,
        mode: str,
        participant_id: str,
        hourly_rate_usd: float,
        timeout_s: float,
        input_fn: Callable[[str], str] = input,
        output: TextIO | None = None,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
        results_root: Path | None = None,
    ) -> None:
        self.name = name
        self.mode = mode
        self.fixture = fixture
        self.timeout_s = timeout_s
        self.run_id = (
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + f"-human-{mode}"
        )
        self.results_dir = (results_root or directory / "results") / self.run_id
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.session = HumanSession(
            results_dir=self.results_dir,
            participant_id=participant_id,
            hourly_rate_usd=hourly_rate_usd,
            input_fn=input_fn,
            output=output,
            event_sink=event_sink,
        )
        self.commands: dict[str, str] = {}
        self.phases: list[dict[str, Any]] = []
        self.results: dict[str, Any] = {
            "experiment": name,
            "system": "human",
            "human_mode": mode,
            "participant_id": participant_id,
            "human_hourly_rate_usd": hourly_rate_usd,
            "run_id": self.run_id,
            "phases": self.phases,
            "fires": [],
        }

    def phase(self, name: str, fn: Callable[[], Any]) -> Any:
        before = self.session.cost_snapshot()
        started = time.monotonic()
        value = fn()
        cost = cost_delta(
            before,
            self.session.cost_snapshot(),
            elapsed_seconds=time.monotonic() - started,
        )
        self.phases.append(
            {
                "name": name,
                "wall_seconds": cost["elapsed_seconds"],
                "provider_cost_usd": None,
                "human_active_seconds": cost.get("human_active_seconds", 0.0),
                "human_hourly_rate_usd": cost.get("human_hourly_rate_usd"),
                "human_labor_cost_usd": cost.get("human_labor_cost_usd", 0.0),
                "llm_calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost": cost,
            },
        )
        return value

    def latest_cost(self) -> dict[str, Any]:
        return dict(self.phases[-1]["cost"])

    def setup_one(self, key: str, utterance: str) -> None:
        self.session.bind_fixture(self.fixture, f"setup_{key}")
        context = (
            "Build this automation in the persistent workspace with /shell. "
            "Finish with /done COMMAND, the command to run at each wake."
            if self.mode == "builder"
            else "Read this brief. You will manually perform it at each simulated wake."
        )
        reply = self.phase(
            f"setup_{key}",
            lambda: self.session.send(utterance, context=context, persist=True),
        )
        if self.mode == "builder":
            command = reply.text.strip()
            if not command:
                raise RuntimeError(f"no fire command supplied for {key}")
            self.commands[key] = command

    def owner_message(self, text: str) -> None:
        self.session.bind_fixture(self.fixture, "policy_change")
        context = (
            "Update every affected artifact in the persistent workspace. Keep "
            "the existing fire commands unless necessary; finish with /done."
            if self.mode == "builder"
            else "Apply this update to all subsequent manual work."
        )
        self.phase(
            "policy_change",
            lambda: self.session.send(text, context=context, persist=True),
        )

    def fire(self, key: str, label: str) -> dict[str, Any]:
        self.session.bind_fixture(self.fixture, label)
        if self.mode == "operator":
            reply = self.phase(
                label,
                lambda: self.session.send(
                    f"The {key} recurring work is due. Complete exactly one run now.",
                    context="SIMULATED WAKE",
                    persist=True,
                    timeout=self.timeout_s,
                ),
            )
            return {
                "label": label,
                "fire_mode": "human_operator",
                "ok": reply.ok,
                "cost": self.latest_cost(),
            }

        def execute() -> dict[str, Any]:
            env = dict(os.environ)
            env["COLLEAGUE_FIXTURE_URL"] = self.fixture.base_url
            try:
                done = subprocess.run(
                    self.commands[key],
                    cwd=self.session.workspace,
                    env=env,
                    shell=True,
                    text=True,
                    capture_output=True,
                    timeout=self.timeout_s,
                    check=False,
                )
                return {
                    "fire_mode": "human_built_artifact",
                    "exit_code": done.returncode,
                    "stdout_tail": done.stdout[-2000:],
                    "stderr_tail": done.stderr[-2000:],
                }
            except subprocess.TimeoutExpired as exc:
                return {"fire_mode": "human_built_artifact", "error": str(exc)}

        value = self.phase(label, execute)
        return {"label": label, **value, "cost": self.latest_cost()}

    def finish(self) -> None:
        self.results["commands"] = dict(self.commands)
        self.results["artifacts"] = self.session.artifacts()
        self.results["cost"] = total_cost([p["cost"] for p in self.phases])
        self.results["finished_at"] = datetime.now(timezone.utc).isoformat()
        (self.results_dir / "results.json").write_text(
            json.dumps(self.results, indent=2, default=str),
            encoding="utf-8",
        )
        lines = [
            f"# {self.name} (human-{self.mode}) — {self.run_id}",
            "",
            "| phase | wall (s) | human active (s) | labour USD |",
            "|---|---:|---:|---:|",
        ]
        for p in self.phases:
            lines.append(
                f"| {p['name']} | {p['wall_seconds']} | "
                f"{p['human_active_seconds']} | {p['human_labor_cost_usd']} |",
            )
        lines += [
            "",
            f"Correct fires: {sum(1 for r in self.results['fires'] if r.get('correct'))} "
            f"/ {len(self.results['fires'])}",
        ]
        (self.results_dir / "summary.md").write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )
        self.fixture.stop()
        print("\n".join(lines))
        print(f"[done] results in {self.results_dir}")


def recurring_report(
    *,
    mode: str,
    hourly_rate_usd: float,
    participant_id: str,
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
    event_sink: Callable[[dict[str, Any]], None] | None = None,
    results_root: Path | None = None,
) -> int:
    from colleague.tracks.standing.recurring_report.fixture import (
        DEFAULT_PORT,
        DEFAULT_SEED,
        FixtureServer,
        expected_report,
        score_report,
    )
    from colleague.tracks.standing.recurring_report.harness import (
        EXPERIMENT_DIR,
        UTTERANCE_TEMPLATE,
    )

    seed = int(os.environ.get("RWR_SEED", DEFAULT_SEED))
    port = int(os.environ.get("RWR_PORT", DEFAULT_PORT))
    runs = int(os.environ.get("RWR_RUNS", "4"))
    timeout = float(os.environ.get("RWR_PHASE_TIMEOUT_S", "1800"))
    fixture = FixtureServer(seed=seed, port=port).start()
    p = Protocol(
        name="recurring_report",
        directory=EXPERIMENT_DIR,
        fixture=fixture,
        mode=mode,
        participant_id=participant_id,
        hourly_rate_usd=hourly_rate_usd,
        timeout_s=timeout,
        input_fn=input_fn,
        output=output,
        event_sink=event_sink,
        results_root=results_root,
    )
    try:
        utterance = UTTERANCE_TEMPLATE.format(base_url=fixture.base_url)
        p.results.update({"seed": seed, "n_runs": runs, "utterance": utterance})
        p.session.setup()
        p.setup_one("report", utterance)
        seen = 0
        for i in range(1, runs + 1):
            run_date = datetime.now(timezone.utc).date()
            fired = p.fire("report", f"run_{i}")
            delivered = fixture.sink.snapshot()[seen:]
            seen += len(delivered)
            expected = expected_report(seed, run_date)
            scores = [score_report(r["body"], expected) for r in delivered]
            p.results["fires"].append(
                {
                    "fire": i,
                    **fired,
                    "reports_delivered": len(delivered),
                    "scores": scores,
                    "correct": len(delivered) == 1 and scores[0]["correct"],
                },
            )
    finally:
        p.finish()
    return 0


def semantic_triage(
    *,
    mode: str,
    hourly_rate_usd: float,
    participant_id: str,
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
    event_sink: Callable[[dict[str, Any]], None] | None = None,
    results_root: Path | None = None,
) -> int:
    from colleague.tracks.standing.semantic_triage.fixture import (
        DEFAULT_PORT,
        DEFAULT_SEED,
        TriageFixtureServer,
    )
    from colleague.tracks.standing.semantic_triage.protocol import (
        N_FIRES,
        UTTERANCE_TEMPLATE,
        prepare_fire,
        score_fire,
    )

    directory = Path(__file__).resolve().parent / "semantic_triage"
    seed = int(os.environ.get("ST_SEED", DEFAULT_SEED))
    port = int(os.environ.get("ST_PORT", DEFAULT_PORT))
    timeout = float(os.environ.get("ST_PHASE_TIMEOUT_S", "1800"))
    fixture = TriageFixtureServer(seed=seed, port=port).start()
    p = Protocol(
        name="semantic_triage",
        directory=directory,
        fixture=fixture,
        mode=mode,
        participant_id=participant_id,
        hourly_rate_usd=hourly_rate_usd,
        timeout_s=timeout,
        input_fn=input_fn,
        output=output,
        event_sink=event_sink,
        results_root=results_root,
    )
    try:
        utterance = UTTERANCE_TEMPLATE.format(base_url=fixture.base_url)
        p.results.update({"seed": seed, "n_fires": N_FIRES, "utterance": utterance})
        p.session.setup()
        p.setup_one("triage", utterance)
        for i in range(1, N_FIRES + 1):
            cursor, released, before = prepare_fire(fixture)
            fired = p.fire("triage", f"fire_{i}")
            p.results["fires"].append(
                {
                    "fire": i,
                    **fired,
                    **score_fire(
                        fixture,
                        cursor_before=cursor,
                        released_now=released,
                        batches_before=before,
                    ),
                },
            )
    finally:
        p.finish()
    return 0


def policy_propagation(
    *,
    mode: str,
    hourly_rate_usd: float,
    participant_id: str,
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
    event_sink: Callable[[dict[str, Any]], None] | None = None,
    results_root: Path | None = None,
) -> int:
    from colleague.tracks.standing.policy_propagation.fixture import (
        DEFAULT_PORT,
        DEFAULT_SEED,
        INITIAL_THRESHOLD,
        POLICY_UPDATE_MESSAGE,
        UPDATED_THRESHOLD,
        PolicyFixtureServer,
    )
    from colleague.tracks.standing.policy_propagation.protocol import (
        AUTOMATIONS,
        POST_CHANGE_ROUNDS,
        PRE_CHANGE_ROUNDS,
        build_utterance,
        prepare_fire,
        release_round,
        score_fire,
    )

    directory = Path(__file__).resolve().parent / "policy_propagation"
    seed = int(os.environ.get("PP_SEED", DEFAULT_SEED))
    port = int(os.environ.get("PP_PORT", DEFAULT_PORT))
    timeout = float(os.environ.get("PP_PHASE_TIMEOUT_S", "1800"))
    fixture = PolicyFixtureServer(seed=seed, port=port).start()
    p = Protocol(
        name="policy_propagation",
        directory=directory,
        fixture=fixture,
        mode=mode,
        participant_id=participant_id,
        hourly_rate_usd=hourly_rate_usd,
        timeout_s=timeout,
        input_fn=input_fn,
        output=output,
        event_sink=event_sink,
        results_root=results_root,
    )
    try:
        utterances = {a: build_utterance(a, fixture.base_url) for a in AUTOMATIONS}
        p.results.update({"seed": seed, "utterances": utterances})
        p.session.setup()
        for automation in AUTOMATIONS:
            p.setup_one(automation, utterances[automation])

        round_no = 0

        def run_round(threshold: int) -> None:
            nonlocal round_no
            round_no += 1
            release_round(fixture)
            for automation in AUTOMATIONS:
                cursor, released, before = prepare_fire(fixture, automation)
                fired = p.fire(automation, f"round{round_no}_{automation}")
                p.results["fires"].append(
                    {
                        "round": round_no,
                        "automation": automation,
                        "threshold": threshold,
                        **fired,
                        **score_fire(
                            fixture,
                            automation,
                            cursor_before=cursor,
                            released_now=released,
                            batches_before=before,
                            threshold=threshold,
                        ),
                    },
                )

        for _ in range(PRE_CHANGE_ROUNDS):
            run_round(INITIAL_THRESHOLD)
        p.owner_message(POLICY_UPDATE_MESSAGE)
        for _ in range(POST_CHANGE_ROUNDS):
            run_round(UPDATED_THRESHOLD)
    finally:
        p.finish()
    return 0


RUNNERS = {
    "recurring_report": recurring_report,
    "semantic_triage": semantic_triage,
    "policy_propagation": policy_propagation,
}
