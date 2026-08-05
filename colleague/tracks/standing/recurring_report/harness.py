"""Recurring weekly report benchmark: Unify-side driver.

Boots the Unify brain standalone against a hosted Orchestra (staging by
default), issues one natural-language automation request, then simulates N
weekly wakes of the resulting task by driving TaskScheduler.execute exactly
the way the ConversationManager's due-task path does. Every LLM call is
recorded per phase, and every delivered report is scored against the
fixture's independently computed ground truth.

The interesting outputs:
  - setup:   tokens/cost to go from utterance to a created recurring task
  - run_1:   description-driven execution + storage review (expensive)
  - run_2+:  expected to execute a stored FunctionManager entrypoint with
             zero LLM calls, IF the post-run review attached one
  - entrypoint_attached_after_run: when (and whether) the flip happened

Launch via run.sh, which prepares the environment before Python starts.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPERIMENT_DIR = Path(__file__).resolve().parent

STAGING_ORCHESTRA_HOST = "api.staging.internal.saas.unify.ai"

UTTERANCE_TEMPLATE = """\
Every Monday at 09:00, generate the weekly orders report and deliver it.

Data source: a local metrics API at {base_url}. \
GET {base_url}/orders?start=YYYY-MM-DD&end=YYYY-MM-DD returns a JSON list of \
orders, each with fields: order_id, date (YYYY-MM-DD), region, units (int), \
unit_price_cents (int).

The report covers the previous calendar week: Monday through Sunday \
inclusive, the last full week before the run date (UTC).

Compute exactly:
- total_units: sum of units over the report week
- total_revenue_cents: sum of units * unit_price_cents over the report week
- revenue_by_region_cents: object mapping each region to its revenue sum
- wow_revenue_change_pct: percent change of total_revenue_cents versus the \
week immediately before the report week, computed as \
round((current - previous) / previous * 100, 2)

Deliver by POSTing JSON to {base_url}/report with exactly these keys: \
week_start, week_end (YYYY-MM-DD strings), total_units, total_revenue_cents, \
revenue_by_region_cents, wow_revenue_change_pct.

Set up the recurring weekly task now, starting next Monday. Do not generate \
a report right now, and do not ask for confirmation.\
"""


def _require_env() -> None:
    """Fail fast when the launcher did not prepare the environment."""
    orchestra_url = os.environ.get("ORCHESTRA_URL", "")
    problems = []
    if not orchestra_url:
        problems.append("ORCHESTRA_URL is not set")
    if not os.environ.get("UNIFY_KEY"):
        problems.append("UNIFY_KEY is not set")
    if os.environ.get("UNILLM_CACHE", "").lower() != "false":
        problems.append(
            "UNILLM_CACHE must be 'false' (benchmark measures real inference)",
        )
    if os.environ.get("TEST", "").lower() != "true":
        problems.append(
            "TEST must be 'true' so unify.init binds to the benchmark context "
            "instead of a real assistant's context tree",
        )
    if os.environ.get("ASSISTANT_ID"):
        problems.append(
            "ASSISTANT_ID must be unset (benchmark must not touch a real assistant)",
        )
    if problems:
        raise SystemExit(
            "Environment not prepared (use run.sh):\n  - " + "\n  - ".join(problems),
        )
    if (
        STAGING_ORCHESTRA_HOST not in orchestra_url
        and os.environ.get("RWR_ALLOW_NON_STAGING") != "true"
    ):
        raise SystemExit(
            f"ORCHESTRA_URL={orchestra_url} is not staging. Set RWR_ALLOW_NON_STAGING=true to override.",
        )


class _BenchmarkTaskExecutionDelegate:
    """Route task runs through the benchmark's actor.

    Mirrors _ConversationTaskExecutionDelegate in
    unify/conversation_manager/domains/task_execution.py, which is how the
    production ConversationManager executes due tasks.
    """

    def __init__(self, actor: Any) -> None:
        self._actor = actor

    async def start_task_run(
        self,
        *,
        task_description: str,
        entrypoint: int | None,
        parent_chat_context: list[dict] | None,
        clarification_up_q: asyncio.Queue[str] | None,
        clarification_down_q: asyncio.Queue[str] | None,
        images: Any | None = None,
        **kwargs: Any,
    ) -> Any:
        _ = images
        return await self._actor.act(
            task_description,
            guidelines=kwargs.pop("guidelines", None),
            entrypoint=entrypoint,
            entrypoint_kwargs=kwargs.pop("entrypoint_kwargs", None),
            entrypoint_repair_attempts=int(
                kwargs.pop("entrypoint_repair_attempts", 0) or 0,
            ),
            entrypoint_repair_context=kwargs.pop("entrypoint_repair_context", None),
            destination=kwargs.pop("destination", None),
            _parent_chat_context=parent_chat_context,
            _clarification_up_q=clarification_up_q,
            _clarification_down_q=clarification_down_q,
            persist=False,
            _reuse_actor_slot=entrypoint is not None,
        )


async def _await_handle(handle: Any, timeout_s: float) -> tuple[str, str]:
    """Await a steerable handle's result; returns (status, text)."""
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


def _task_snapshot(task: Any) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "name": task.name,
        "description": task.description,
        "enabled": task.enabled,
        "entrypoint": task.entrypoint,
        "repeat": (
            [p.model_dump(mode="json") for p in task.repeat] if task.repeat else None
        ),
        "schedule": task.schedule.model_dump(mode="json") if task.schedule else None,
        "offline": task.offline,
    }


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

    from colleague.tracks.standing.recurring_report.fixture import (
        DEFAULT_PORT,
        DEFAULT_SEED,
        FixtureServer,
        expected_report,
        score_report,
    )
    from colleague.tracks.standing.recurring_report.measure import LLMLedger

    seed = int(os.environ.get("RWR_SEED", DEFAULT_SEED))
    port = int(os.environ.get("RWR_PORT", DEFAULT_PORT))
    n_runs = int(os.environ.get("RWR_RUNS", "4"))
    phase_timeout_s = float(os.environ.get("RWR_PHASE_TIMEOUT_S", "1800"))
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

    results_dir = EXPERIMENT_DIR / "results" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    quiesce_idle_s = float(os.environ.get("RWR_QUIESCE_IDLE_S", "180"))
    quiesce_timeout_s = float(os.environ.get("RWR_QUIESCE_TIMEOUT_S", "1800"))

    fixture = FixtureServer(seed=seed, port=port).start()
    print(f"[fixture] serving on {fixture.base_url} (seed={seed})")

    ledger = LLMLedger()

    # ── Boot the brain standalone (mirrors sandboxes/conversation_manager) ──
    import unify as unify_pkg
    import unisdk
    from unify.common.context_registry import ContextRegistry
    from unify.manager_registry import ManagerRegistry
    from unify.session_details import (
        UNASSIGNED_ASSISTANT_CONTEXT,
        UNASSIGNED_USER_CONTEXT,
    )

    ctx = (
        f"colleague/recurring_report/{run_id}"
        f"/{UNASSIGNED_USER_CONTEXT}/{UNASSIGNED_ASSISTANT_CONTEXT}"
    )
    print(f"[boot] orchestra={os.environ['ORCHESTRA_URL']}")
    print(f"[boot] context={ctx}")
    unisdk.activate(os.environ.get("RWR_PROJECT", "Benchmarks"))
    unisdk.create_context(ctx)
    unisdk.set_context(ctx, relative=False)
    ManagerRegistry.clear()
    ContextRegistry.clear()
    unify_pkg.init(project_name=os.environ.get("RWR_PROJECT", "Benchmarks"))
    # After init: unify installed its global LLM hook; chain ours on top.
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

    results: dict[str, Any] = {
        "experiment": "recurring_weekly_report",
        "run_id": run_id,
        "orchestra_url": os.environ["ORCHESTRA_URL"],
        "context": ctx,
        "seed": seed,
        "n_runs": n_runs,
        "quiesce_idle_s": quiesce_idle_s,
        "unillm_cache": os.environ.get("UNILLM_CACHE"),
        "unify_model_env": os.environ.get("UNIFY_MODEL"),
        "utterance": UTTERANCE_TEMPLATE.format(base_url=fixture.base_url),
        "runs": [],
    }

    # ── Phase: setup (NL utterance → recurring task definition) ────────────
    print("[setup] issuing utterance ...")
    with ledger.phase("setup"):
        handle = await actor.act(
            UTTERANCE_TEMPLATE.format(base_url=fixture.base_url),
            persist=False,
        )
        setup_status, setup_text = await _await_handle(handle, phase_timeout_s)
        # Detached post-act work (storage review) belongs to setup: wait for it.
        settled = await ledger.wait_quiescent(
            idle_seconds=quiesce_idle_s,
            timeout_seconds=quiesce_timeout_s,
        )
        if not settled:
            print("[setup] warning: LLM activity still ongoing at quiesce timeout")
    print(f"[setup] {setup_status}: {setup_text[:300]}")
    results["setup"] = {"status": setup_status, "result": setup_text}

    tasks = [
        t
        for t in scheduler._filter_tasks(filter=None, limit=100)
        if t.repeat is not None or t.trigger is not None
    ]
    if setup_status != "completed" or len(tasks) != 1:
        results["setup"]["recurring_tasks_found"] = [_task_snapshot(t) for t in tasks]
        _finalize(results, ledger, results_dir, fixture)
        print(
            f"[abort] setup did not yield exactly one recurring task "
            f"(status={setup_status}, found={len(tasks)})",
        )
        return 1
    task = tasks[0]
    results["task_after_setup"] = _task_snapshot(task)
    print(
        f"[setup] task_id={task.task_id} entrypoint={task.entrypoint} "
        f"repeat={'yes' if task.repeat else 'no'}",
    )

    # ── Phases: simulated weekly wakes ──────────────────────────────────────
    delegate = _BenchmarkTaskExecutionDelegate(actor)
    reports_seen = 0
    for i in range(1, n_runs + 1):
        run_date = datetime.now(timezone.utc).date()
        before = scheduler._filter_tasks(filter=f"task_id == {task.task_id}")[0]
        print(f"[run_{i}] executing (entrypoint before: {before.entrypoint}) ...")
        with ledger.phase(f"run_{i}"):
            token = current_task_execution_delegate.set(delegate)
            try:
                run_status, run_text = (
                    "error",
                    "execute() raised before returning a handle",
                )
                run_handle = await scheduler.execute(
                    task_id=task.task_id,
                    _activated_by=ActivatedBy.schedule,
                )
                run_status, run_text = await _await_handle(run_handle, phase_timeout_s)
            except Exception as exc:
                run_text = f"{type(exc).__name__}: {exc}"
            finally:
                current_task_execution_delegate.reset(token)

        # Post-run reviews detach from the handle; in production the next wake
        # is a week away, so reviews always finish in between. Restore that
        # invariant and attribute the review tail to its own phase.
        with ledger.phase(f"run_{i}_review"):
            settled = await ledger.wait_quiescent(
                idle_seconds=quiesce_idle_s,
                timeout_seconds=quiesce_timeout_s,
            )
            if not settled:
                print(
                    f"[run_{i}] warning: LLM activity still ongoing at quiesce timeout",
                )

        after = scheduler._filter_tasks(filter=f"task_id == {task.task_id}")[0]
        delivered = fixture.sink.snapshot()[reports_seen:]
        reports_seen += len(delivered)
        expected = expected_report(seed, run_date)
        scores = [score_report(r["body"], expected) for r in delivered]
        run_row = {
            "run": i,
            "run_date": run_date.isoformat(),
            "status": run_status,
            "entrypoint_before": before.entrypoint,
            "entrypoint_after": after.entrypoint,
            "reports_delivered": len(delivered),
            "reports": [r["body"] for r in delivered],
            "expected_report": expected,
            "scores": scores,
            "correct": (
                len(delivered) == 1 and scores[0]["correct"] if scores else False
            ),
            "result": run_text[:2000],
        }
        results["runs"].append(run_row)
        print(
            f"[run_{i}] {run_status}; reports={len(delivered)} "
            f"correct={run_row['correct']} entrypoint_after={after.entrypoint}",
        )

    final_task = scheduler._filter_tasks(filter=f"task_id == {task.task_id}")[0]
    results["task_final"] = _task_snapshot(final_task)
    if final_task.entrypoint is not None:
        results["entrypoint_function"] = _function_snapshot(final_task.entrypoint)

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
        f"# recurring_weekly_report — {results['run_id']}",
        "",
        f"- orchestra: `{results['orchestra_url']}`",
        f"- context: `{results['context']}`",
        f"- UNILLM_CACHE: `{results.get('unillm_cache')}`",
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
        "| run | status | entrypoint before → after | reports | correct |",
        "|---|---|---|---|---|",
    ]
    for r in results.get("runs", []):
        lines.append(
            f"| {r['run']} | {r['status']} | {r['entrypoint_before']} → "
            f"{r['entrypoint_after']} | {r['reports_delivered']} | {r['correct']} |",
        )
    summary = "\n".join(lines) + "\n"
    with open(results_dir / "summary.md", "w", encoding="utf-8") as f:
        f.write(summary)

    fixture.stop()
    print(f"\n{summary}")
    print(f"[done] results in {results_dir}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
