"""The unify arm of a fire-series experiment.

Standalone boot against staging Orchestra (``colleague.arms.unify_runtime``),
one utterance, then the experiment's fires through ``TaskScheduler.execute``
under the mirrored due-task delegate — exactly the production path. Between
fires the harness applies the experiment's world changes and delivers the
owner's messages as ordinary ``act`` requests. No operator ever fixes
anything for this arm; whatever the runtime's own verification and repair
do is the result.

Two things are read from the arm's own runtime rather than the fixture:

* a **native hold** — a run the runtime refused to deliver because a verdict
  it depended on failed or could not be settled. The owner-facing sentence
  the runtime produces is recorded as an owner message ``via="native"`` and
  scores as *held*, alongside anything the arm chose to POST to the
  fixture's owner channel;
* the **purpose split** of every LLM call (planning / verification /
  repair), which the ledger reads from unify's client tags.

Function snapshots before and after each fire are evidence for the record —
which stored functions a repair rewrote — never a score.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

from colleague.arms.unify_runtime import (
    BenchmarkTaskExecutionDelegate,
    await_handle,
    boot,
    function_snapshot,
    function_snapshots_by_name,
    require_env,
)
from colleague.tracks.standing.series.report import finalize
from colleague.tracks.standing.series.spec import (
    Experiment,
    OwnerMessage,
    messages_since,
)


def _env(prefix: str, key: str, default: Any) -> str:
    return os.environ.get(f"{prefix}_{key}", str(default))


async def run(experiment: Experiment) -> int:
    require_env()
    prefix = experiment.env_prefix
    seed = int(_env(prefix, "SEED", experiment.default_seed))
    port = int(_env(prefix, "PORT", experiment.default_port))
    phase_timeout_s = float(_env(prefix, "PHASE_TIMEOUT_S", 1800))
    quiesce_idle_s = float(_env(prefix, "QUIESCE_IDLE_S", 180))
    quiesce_timeout_s = float(_env(prefix, "QUIESCE_TIMEOUT_S", 1800))
    run_id = (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        + experiment.run_suffix()
        + "-unify"
    )
    results_dir = experiment.directory / "results" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    fixture = experiment.build_fixture(seed=seed, port=port).start()
    print(f"[fixture] {fixture.base_url} (seed={seed})")
    rt = boot(
        experiment=experiment.name,
        run_id=run_id,
        project_env=f"{prefix}_PROJECT",
    )
    ledger = rt.ledger

    from unify.common.llm_meter import handle_run_stats
    from unify.common.task_execution_context import current_task_execution_delegate
    from unify.task_scheduler.types.activated_by import ActivatedBy

    utterance = experiment.utterance(fixture.base_url)
    results: dict[str, Any] = {
        "experiment": experiment.name,
        "variant": experiment.variant(),
        "system": "unify",
        "run_id": run_id,
        "orchestra_url": rt.orchestra_url,
        "context": rt.context,
        "seed": seed,
        "n_fires": experiment.n_fires,
        "quiesce_idle_s": quiesce_idle_s,
        "utterance": utterance,
        **experiment.describe(),
        "messages": [],
        "fires": [],
    }

    def _finish() -> int:
        summary = finalize(
            results,
            phases=[p.to_json() for p in ledger.summarize()],
            results_dir=results_dir,
            experiment=experiment,
            arm="unify",
        )
        ledger.dump(results_dir / "ledger.jsonl")
        fixture.stop()
        print(f"\n{summary}")
        print(f"[done] results in {results_dir}")
        return 0

    async def _quiesce(label: str) -> None:
        if not await ledger.wait_quiescent(
            idle_seconds=quiesce_idle_s,
            timeout_seconds=quiesce_timeout_s,
        ):
            print(f"[{label}] warning: still active at quiesce timeout")

    print("[setup] issuing utterance ...")
    with ledger.phase("setup"):
        handle = await rt.actor.act(utterance, persist=False)
        setup_status, setup_text = await await_handle(handle, phase_timeout_s)
        await _quiesce("setup")
    print(f"[setup] {setup_status}: {setup_text[:200]}")
    results["setup"] = {"status": setup_status, "result": setup_text}

    tasks = [
        t
        for t in rt.scheduler._filter_tasks(filter=None, limit=100)
        if t.repeat is not None or t.trigger is not None
    ]
    if setup_status != "completed" or len(tasks) != 1:
        _finish()
        print(f"[abort] expected one recurring task, found {len(tasks)}")
        return 1
    task = tasks[0]
    print(f"[setup] task_id={task.task_id} entrypoint={task.entrypoint}")
    results["functions_after_setup"] = function_snapshots_by_name()

    delegate = BenchmarkTaskExecutionDelegate(rt.actor)
    for i in range(1, experiment.n_fires + 1):
        label = experiment.label(i)
        events = experiment.before_fire(fixture, i)
        for event in events:
            print(f"[{label}] world: {event}")

        for k, text in enumerate(experiment.operator_messages(i, fixture.base_url)):
            phase = f"message_{i}" if k == 0 else f"message_{i}_{k}"
            print(f"[{phase}] owner says: {text[:120]}")
            with ledger.phase(phase):
                msg_handle = await rt.actor.act(text, persist=False)
                msg_status, msg_text = await await_handle(msg_handle, phase_timeout_s)
                await _quiesce(phase)
            results["messages"].append(
                {
                    "before_fire": i,
                    "phase": phase,
                    "text": text,
                    "status": msg_status,
                    "result": msg_text[:1500],
                },
            )
            print(f"[{phase}] {msg_status}: {msg_text[:160]}")

        ctx = experiment.prepare_fire(fixture)
        ctx["fire"] = i
        owner_before = len(fixture.state["owner"])
        before = rt.scheduler._filter_tasks(filter=f"task_id == {task.task_id}")[0]
        functions_before = function_snapshots_by_name()
        print(
            f"[{label}] pending: {ctx.get('pending', ctx)} (entrypoint {before.entrypoint})",
        )

        native: list[OwnerMessage] = []
        held: dict[str, Any] | None = None
        run_stats: dict[str, Any] = {}
        with ledger.phase(label):
            token = current_task_execution_delegate.set(delegate)
            try:
                fire_status, fire_text = (
                    "error",
                    "execute() raised before returning a handle",
                )
                fire_handle = await rt.scheduler.execute(
                    task_id=task.task_id,
                    _activated_by=ActivatedBy.schedule,
                )
                fire_status, fire_text = await await_handle(
                    fire_handle,
                    phase_timeout_s,
                )
                outcome = getattr(fire_handle, "held_outcome", None)
                if outcome is not None:
                    held = {
                        "code": outcome.code,
                        "reason": outcome.reason,
                        "leaf": outcome.leaf_name,
                    }
                    native.append(OwnerMessage(text=fire_text, via="native"))
                run_stats = handle_run_stats(fire_handle)
            except Exception as exc:
                fire_text = f"{type(exc).__name__}: {exc}"
            finally:
                current_task_execution_delegate.reset(token)
        with ledger.phase(f"{label}_review"):
            await _quiesce(label)

        after = rt.scheduler._filter_tasks(filter=f"task_id == {task.task_id}")[0]
        functions_after = function_snapshots_by_name()
        changed = sorted(
            name
            for name, snap in functions_after.items()
            if (functions_before.get(name) or {}).get("implementation")
            != snap.get("implementation")
        )
        row = {
            "fire": i,
            "label": label,
            "events": events,
            "status": fire_status,
            "entrypoint_before": before.entrypoint,
            "entrypoint_after": after.entrypoint,
            **experiment.score_fire(
                fixture,
                ctx,
                messages=messages_since(fixture, owner_before) + native,
            ),
            "held_outcome": held,
            "verdicts": run_stats.get("verdicts"),
            "rewinds": run_stats.get("rewinds"),
            "functions_changed": changed,
            "result": fire_text[:1500],
        }
        results["fires"].append(row)
        print(
            f"[{label}] {fire_status}; outcome={row['outcome']} score={row['score']} "
            f"held={held is not None} changed={changed or '-'}",
        )

    final_task = rt.scheduler._filter_tasks(filter=f"task_id == {task.task_id}")[0]
    if final_task.entrypoint is not None:
        results["entrypoint_function_final"] = function_snapshot(final_task.entrypoint)
    results["functions_final"] = function_snapshots_by_name()
    return _finish()


def main(experiment: Experiment) -> int:
    return asyncio.run(run(experiment))
