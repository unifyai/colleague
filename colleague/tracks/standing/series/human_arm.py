"""Human operator and human builder protocols for fire-series experiments.

``operator`` is the ARC-like baseline: the participant handles every wake in
the workbench and is charged for that labour. ``builder`` preserves the
standing track's architectural question: the participant authors an artifact
once, the harness freezes and fires it unattended, and the participant returns
only for owner messages or the protocol's explicit operator-fix point.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from colleague.arms.sessions.human_session import HumanSession
from colleague.harness.cost import delta as cost_delta
from colleague.tracks.standing.series.report import finalize
from colleague.tracks.standing.series.spec import Experiment, messages_since


class HumanStandingArm:
    name = "human"

    def __init__(
        self,
        *,
        fixture: Any,
        results_dir: Path,
        mode: str,
        hourly_rate_usd: float,
        participant_id: str,
        timeout_s: float,
    ) -> None:
        self.fixture = fixture
        self.results_dir = results_dir
        self.mode = mode
        self.timeout_s = timeout_s
        self.session = HumanSession(
            results_dir=results_dir,
            hourly_rate_usd=hourly_rate_usd,
            participant_id=participant_id,
        )
        self.session.bind_fixture(fixture, "setup")
        self.command = ""

    @property
    def workspace(self) -> Path:
        return self.session.workspace

    def start(self) -> None:
        self.session.setup()

    def setup(self, utterance: str) -> dict[str, Any]:
        if self.mode == "builder":
            context = (
                "HUMAN-BUILDER PROTOCOL\n"
                "Build the recurring automation in the persistent workspace. "
                "You may use /shell and the API documented below. Finish with "
                "/done COMMAND, where COMMAND is the workspace-relative shell "
                "command the harness should execute on every simulated wake. "
                "After setup you will not be present for ordinary fires."
            )
        else:
            context = (
                "HUMAN-OPERATOR PROTOCOL\n"
                "Read the recurring-work brief now. At each simulated wake you "
                "will return to perform one run manually through the workbench. "
                "Finish setup with /done."
            )
        reply = self.session.send(utterance, context=context, persist=True)
        if self.mode == "builder":
            self.command = reply.text.strip()
        return {"ok": reply.ok, "command": self.command or None, "mode": self.mode}

    def automation_ready(self) -> tuple[bool, str]:
        if self.mode == "operator":
            return True, "manual operator will handle every simulated wake"
        if not self.command:
            return False, "builder supplied no fire command"
        return True, f"human-authored command: {self.command}"

    def message(self, text: str, *, label: str) -> dict[str, Any]:
        self.session.bind_fixture(self.fixture, label)
        context = (
            "OWNER MESSAGE\nApply this update to the existing artifact. Use "
            "/shell as needed. Finish with /done and, only if the fire command "
            "changed, put the replacement command after /done."
            if self.mode == "builder"
            else "OWNER MESSAGE\nTake this into account on later manual wakes."
        )
        reply = self.session.send(text, context=context, persist=True)
        if self.mode == "builder" and reply.text.strip():
            self.command = reply.text.strip()
        return {"ok": reply.ok, "command": self.command or None}

    def fire(self, label: str) -> dict[str, Any]:
        self.session.bind_fixture(self.fixture, label)
        if self.mode == "operator":
            reply = self.session.send(
                "The recurring work is due now. Complete exactly one run against "
                "the documented fixture, then finish with /done.",
                context="SIMULATED WAKE",
                persist=True,
                timeout=self.timeout_s,
            )
            return {"ok": reply.ok, "fire_mode": "human_operator"}
        env = dict(os.environ)
        env["COLLEAGUE_FIXTURE_URL"] = self.fixture.base_url
        try:
            completed = subprocess.run(
                self.command,
                cwd=self.workspace,
                env=env,
                shell=True,
                text=True,
                capture_output=True,
                timeout=self.timeout_s,
                check=False,
            )
            return {
                "fire_mode": "human_built_artifact",
                "exit_code": completed.returncode,
                "stdout_tail": completed.stdout[-2000:],
                "stderr_tail": completed.stderr[-2000:],
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "fire_mode": "human_built_artifact",
                "exit_code": None,
                "error": f"timed out after {exc.timeout}s",
            }

    def snapshot(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "command": self.command or None,
            "workspace_files": sorted(
                str(p.relative_to(self.workspace))
                for p in self.workspace.rglob("*")
                if p.is_file()
            ),
            "cost": self.session.cost_snapshot(),
        }


def run(
    experiment: Experiment,
    *,
    mode: str = "builder",
    hourly_rate_usd: float = 30.0,
    participant_id: str = "anonymous",
) -> int:
    prefix = experiment.env_prefix
    seed = int(os.environ.get(f"{prefix}_SEED", experiment.default_seed))
    port = int(os.environ.get(f"{prefix}_PORT", experiment.default_port))
    timeout_s = float(os.environ.get(f"{prefix}_PHASE_TIMEOUT_S", "1800"))
    run_id = (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        + experiment.run_suffix()
        + f"-human-{mode}"
    )
    results_dir = experiment.directory / "results" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)
    fixture = experiment.build_fixture(seed=seed, port=port).start()
    arm = HumanStandingArm(
        fixture=fixture,
        results_dir=results_dir,
        mode=mode,
        hourly_rate_usd=hourly_rate_usd,
        participant_id=participant_id,
        timeout_s=timeout_s,
    )
    utterance = experiment.utterance(fixture.base_url)
    phases: list[dict[str, Any]] = []
    results: dict[str, Any] = {
        "experiment": experiment.name,
        "variant": experiment.variant(),
        "system": "human",
        "human_mode": mode,
        "participant_id": participant_id,
        "human_hourly_rate_usd": hourly_rate_usd,
        "run_id": run_id,
        "seed": seed,
        "n_fires": experiment.n_fires,
        "utterance": utterance,
        "operator_fix_after_failures": experiment.operator_fix_after_failures,
        "operator_fix_message": experiment.operator_fix_message,
        **experiment.describe(),
        "messages": [],
        "fires": [],
    }

    def phase(name: str, fn):
        before = arm.session.cost_snapshot()
        started = time.monotonic()
        out = fn()
        cost = cost_delta(
            before,
            arm.session.cost_snapshot(),
            elapsed_seconds=time.monotonic() - started,
        )
        phases.append(
            {
                "name": name,
                "wall_seconds": cost["elapsed_seconds"],
                "llm_calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "provider_cost_usd": None,
                "by_purpose": {},
                "cost": cost,
                **{k: v for k, v in cost.items() if k.startswith("human_")},
            },
        )
        return out

    consecutive_noncorrect = 0
    operator_fix_done = False
    try:
        arm.start()
        results["setup"] = phase("setup", lambda: arm.setup(utterance))
        results["profile_after_setup"] = arm.snapshot()
        ready, note = arm.automation_ready()
        if not ready:
            results["setup_error"] = note
            return 1
        for i in range(1, experiment.n_fires + 1):
            label = experiment.label(i)
            events = experiment.before_fire(fixture, i)
            for k, text in enumerate(experiment.operator_messages(i, fixture.base_url)):
                phase_name = f"message_{i}" if k == 0 else f"message_{i}_{k}"
                out = phase(
                    phase_name,
                    lambda t=text, n=phase_name: arm.message(t, label=n),
                )
                results["messages"].append(
                    {"before_fire": i, "phase": phase_name, "text": text, **out},
                )
            threshold = experiment.operator_fix_after_failures
            if (
                threshold is not None
                and consecutive_noncorrect >= threshold
                and not operator_fix_done
            ):
                out = phase(
                    "operator_fix",
                    lambda: arm.message(
                        experiment.operator_fix_message,
                        label="operator_fix",
                    ),
                )
                results["operator_fix"] = {**out, "before_fire": i}
                operator_fix_done = True
            ctx = experiment.prepare_fire(fixture)
            ctx["fire"] = i
            owner_before = len(fixture.state["owner"])
            fired = phase(label, lambda n=label: arm.fire(n))
            row = {
                "fire": i,
                "label": label,
                "events": events,
                **fired,
                **experiment.score_fire(
                    fixture,
                    ctx,
                    messages=messages_since(fixture, owner_before),
                ),
            }
            results["fires"].append(row)
            consecutive_noncorrect = 0 if row["correct"] else consecutive_noncorrect + 1
        results["profile_final"] = arm.snapshot()
    finally:
        results["artifacts"] = arm.session.artifacts()
        summary = finalize(
            results,
            phases=phases,
            results_dir=results_dir,
            experiment=experiment,
            arm=f"human-{mode}",
        )
        fixture.stop()
        print(summary)
        print(f"[done] results in {results_dir}")
    return 0


def main(experiment: Experiment, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=f"human-{experiment.name}")
    parser.add_argument("--mode", choices=("operator", "builder"), default="builder")
    parser.add_argument("--hourly-rate-usd", type=float, default=30.0)
    parser.add_argument("--participant-id", default="anonymous")
    args = parser.parse_args(argv)
    return run(
        experiment,
        mode=args.mode,
        hourly_rate_usd=args.hourly_rate_usd,
        participant_id=args.participant_id,
    )
