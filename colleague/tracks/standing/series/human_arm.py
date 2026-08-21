"""Direct human protocol for fire-series experiments.

The participant performs every simulated occurrence themselves. Repetition,
retained notes and growing familiarity are human analogues of a harness reusing
durable machinery; the protocol never asks the participant to write code or
construct a technical implementation.
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO

from colleague.arms.sessions.human_session import HumanSession
from colleague.harness.cost import delta as cost_delta
from colleague.tracks.standing.human_brief import (
    PARTICIPANT_UPDATE_REQUEST,
    REQUEST_DUE,
    REQUEST_SETUP,
    direct_work_brief,
    human_update_request,
    standing_surface,
)
from colleague.tracks.standing.series.report import finalize
from colleague.tracks.standing.series.spec import Experiment, messages_since


class HumanStandingArm:
    name = "human"

    def __init__(
        self,
        *,
        fixture: Any,
        results_dir: Path,
        hourly_rate_usd: float,
        participant_id: str,
        timeout_s: float,
        input_fn: Callable[[str], str] = input,
        output: TextIO | None = None,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.fixture = fixture
        self.results_dir = results_dir
        self.timeout_s = timeout_s
        self.session = HumanSession(
            results_dir=results_dir,
            hourly_rate_usd=hourly_rate_usd,
            participant_id=participant_id,
            input_fn=input_fn,
            output=output,
            event_sink=event_sink,
        )
        self.session.bind_fixture(fixture, "setup")

    def start(self) -> None:
        self.session.setup()

    def _present(self, surface: dict[str, Any] | None, request: str) -> None:
        self.session.surface = {**surface, "request": request} if surface else None

    def setup(
        self,
        utterance: str,
        *,
        surface: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = (
            "RECURRING WORK\n"
            "Read the brief now. Each time this work becomes due, you will "
            "complete it yourself through the workbench. You may retain notes "
            "and use what you learn from earlier occurrences."
        )
        self._present(surface, REQUEST_SETUP)
        reply = self.session.send(
            direct_work_brief(utterance),
            context=context,
            persist=True,
        )
        return {"ok": reply.ok}

    def message(
        self,
        text: str,
        *,
        label: str,
        surface: dict[str, Any] | None = None,
        request: str | None = None,
    ) -> dict[str, Any]:
        self.session.bind_fixture(self.fixture, label)
        self._present(surface, request or direct_work_brief(text))
        reply = self.session.send(
            direct_work_brief(text),
            context="UPDATE\nApply this information to later occurrences of the work.",
            persist=True,
        )
        return {"ok": reply.ok}

    def fire(
        self,
        label: str,
        *,
        surface: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.session.bind_fixture(self.fixture, label)
        self._present(surface, REQUEST_DUE)
        reply = self.session.send(
            "The recurring work is due now. Complete one occurrence using the "
            "available workspace information, then finish the task.",
            context="WORK DUE",
            persist=True,
            timeout=self.timeout_s,
        )
        return {"ok": reply.ok}

    def snapshot(self) -> dict[str, Any]:
        return {
            "cost": self.session.cost_snapshot(),
            "turns": self.session.cost_snapshot()["turns"],
        }


def run(
    experiment: Experiment,
    *,
    hourly_rate_usd: float = 30.0,
    participant_id: str = "anonymous",
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
    event_sink: Callable[[dict[str, Any]], None] | None = None,
    results_root: Path | None = None,
) -> int:
    prefix = experiment.env_prefix
    seed = int(os.environ.get(f"{prefix}_SEED", experiment.default_seed))
    port = int(os.environ.get(f"{prefix}_PORT", experiment.default_port))
    timeout_s = float(os.environ.get(f"{prefix}_PHASE_TIMEOUT_S", "1800"))
    run_id = (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        + experiment.run_suffix()
        + "-human"
    )
    results_dir = (results_root or experiment.directory / "results") / run_id
    results_dir.mkdir(parents=True, exist_ok=True)
    fixture = experiment.build_fixture(seed=seed, port=port).start()
    arm = HumanStandingArm(
        fixture=fixture,
        results_dir=results_dir,
        hourly_rate_usd=hourly_rate_usd,
        participant_id=participant_id,
        timeout_s=timeout_s,
        input_fn=input_fn,
        output=output,
        event_sink=event_sink,
    )
    utterance = experiment.utterance(fixture.base_url)
    phases: list[dict[str, Any]] = []
    results: dict[str, Any] = {
        "experiment": experiment.name,
        "variant": experiment.variant(),
        "system": "human",
        "participant_id": participant_id,
        "human_hourly_rate_usd": hourly_rate_usd,
        "run_id": run_id,
        "seed": seed,
        "n_fires": experiment.n_fires,
        "brief": direct_work_brief(utterance),
        "participant_update_after_failures": experiment.operator_fix_after_failures,
        "participant_update_message": direct_work_brief(
            experiment.operator_fix_message,
        ),
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
    participant_update_done = False
    updates_delivered = 0

    def surface_now() -> dict[str, Any] | None:
        return standing_surface(
            experiment.name,
            variant=experiment.variant(),
            updates=updates_delivered,
        )

    try:
        arm.start()
        results["setup"] = phase(
            "setup",
            lambda: arm.setup(utterance, surface=surface_now()),
        )
        results["profile_after_setup"] = arm.snapshot()
        for i in range(1, experiment.n_fires + 1):
            label = experiment.label(i)
            events = experiment.before_fire(fixture, i)
            for k, text in enumerate(experiment.operator_messages(i, fixture.base_url)):
                phase_name = f"message_{i}" if k == 0 else f"message_{i}_{k}"
                updates_delivered += 1
                out = phase(
                    phase_name,
                    lambda t=text, n=phase_name: arm.message(
                        t,
                        label=n,
                        surface=surface_now(),
                        request=human_update_request(experiment.name, t),
                    ),
                )
                results["messages"].append(
                    {
                        "before_fire": i,
                        "phase": phase_name,
                        "text": direct_work_brief(text),
                        **out,
                    },
                )
            threshold = experiment.operator_fix_after_failures
            if (
                threshold is not None
                and consecutive_noncorrect >= threshold
                and not participant_update_done
            ):
                out = phase(
                    "participant_update",
                    lambda: arm.message(
                        experiment.operator_fix_message,
                        label="participant_update",
                        surface=surface_now(),
                        request=PARTICIPANT_UPDATE_REQUEST,
                    ),
                )
                results["participant_update"] = {**out, "before_fire": i}
                participant_update_done = True
            ctx = experiment.prepare_fire(fixture)
            ctx["fire"] = i
            owner_before = len(fixture.state["owner"])
            fired = phase(label, lambda n=label: arm.fire(n, surface=surface_now()))
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
        results["participant_session"] = arm.session.participant_record()
        summary = finalize(
            results,
            phases=phases,
            results_dir=results_dir,
            experiment=experiment,
            arm="human",
        )
        fixture.stop()
        print(summary)
        print(f"[done] results in {results_dir}")
    return 0


def main(experiment: Experiment, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=f"human-{experiment.name}")
    parser.add_argument("--hourly-rate-usd", type=float, default=30.0)
    parser.add_argument("--participant-id", default="anonymous")
    args = parser.parse_args(argv)
    return run(
        experiment,
        hourly_rate_usd=args.hourly_rate_usd,
        participant_id=args.participant_id,
    )
