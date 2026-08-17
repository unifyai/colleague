"""One-automation slice of the policy_propagation unify arm.

A cheap validation gate for storage-prompt changes: boot the real pipeline
in a fresh context, run ONE automation's setup plus its first fire (whose
post-run review is the decision point under test), then print what landed
in the guidance and function stores — specifically whether the shared
policy was factored into a guidance entry linked to the stored function,
rather than living only inside the function body. Captures full LLM
requests to requests.jsonl for offline replay of the decision.

Usage (same environment contract as run_unify.sh):
    PP_SLICE=1 bash colleague/tracks/standing/policy_propagation/run_unify.sh  # not wired;
    run directly instead:
    .venv/bin/python -m colleague.tracks.standing.policy_propagation.slice_check
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from colleague.arms.unify_runtime import BenchmarkTaskExecutionDelegate
from colleague.tracks.standing.policy_propagation.unify import (
    _await_handle,
    _require_env,
)

EXPERIMENT_DIR = Path(__file__).resolve().parent


async def main() -> int:
    _require_env()

    from colleague.tracks.standing.policy_propagation.fixture import (
        DEFAULT_SEED,
        PolicyFixtureServer,
    )
    from colleague.tracks.standing.policy_propagation.protocol import (
        build_utterance,
        prepare_fire,
        release_round,
    )
    from colleague.tracks.standing.recurring_report.measure import LLMLedger

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + "-slice"
    results_dir = EXPERIMENT_DIR / "results" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    fixture = PolicyFixtureServer(seed=DEFAULT_SEED, port=0).start()
    print(f"[fixture] {fixture.base_url}")
    ledger = LLMLedger(capture_requests_path=results_dir / "requests.jsonl")

    import unify as unify_pkg
    import unisdk
    from unify.common.context_registry import ContextRegistry
    from unify.manager_registry import ManagerRegistry
    from unify.session_details import (
        UNASSIGNED_ASSISTANT_CONTEXT,
        UNASSIGNED_USER_CONTEXT,
    )

    ctx = (
        f"colleague/policy_propagation/{run_id}"
        f"/{UNASSIGNED_USER_CONTEXT}/{UNASSIGNED_ASSISTANT_CONTEXT}"
    )
    print(f"[boot] context={ctx}")
    unisdk.activate(os.environ.get("PP_PROJECT", "Benchmarks"))
    unisdk.create_context(ctx)
    unisdk.set_context(ctx, relative=False)
    ManagerRegistry.clear()
    ContextRegistry.clear()
    unify_pkg.init(project_name=os.environ.get("PP_PROJECT", "Benchmarks"))
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

    print("[setup] issuing triage utterance ...")
    with ledger.phase("setup"):
        handle = await actor.act(
            build_utterance("triage", fixture.base_url),
            persist=False,
        )
        status, text = await _await_handle(handle, 1800)
        await ledger.wait_quiescent(idle_seconds=150, timeout_seconds=1200)
    print(f"[setup] {status}: {text[:150]}")

    tasks = [
        t
        for t in scheduler._filter_tasks(filter=None, limit=50)
        if t.repeat is not None or t.trigger is not None
    ]
    if status != "completed" or len(tasks) != 1:
        print(f"[abort] expected one task, found {len(tasks)}")
        return 1
    task = tasks[0]

    release_round(fixture)
    cursor_before, released_now, batches_before = prepare_fire(fixture, "triage")
    delegate = BenchmarkTaskExecutionDelegate(actor)
    print("[fire] running first fire + review ...")
    with ledger.phase("fire_1"):
        token = current_task_execution_delegate.set(delegate)
        try:
            handle = await scheduler.execute(
                task_id=task.task_id,
                _activated_by=ActivatedBy.schedule,
            )
            status, text = await _await_handle(handle, 1800)
        finally:
            current_task_execution_delegate.reset(token)
    with ledger.phase("fire_1_review"):
        await ledger.wait_quiescent(idle_seconds=150, timeout_seconds=1200)
    print(f"[fire] {status}")

    # ── The verdict: what did the review persist? ──────────────────────────
    fm = ManagerRegistry.get_function_manager()
    gm = ManagerRegistry.get_guidance_manager()
    functions = fm.filter_functions(filter=None, limit=50) or []
    guidance = gm.filter(filter=None, limit=50) or []
    verdict = {
        "task_entrypoint": scheduler._filter_tasks(
            filter=f"task_id == {task.task_id}",
        )[0].entrypoint,
        "functions": [
            {"function_id": f.get("function_id"), "name": f.get("name")}
            for f in functions
            if isinstance(f, dict)
        ],
        "guidance": [
            {
                "guidance_id": (g.get("guidance_id") if isinstance(g, dict) else None),
                "title": (g.get("title") if isinstance(g, dict) else str(g)[:80]),
                "function_ids": (
                    g.get("function_ids") if isinstance(g, dict) else None
                ),
                "content_head": (
                    str(g.get("content"))[:300] if isinstance(g, dict) else None
                ),
            }
            for g in guidance
        ],
        "phases": [p.to_json() for p in ledger.summarize()],
    }
    (results_dir / "verdict.json").write_text(
        json.dumps(verdict, indent=2, default=str),
    )
    print(json.dumps(verdict, indent=2, default=str)[:3000])
    fixture.stop()
    print(f"[done] {results_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
