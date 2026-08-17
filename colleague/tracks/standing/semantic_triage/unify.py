"""Semantic triage benchmark: Unify arm.

Same standalone boot and metering as drift_recovery's unify driver. The
question this experiment answers is what the steady state looks like when
the recurring work contains a genuine judgment substep: the expected
convergence is a stored entrypoint whose control flow is frozen and whose
classification happens through focused ``query_llm`` calls — so each fire
costs a handful of small, narrow-prompt calls rather than a full CodeAct
loop. Per-fire tokens and per-item accuracy are the measurements.

Launch via run_unify.sh.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from colleague.arms.unify_runtime import BenchmarkTaskExecutionDelegate

EXPERIMENT_DIR = Path(__file__).resolve().parent

STAGING_ORCHESTRA_HOST = "api.staging.internal.saas.unify.ai"


def _require_env() -> None:
    orchestra_url = os.environ.get("ORCHESTRA_URL", "")
    problems = []
    if not orchestra_url:
        problems.append("ORCHESTRA_URL is not set")
    if not os.environ.get("UNIFY_KEY"):
        problems.append("UNIFY_KEY is not set")
    if os.environ.get("UNILLM_CACHE", "").lower() != "false":
        problems.append("UNILLM_CACHE must be 'false'")
    if os.environ.get("TEST", "").lower() != "true":
        problems.append("TEST must be 'true' (benchmark context binding)")
    if os.environ.get("ASSISTANT_ID"):
        problems.append("ASSISTANT_ID must be unset")
    if problems:
        raise SystemExit(
            "Environment not prepared (use run_unify.sh):\n  - "
            + "\n  - ".join(problems),
        )
    if (
        STAGING_ORCHESTRA_HOST not in orchestra_url
        and os.environ.get("RWR_ALLOW_NON_STAGING") != "true"
    ):
        raise SystemExit(f"ORCHESTRA_URL={orchestra_url} is not staging.")


async def _await_handle(handle: Any, timeout_s: float) -> tuple[str, str]:
    try:
        text = await asyncio.wait_for(handle.result(), timeout=timeout_s)
        return "completed", str(text)
    except asyncio.TimeoutError:
        try:
            await handle.stop(reason="benchmark phase timeout")
        except Exception as exc:
            return "timeout", f"timed out after {timeout_s}s; stop failed: {exc}"
        return "timeout", f"timed out after {timeout_s}s"
    except Exception as exc:
        return "error", f"{type(exc).__name__}: {exc}"


def _function_snapshot(function_id: int) -> dict[str, Any]:
    from unify.manager_registry import ManagerRegistry

    fm = ManagerRegistry.get_function_manager()
    try:
        log = fm._get_log_by_function_id(function_id=function_id, raise_if_missing=True)
        entries = dict(log.entries)
        return {
            "function_id": function_id,
            "name": entries.get("name"),
            "docstring": entries.get("docstring"),
            "implementation": entries.get("implementation"),
        }
    except Exception as exc:
        return {"function_id": function_id, "error": f"{type(exc).__name__}: {exc}"}


async def main() -> int:
    _require_env()

    from colleague.tracks.standing.recurring_report.measure import LLMLedger
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

    seed = int(os.environ.get("ST_SEED", DEFAULT_SEED))
    port = int(os.environ.get("ST_PORT", DEFAULT_PORT))
    phase_timeout_s = float(os.environ.get("ST_PHASE_TIMEOUT_S", "1800"))
    quiesce_idle_s = float(os.environ.get("ST_QUIESCE_IDLE_S", "180"))
    quiesce_timeout_s = float(os.environ.get("ST_QUIESCE_TIMEOUT_S", "1800"))
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + "-unify"

    results_dir = EXPERIMENT_DIR / "results" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    fixture = TriageFixtureServer(seed=seed, port=port).start()
    print(f"[fixture] {fixture.base_url} (seed={seed})")

    ledger = LLMLedger()

    import unify as unify_pkg
    import unisdk
    from unify.common.context_registry import ContextRegistry
    from unify.manager_registry import ManagerRegistry
    from unify.session_details import (
        UNASSIGNED_ASSISTANT_CONTEXT,
        UNASSIGNED_USER_CONTEXT,
    )

    ctx = (
        f"colleague/semantic_triage/{run_id}"
        f"/{UNASSIGNED_USER_CONTEXT}/{UNASSIGNED_ASSISTANT_CONTEXT}"
    )
    print(f"[boot] orchestra={os.environ['ORCHESTRA_URL']}")
    print(f"[boot] context={ctx}")
    unisdk.activate(os.environ.get("ST_PROJECT", "Benchmarks"))
    unisdk.create_context(ctx)
    unisdk.set_context(ctx, relative=False)
    ManagerRegistry.clear()
    ContextRegistry.clear()
    unify_pkg.init(project_name=os.environ.get("ST_PROJECT", "Benchmarks"))
    ledger.install()

    from unify.actor.code_act_actor import CodeActActor
    from unify.actor.environments import StateManagerEnvironment
    from unify.common.task_execution_context import current_task_execution_delegate
    from unify.function_manager.primitives import Primitives
    from unify.task_scheduler.types.activated_by import ActivatedBy

    primitives = Primitives()
    actor = CodeActActor(
        environments=[StateManagerEnvironment(primitives)],
        function_manager=ManagerRegistry.get_function_manager(),
        guidance_manager=ManagerRegistry.get_guidance_manager(),
        knowledge_manager=ManagerRegistry.get_knowledge_manager(),
    )
    scheduler = ManagerRegistry.get_task_scheduler()
    print("[boot] actor + managers ready")

    utterance = UTTERANCE_TEMPLATE.format(base_url=fixture.base_url)
    results: dict[str, Any] = {
        "experiment": "semantic_triage",
        "system": "unify",
        "run_id": run_id,
        "orchestra_url": os.environ["ORCHESTRA_URL"],
        "context": ctx,
        "seed": seed,
        "n_fires": N_FIRES,
        "quiesce_idle_s": quiesce_idle_s,
        "utterance": utterance,
        "fires": [],
    }

    print("[setup] issuing utterance ...")
    with ledger.phase("setup"):
        handle = await actor.act(utterance, persist=False)
        setup_status, setup_text = await _await_handle(handle, phase_timeout_s)
        if not await ledger.wait_quiescent(
            idle_seconds=quiesce_idle_s,
            timeout_seconds=quiesce_timeout_s,
        ):
            print("[setup] warning: still active at quiesce timeout")
    print(f"[setup] {setup_status}: {setup_text[:200]}")
    results["setup"] = {"status": setup_status, "result": setup_text}

    tasks = [
        t
        for t in scheduler._filter_tasks(filter=None, limit=100)
        if t.repeat is not None or t.trigger is not None
    ]
    if setup_status != "completed" or len(tasks) != 1:
        _finalize(results, ledger, results_dir, fixture)
        print(f"[abort] expected one recurring task, found {len(tasks)}")
        return 1
    task = tasks[0]
    print(f"[setup] task_id={task.task_id} entrypoint={task.entrypoint}")

    delegate = BenchmarkTaskExecutionDelegate(actor)
    for i in range(1, N_FIRES + 1):
        cursor_before, released_now, batches_before = prepare_fire(fixture)
        before = scheduler._filter_tasks(filter=f"task_id == {task.task_id}")[0]
        print(
            f"[fire_{i}] pending seqs {cursor_before + 1}..{released_now} "
            f"(entrypoint: {before.entrypoint})",
        )
        with ledger.phase(f"fire_{i}"):
            token = current_task_execution_delegate.set(delegate)
            try:
                fire_status, fire_text = (
                    "error",
                    "execute() raised before returning a handle",
                )
                fire_handle = await scheduler.execute(
                    task_id=task.task_id,
                    _activated_by=ActivatedBy.schedule,
                )
                fire_status, fire_text = await _await_handle(
                    fire_handle,
                    phase_timeout_s,
                )
            except Exception as exc:
                fire_text = f"{type(exc).__name__}: {exc}"
            finally:
                current_task_execution_delegate.reset(token)
        with ledger.phase(f"fire_{i}_review"):
            if not await ledger.wait_quiescent(
                idle_seconds=quiesce_idle_s,
                timeout_seconds=quiesce_timeout_s,
            ):
                print(f"[fire_{i}] warning: still active at quiesce timeout")

        after = scheduler._filter_tasks(filter=f"task_id == {task.task_id}")[0]
        row = {
            "fire": i,
            "status": fire_status,
            "entrypoint_before": before.entrypoint,
            "entrypoint_after": after.entrypoint,
            **score_fire(
                fixture,
                cursor_before=cursor_before,
                released_now=released_now,
                batches_before=batches_before,
            ),
            "result": fire_text[:1500],
        }
        results["fires"].append(row)
        print(
            f"[fire_{i}] {fire_status}; delivered={row['batches_delivered']} "
            f"correct={row['correct']} accuracy={row['accuracy']} "
            f"entrypoint_after={after.entrypoint}",
        )

    final_task = scheduler._filter_tasks(filter=f"task_id == {task.task_id}")[0]
    if final_task.entrypoint is not None:
        results["entrypoint_function_final"] = _function_snapshot(final_task.entrypoint)

    _finalize(results, ledger, results_dir, fixture)
    return 0


def _finalize(
    results: dict[str, Any],
    ledger: Any,
    results_dir: Path,
    fixture: Any,
) -> None:
    phases = ledger.summarize()
    results["phases"] = [p.to_json() for p in phases]
    results["finished_at"] = datetime.now(timezone.utc).isoformat()
    ledger.dump(results_dir / "ledger.jsonl")
    with open(results_dir / "results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    lines = [
        f"# semantic_triage (unify arm) — {results['run_id']}",
        "",
        f"- orchestra: `{results['orchestra_url']}`",
        "",
        "| phase | LLM calls | prompt tok | completion tok | cost (USD) | wall (s) |",
        "|---|---|---|---|---|---|",
    ]
    for p in phases:
        j = p.to_json()
        lines.append(
            f"| {j['name']} | {j['llm_calls']} | {j['prompt_tokens']} | "
            f"{j['completion_tokens']} | {j['provider_cost_usd']} | {j['wall_seconds']} |",
        )
    lines += [
        "",
        "| fire | status | delivered | contract | accuracy |",
        "|---|---|---|---|---|",
    ]
    for r in results.get("fires", []):
        lines.append(
            f"| {r['fire']} | {r['status']} | {r['batches_delivered']} | "
            f"{r['correct']} | {r['accuracy']} |",
        )
    summary = "\n".join(lines) + "\n"
    (results_dir / "summary.md").write_text(summary, encoding="utf-8")
    fixture.stop()
    print(f"\n{summary}")
    print(f"[done] results in {results_dir}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
