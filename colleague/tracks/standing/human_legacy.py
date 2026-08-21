"""Direct human protocols for the three standing experiments predating ``series``.

These use the experiments' existing fixtures and exact scorers. The participant
performs every occurrence directly; this module is compatibility glue, not a
second scoring implementation.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO

from colleague.arms.sessions.human_session import HumanSession
from colleague.harness.cost import delta as cost_delta
from colleague.harness.cost import total as total_cost
from colleague.tracks.standing.human_brief import (
    REQUEST_SETUP,
    direct_work_brief,
    policy_surfaces,
    standing_surface,
)


class Protocol:
    def __init__(
        self,
        *,
        name: str,
        directory: Path,
        fixture: Any,
        participant_id: str,
        hourly_rate_usd: float,
        timeout_s: float,
        input_fn: Callable[[str], str] = input,
        output: TextIO | None = None,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
        results_root: Path | None = None,
    ) -> None:
        self.name = name
        self.fixture = fixture
        self.timeout_s = timeout_s
        self.run_id = (
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + "-human"
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
        self.phases: list[dict[str, Any]] = []
        self.results: dict[str, Any] = {
            "experiment": name,
            "system": "human",
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

    def _present(self, surface: dict[str, Any] | None, request: str) -> None:
        self.session.surface = {**surface, "request": request} if surface else None

    def setup_one(
        self,
        key: str,
        utterance: str,
        *,
        surface: dict[str, Any] | None = None,
    ) -> None:
        self.session.bind_fixture(self.fixture, f"setup_{key}")
        context = (
            "Read this recurring-work brief. Each time the work becomes due, "
            "you will complete it yourself. You may retain notes and use what "
            "you learn from earlier occurrences."
        )
        self._present(surface, REQUEST_SETUP)
        self.phase(
            f"setup_{key}",
            lambda: self.session.send(
                direct_work_brief(utterance),
                context=context,
                persist=True,
            ),
        )

    def owner_message(
        self,
        text: str,
        *,
        surface: dict[str, Any] | None = None,
    ) -> None:
        self.session.bind_fixture(self.fixture, "policy_change")
        self._present(surface, direct_work_brief(text))
        self.phase(
            "policy_change",
            lambda: self.session.send(
                direct_work_brief(text),
                context="Apply this update to all later occurrences of the work.",
                persist=True,
            ),
        )

    def fire(
        self,
        key: str,
        label: str,
        *,
        surface: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.session.bind_fixture(self.fixture, label)
        request = (
            f"The {key.replace('_', ' ')} work is due. Complete one occurrence now."
        )
        self._present(surface, request)
        reply = self.phase(
            label,
            lambda: self.session.send(
                request,
                context="WORK DUE",
                persist=True,
                timeout=self.timeout_s,
            ),
        )
        return {
            "label": label,
            "ok": reply.ok,
            "cost": self.latest_cost(),
        }

    def finish(self) -> None:
        self.results["participant_session"] = self.session.participant_record()
        self.results["cost"] = total_cost([p["cost"] for p in self.phases])
        self.results["finished_at"] = datetime.now(timezone.utc).isoformat()
        (self.results_dir / "results.json").write_text(
            json.dumps(self.results, indent=2, default=str),
            encoding="utf-8",
        )
        lines = [
            f"# {self.name} (human) — {self.run_id}",
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
    from colleague.tracks.standing.recurring_report.protocol import (
        UTTERANCE_TEMPLATE,
        RecurringReport,
    )

    EXPERIMENT_DIR = RecurringReport.directory

    seed = int(os.environ.get("RWR_SEED", DEFAULT_SEED))
    port = int(os.environ.get("RWR_PORT", DEFAULT_PORT))
    runs = int(os.environ.get("RWR_RUNS", "4"))
    timeout = float(os.environ.get("RWR_PHASE_TIMEOUT_S", "1800"))
    fixture = FixtureServer(seed=seed, port=port).start()
    p = Protocol(
        name="recurring_report",
        directory=EXPERIMENT_DIR,
        fixture=fixture,
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
        p.results.update(
            {"seed": seed, "n_runs": runs, "brief": direct_work_brief(utterance)},
        )
        surface = standing_surface("recurring_report")
        p.session.setup()
        p.setup_one("report", utterance, surface=surface)
        seen = 0
        for i in range(1, runs + 1):
            run_date = datetime.now(timezone.utc).date()
            fired = p.fire("report", f"run_{i}", surface=surface)
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
        p.results.update(
            {
                "seed": seed,
                "n_fires": N_FIRES,
                "brief": direct_work_brief(utterance),
            },
        )
        surface = standing_surface("semantic_triage")
        p.session.setup()
        p.setup_one("triage", utterance, surface=surface)
        for i in range(1, N_FIRES + 1):
            cursor, released, before = prepare_fire(fixture)
            fired = p.fire("triage", f"fire_{i}", surface=surface)
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
        p.results.update(
            {
                "seed": seed,
                "briefs": {
                    key: direct_work_brief(value) for key, value in utterances.items()
                },
            },
        )
        surfaces = policy_surfaces()
        p.session.setup()
        for automation in AUTOMATIONS:
            p.setup_one(
                automation, utterances[automation], surface=surfaces[automation]
            )

        round_no = 0

        def run_round(threshold: int) -> None:
            nonlocal round_no
            round_no += 1
            release_round(fixture)
            for automation in AUTOMATIONS:
                cursor, released, before = prepare_fire(fixture, automation)
                fired = p.fire(
                    automation,
                    f"round{round_no}_{automation}",
                    surface=surfaces[automation],
                )
                p.results["fires"].append(
                    {
                        "round": round_no,
                        "task": automation,
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
