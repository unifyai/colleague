"""Drift-recovery benchmark: Unify arm.

Same standalone boot as the recurring_weekly_report harness (staging
Orchestra, isolated context, chained LLM ledger, quiescence barriers), with
the drift-recovery fire protocol: 10 fires, ORDERS_PER_FIRE released before
each, and the orders API renaming ``unit_price_cents`` to
``unit_price_minor`` after fire 4. The interesting measurement is fire 5:
the stored symbolic entrypoint fails on the renamed field, the bounded
repair loop (entrypoint_repair_attempts=1) rewrites and persists the
function, and the retry inside the same run should still deliver — after
which fires 6-10 are expected back at zero LLM calls.

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


class _BenchmarkTaskExecutionDelegate:
    """Mirror of the ConversationManager due-task delegate (see exp 1)."""

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

    from colleague.tracks.standing.drift_recovery.fixture import (
        DEFAULT_PORT,
        DEFAULT_SEED,
        DriftFixtureServer,
    )
    from colleague.tracks.standing.drift_recovery.protocol import (
        DRIFT_AFTER_FIRE,
        N_FIRES,
        UTTERANCE_TEMPLATE,
        prepare_fire,
        score_fire,
    )
    from colleague.tracks.standing.recurring_report.measure import LLMLedger

    seed = int(os.environ.get("DR_SEED", DEFAULT_SEED))
    port = int(os.environ.get("DR_PORT", DEFAULT_PORT))
    phase_timeout_s = float(os.environ.get("DR_PHASE_TIMEOUT_S", "1800"))
    quiesce_idle_s = float(os.environ.get("DR_QUIESCE_IDLE_S", "180"))
    quiesce_timeout_s = float(os.environ.get("DR_QUIESCE_TIMEOUT_S", "1800"))
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + "-unify"

    results_dir = EXPERIMENT_DIR / "results" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    fixture = DriftFixtureServer(seed=seed, port=port).start()
    print(f"[fixture] {fixture.base_url} (seed={seed})")

    ledger = LLMLedger()

    import unisdk
    import unify as unify_pkg
    from unify.common.context_registry import ContextRegistry
    from unify.manager_registry import ManagerRegistry
    from unify.session_details import (
        UNASSIGNED_ASSISTANT_CONTEXT,
        UNASSIGNED_USER_CONTEXT,
    )

    ctx = (
        f"colleague/drift_recovery/{run_id}"
        f"/{UNASSIGNED_USER_CONTEXT}/{UNASSIGNED_ASSISTANT_CONTEXT}"
    )
    print(f"[boot] orchestra={os.environ['ORCHESTRA_URL']}")
    print(f"[boot] context={ctx}")
    unisdk.activate(os.environ.get("DR_PROJECT", "Benchmarks"))
    unisdk.create_context(ctx)
    unisdk.set_context(ctx, relative=False)
    ManagerRegistry.clear()
    ContextRegistry.clear()
    unify_pkg.init(project_name=os.environ.get("DR_PROJECT", "Benchmarks"))
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
        "experiment": "drift_recovery",
        "system": "unify",
        "run_id": run_id,
        "orchestra_url": os.environ["ORCHESTRA_URL"],
        "context": ctx,
        "seed": seed,
        "n_fires": N_FIRES,
        "drift_after_fire": DRIFT_AFTER_FIRE,
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

    delegate = _BenchmarkTaskExecutionDelegate(actor)
    for i in range(1, N_FIRES + 1):
        if i == DRIFT_AFTER_FIRE + 1:
            fixture.stream.set_drift(True)
            print(
                f"[drift] applied before fire {i}: unit_price_cents -> unit_price_minor",
            )
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
            "drifted": i > DRIFT_AFTER_FIRE,
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
            f"correct={row['correct']} entrypoint_after={after.entrypoint}",
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
        f"# drift_recovery (unify arm) — {results['run_id']}",
        "",
        f"- orchestra: `{results['orchestra_url']}`",
        f"- drift after fire {results['drift_after_fire']}: `unit_price_cents -> unit_price_minor`",
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
        "| fire | drifted | status | delivered | correct |",
        "|---|---|---|---|---|",
    ]
    for r in results.get("fires", []):
        lines.append(
            f"| {r['fire']} | {r['drifted']} | {r['status']} | "
            f"{r['batches_delivered']} | {r['correct']} |",
        )
    summary = "\n".join(lines) + "\n"
    (results_dir / "summary.md").write_text(summary, encoding="utf-8")
    fixture.stop()
    print(f"\n{summary}")
    print(f"[done] results in {results_dir}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
