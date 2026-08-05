"""ecommerce-trading-review: the unify arm.

Boots the Unify brain standalone against a hosted Orchestra (staging by
default), hands it the landing page's `brief` verbatim, then drives the Monday
wake through `TaskScheduler.execute` with the same delegate mechanics the
production ConversationManager uses for due tasks. Every LLM call is metered
per phase; the posted review is scored against ground truth recomputed from
the served weekly series.

One review per run rather than one per client, so the page-eligible cost is
per run. `summary.md` ends with a transcription block naming the figures
eligible to appear on the page.

Launch via run_unify.sh, which prepares the environment before Python starts.
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
    """Fail fast when the launcher did not prepare the environment."""
    orchestra_url = os.environ.get("ORCHESTRA_URL", "")
    problems = []
    if not orchestra_url:
        problems.append("ORCHESTRA_URL is not set")
    if not os.environ.get("UNIFY_KEY"):
        problems.append("UNIFY_KEY is not set")
    if os.environ.get("UNILLM_CACHE", "").lower() != "false":
        problems.append("UNILLM_CACHE must be 'false' (this measures real inference)")
    if os.environ.get("TEST", "").lower() != "true":
        problems.append(
            "TEST must be 'true' so unify.init binds to the measurement context "
            "instead of a real assistant's context tree",
        )
    if os.environ.get("ASSISTANT_ID"):
        problems.append("ASSISTANT_ID must be unset (never touch a real assistant)")
    if problems:
        raise SystemExit(
            "Environment not prepared (use run_unify.sh):\n  - " + "\n  - ".join(problems),
        )
    if (
        STAGING_ORCHESTRA_HOST not in orchestra_url
        and os.environ.get("ETR_ALLOW_NON_STAGING") != "true"
    ):
        raise SystemExit(
            f"ORCHESTRA_URL={orchestra_url} is not staging. "
            f"Set ETR_ALLOW_NON_STAGING=true to override.",
        )


class _MeasuredTaskExecutionDelegate:
    """Route task runs through this run's actor.

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
            await handle.stop(reason="measurement phase timeout")
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

    from colleague.tracks.standing.recurring_report.measure import LLMLedger
    from colleague.tracks.usecases.ecommerce_trading_review.fixture import (
        DEFAULT_PORT,
        DEFAULT_SEED,
        FixtureServer,
        selftest as fixture_selftest,
    )
    from colleague.tracks.usecases.ecommerce_trading_review.protocol import (
        DEFAULT_USECASES_TSX,
        brief_digest,
        extract_brief,
        score_run,
        selftest as scorer_selftest,
        utterance as build_utterance,
    )

    seed = int(os.environ.get("ETR_SEED", DEFAULT_SEED))
    port = int(os.environ.get("ETR_PORT", DEFAULT_PORT))
    n_runs = int(os.environ.get("ETR_RUNS", "2"))
    phase_timeout_s = float(os.environ.get("ETR_PHASE_TIMEOUT_S", "3600"))
    quiesce_idle_s = float(os.environ.get("ETR_QUIESCE_IDLE_S", "180"))
    quiesce_timeout_s = float(os.environ.get("ETR_QUIESCE_TIMEOUT_S", "1800"))
    check_only = os.environ.get("ETR_CHECK", "").lower() == "true"
    tsx_path = Path(os.environ.get("ETR_USECASES_TSX") or DEFAULT_USECASES_TSX)
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + "-unify"

    results_dir = EXPERIMENT_DIR / "results" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    # Ground truth and the scoring path are proved before anything is spent.
    ground_truth = fixture_selftest(seed)
    anchor = ground_truth["anchor_week"]
    scorer_selftest(seed, anchor)
    print(
        f"[fixture] selftest ok — week={anchor} planted={ground_truth['planted']} "
        f"clean_history={ground_truth['history_weeks_clean']}w "
        f"slide_starts={ground_truth['slide_starts']}",
    )

    brief = extract_brief(tsx_path)
    fixture = FixtureServer(seed=seed, port=port, anchor=anchor).start()
    utterance = build_utterance(brief, fixture.base_url)
    print(f"[fixture] serving on {fixture.base_url} (seed={seed})")
    print(f"[brief] {tsx_path} sha256={brief_digest(brief)[:16]} chars={len(brief)}")

    ledger = LLMLedger()

    # ── Boot the brain standalone (mirrors sandboxes/conversation_manager) ──
    import unisdk
    import unify as unify_pkg
    from unify.common.context_registry import ContextRegistry
    from unify.manager_registry import ManagerRegistry
    from unify.session_details import (
        UNASSIGNED_ASSISTANT_CONTEXT,
        UNASSIGNED_USER_CONTEXT,
    )

    project = os.environ.get("ETR_PROJECT", "Benchmarks")
    ctx = (
        f"colleague/usecases/ecommerce_trading_review/{run_id}"
        f"/{UNASSIGNED_USER_CONTEXT}/{UNASSIGNED_ASSISTANT_CONTEXT}"
    )
    print(f"[boot] orchestra={os.environ['ORCHESTRA_URL']}")
    print(f"[boot] context={ctx}")
    unisdk.activate(project)
    unisdk.create_context(ctx)
    unisdk.set_context(ctx, relative=False)
    ManagerRegistry.clear()
    ContextRegistry.clear()
    unify_pkg.init(project_name=project)
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
        "experiment": "usecases/ecommerce_trading_review",
        "system": "unify",
        "use_case_slug": "ecommerce-trading-review",
        "run_id": run_id,
        "orchestra_url": os.environ["ORCHESTRA_URL"],
        "context": ctx,
        "seed": seed,
        "anchor_week": anchor,
        "n_runs": n_runs,
        "unillm_cache": os.environ.get("UNILLM_CACHE"),
        "unify_model_env": os.environ.get("UNIFY_MODEL"),
        "brief_source": str(tsx_path),
        "brief_sha256": brief_digest(brief),
        "brief_verbatim": brief,
        "utterance": utterance,
        "ground_truth": ground_truth,
        "runs": [],
    }

    if check_only:
        print("\n[check] utterance that would be issued:\n")
        print(utterance)
        print("\n[check] plumbing ok; no LLM call made")
        with open(results_dir / "check.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)
        fixture.stop()
        return 0

    # ── Phase: setup (the brief → a recurring Monday task) ──────────────────
    print("[setup] issuing the brief ...")
    with ledger.phase("setup"):
        handle = await actor.act(utterance, persist=False)
        setup_status, setup_text = await _await_handle(handle, phase_timeout_s)
        if not await ledger.wait_quiescent(
            idle_seconds=quiesce_idle_s,
            timeout_seconds=quiesce_timeout_s,
        ):
            print("[setup] warning: LLM activity still ongoing at quiesce timeout")
    print(f"[setup] {setup_status}: {setup_text[:300]}")
    results["setup"] = {"status": setup_status, "result": setup_text}

    # A dry run during setup is a fair reading of the brief, which asks for a
    # schedule without forbidding an immediate run. Those posts are setup's.
    setup_posts = fixture.sink.snapshot()
    posts_seen = len(setup_posts)
    results["setup"]["posts"] = posts_seen
    if posts_seen:
        results["setup"]["dry_run_score"] = score_run(
            setup_posts,
            seed=seed,
            anchor=anchor,
        )
        print(f"[setup] posted {posts_seen} review(s) during setup (scored separately)")

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
    start_at = (results["task_after_setup"].get("schedule") or {}).get("start_at")
    if start_at:
        print(f"[align] task activates {start_at}; fixture is pinned to week {anchor}")

    # ── Phases: Monday wakes ────────────────────────────────────────────────
    delegate = _MeasuredTaskExecutionDelegate(actor)
    for i in range(1, n_runs + 1):
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

        with ledger.phase(f"run_{i}_review"):
            if not await ledger.wait_quiescent(
                idle_seconds=quiesce_idle_s,
                timeout_seconds=quiesce_timeout_s,
            ):
                print(f"[run_{i}] warning: LLM activity still ongoing at quiesce timeout")

        after = scheduler._filter_tasks(filter=f"task_id == {task.task_id}")[0]
        posted = fixture.sink.snapshot()[posts_seen:]
        posts_seen += len(posted)
        scored = score_run(posted, seed=seed, anchor=anchor)
        aligned = scored["week_reported"] == anchor
        row = {
            "run": i,
            "status": run_status,
            "entrypoint_before": before.entrypoint,
            "entrypoint_after": after.entrypoint,
            "regime": "entrypoint" if before.entrypoint is not None else "description",
            "window": {
                "aligned": aligned,
                "anchor": anchor,
                "week_reported": scored["week_reported"],
            },
            **scored,
            "result": run_text[:2000],
        }
        results["runs"].append(row)
        print(
            f"[run_{i}] {run_status} ({row['regime']}); posted={row['posted']} "
            f"week={row['week_reported']} flags={len(row['flags_matched'])}"
            f"/{len(row['flags_expected'])} extra={len(row['flags_extra'])} "
            f"moved={row['moved']} entrypoint_after={after.entrypoint}",
        )
        if not aligned:
            print(
                f"[run_{i}] WINDOW MISALIGNED: reported {row['week_reported']} but the "
                f"anomalies are planted in {anchor} — flags from this run mean nothing",
            )

    final_task = scheduler._filter_tasks(filter=f"task_id == {task.task_id}")[0]
    results["task_final"] = _task_snapshot(final_task)
    if final_task.entrypoint is not None:
        results["entrypoint_function"] = _function_snapshot(final_task.entrypoint)

    _finalize(results, ledger, results_dir, fixture)
    return 0


def _usd(amount: float) -> str:
    if amount >= 1:
        return f"${amount:.2f}"
    if amount >= 0.10:
        return f"${amount:.3f}"
    return f"${amount:.4f}"


def _transcription_block(results: dict[str, Any], phases: list[Any]) -> list[str]:
    """The figures eligible for the landing page, and the ones that are not."""
    runs = results.get("runs") or []
    if not runs:
        return ["", "## Landing-page transcription", "", "No run completed — nothing eligible."]
    first = next((r for r in runs if r["window"]["aligned"]), None)
    if first is None:
        return [
            "",
            "## Landing-page transcription",
            "",
            f"**Nothing is eligible.** No run reported on week "
            f"{runs[0]['window']['anchor']}, where the anomalies are planted — weeks "
            f"seen: {[r['window']['week_reported'] for r in runs]}.",
        ]
    by_name = {p.to_json()["name"]: p.to_json() for p in phases}
    exec_phase = by_name.get(f"run_{first['run']}", {})
    review_phase = by_name.get(f"run_{first['run']}_review", {})
    setup_phase = by_name.get("setup", {})
    exec_cost = float(exec_phase.get("provider_cost_usd") or 0.0)
    wall_min = float(exec_phase.get("wall_seconds") or 0.0) / 60.0
    caught = len(first["flags_matched"])
    total = len(first["flags_expected"])
    lines = [
        "",
        "## Landing-page transcription",
        "",
        f"Brief sha256 `{results['brief_sha256'][:16]}` · seed `{results['seed']}` "
        f"· week `{results['anchor_week']}`",
        "",
        "| page figure | value | where it comes from |",
        "|---|---|---|",
        f"| cost of one Monday review | {_usd(exec_cost)} | "
        f"run_{first['run']} ({first['regime']} regime) provider cost |",
        f"| the review is ready in | {wall_min:.0f} min | "
        f"run_{first['run']} wall time, twelve weeks of history |",
        f"| signals caught | {caught} of {total} | "
        f"{first['flags_extra'] and len(first['flags_extra']) or 0} extra, "
        f"{len(first['flags_missed'])} missed |",
        "",
        "The repeat-rate slide is planted to begin two weeks before the reported "
        "week, so catching it means catching it the first week it qualified — not "
        "a comparison against how long a person would have taken.",
        "",
        "Not page-eligible:",
        "",
        f"- setup (one-off, utterance → task): "
        f"{_usd(float(setup_phase.get('provider_cost_usd') or 0.0))}",
        f"- post-run review tail: {_usd(float(review_phase.get('provider_cost_usd') or 0.0))}",
    ]
    for row in runs:
        if row is first:
            continue
        name = f"run_{row['run']}"
        cost = float(by_name.get(name, {}).get("provider_cost_usd") or 0.0)
        lines.append(
            f"- {name} ({row['regime']} regime): {_usd(cost)}, "
            f"entrypoint {row['entrypoint_before']} → {row['entrypoint_after']}",
        )
    return lines


def _finalize(
    results: dict[str, Any],
    ledger: Any,
    results_dir: Path,
    fixture: Any,
) -> None:
    phases = ledger.summarize()
    results["phases"] = [p.to_json() for p in phases]
    results["posts"] = fixture.sink.snapshot()
    results["finished_at"] = datetime.now(timezone.utc).isoformat()

    ledger.dump(results_dir / "ledger.jsonl")
    with open(results_dir / "results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    lines = [
        f"# ecommerce-trading-review (unify arm) — {results['run_id']}",
        "",
        f"- orchestra: `{results['orchestra_url']}`",
        f"- context: `{results['context']}`",
        f"- UNILLM_CACHE: `{results.get('unillm_cache')}`",
        f"- week reported: `{results['anchor_week']}` · seed `{results['seed']}`",
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
        "| run | regime | status | week | flags | extra | missed | moved |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results.get("runs", []):
        lines.append(
            f"| {r['run']} | {r['regime']} | {r['status']} | {r['week_reported']} | "
            f"{len(r['flags_matched'])}/{len(r['flags_expected'])} | "
            f"{len(r['flags_extra'])} | {len(r['flags_missed'])} | {r['moved']} |",
        )
    lines += _transcription_block(results, phases)
    summary = "\n".join(lines) + "\n"
    with open(results_dir / "summary.md", "w", encoding="utf-8") as f:
        f.write(summary)

    fixture.stop()
    print(f"\n{summary}")
    print(f"[done] results in {results_dir}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
