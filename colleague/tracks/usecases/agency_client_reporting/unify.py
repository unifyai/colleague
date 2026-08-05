"""agency-client-reporting: the unify arm.

Boots the Unify brain standalone against a hosted Orchestra (staging by
default), hands it the landing page's `brief` verbatim, then drives the
monthly wake through `TaskScheduler.execute` with the same delegate mechanics
the production ConversationManager uses for due tasks. Every LLM call is
metered per phase; every delivered report is scored against ground truth
recomputed from the served data.

The outputs the landing page draws on:

  - cost per client report   = the reporting phase's provider cost / reports
  - one cycle, wall-clock    = the reporting phase's wall time, all clients
  - flags found              = matched against the planted set, exactly

`summary.md` ends with a transcription block naming the figures that are
eligible to appear on the page, so nothing reaches marketing copy by being
retyped from memory.

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
        and os.environ.get("ACR_ALLOW_NON_STAGING") != "true"
    ):
        raise SystemExit(
            f"ORCHESTRA_URL={orchestra_url} is not staging. "
            f"Set ACR_ALLOW_NON_STAGING=true to override.",
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


def _activation_anchor(start_at: str | None) -> str | None:
    """The month a wake firing at `start_at` reports on: the month before it.

    A description-driven run reads the activation it believes it is running
    at rather than the wall clock, so a task whose first fire is 2026-09-01
    reports 2026-08 however early the harness fires it. Returns None when the
    task carries no start_at, or one this cannot parse.
    """
    if not start_at:
        return None
    from colleague.tracks.usecases.agency_client_reporting.fixture import (
        month_str,
        prev_month,
    )

    try:
        stamp = datetime.fromisoformat(str(start_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return prev_month(month_str(stamp.date()))


def _expected_anchor(regime: str, activation: str | None, wall_clock: str) -> str:
    """The month the next run will report on, given the regime it runs in.

    The two regimes disagree about what "last month" means when a task is
    fired ahead of its schedule: a description-driven run reads its own
    activation, a stored entrypoint reads the wall clock. The fixture can only
    pin its anomalies to one pair at a time, so the harness follows the run
    rather than hoping the two agree — the task's reading of its own schedule
    is the correct one, and so is the entrypoint's reading of the clock.
    """
    if regime == "entrypoint":
        return wall_clock
    return activation or wall_clock


def _window_alignment(scored: dict[str, Any], anchor: str) -> dict[str, Any]:
    """Whether the system reported on the month the plants are pinned to.

    `_expected_anchor` should have moved the plants onto the pair this run was
    always going to compare, so a misalignment here means that prediction was
    wrong — the run read its window from something other than its activation
    or the clock. Either way the flag count measures nothing about detection,
    and it fails silently, looking like a perfect zero-flag month. This is the
    guard that stops that reaching a page as a figure.
    """
    reported = sorted({r["month"] for r in scored["clients"] if r["month"]})
    return {
        "aligned": reported == [anchor],
        "anchor": anchor,
        "months_reported": reported,
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
    from colleague.tracks.usecases.agency_client_reporting.fixture import (
        DEFAULT_PORT,
        DEFAULT_SEED,
        FixtureServer,
        selftest as fixture_selftest,
    )
    from colleague.tracks.usecases.agency_client_reporting.protocol import (
        DEFAULT_USECASES_TSX,
        brief_digest,
        extract_brief,
        score_run,
        selftest as scorer_selftest,
        utterance as build_utterance,
    )

    seed = int(os.environ.get("ACR_SEED", DEFAULT_SEED))
    port = int(os.environ.get("ACR_PORT", DEFAULT_PORT))
    n_runs = int(os.environ.get("ACR_RUNS", "1"))
    phase_timeout_s = float(os.environ.get("ACR_PHASE_TIMEOUT_S", "3600"))
    quiesce_idle_s = float(os.environ.get("ACR_QUIESCE_IDLE_S", "180"))
    quiesce_timeout_s = float(os.environ.get("ACR_QUIESCE_TIMEOUT_S", "1800"))
    check_only = os.environ.get("ACR_CHECK", "").lower() == "true"
    tsx_path = Path(os.environ.get("ACR_USECASES_TSX") or DEFAULT_USECASES_TSX)
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + "-unify"

    results_dir = EXPERIMENT_DIR / "results" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    # Ground truth and the scoring path are proved before anything is spent.
    ground_truth = fixture_selftest(seed)
    scorer_selftest(seed, ground_truth["anchor"])
    # The month before now. Setup runs against this, since the task whose
    # activation decides the metered months does not exist yet; each metered
    # run then re-anchors to the pair it is actually going to compare.
    boot_anchor = ground_truth["anchor"]
    anchor = boot_anchor
    print(
        f"[fixture] selftest ok — anchor={anchor} clients={ground_truth['clients']} "
        f"campaigns={ground_truth['campaigns']} "
        f"planted_flags={ground_truth['flagged_campaigns']} "
        f"across {len(ground_truth['flagged_clients'])} clients",
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

    project = os.environ.get("ACR_PROJECT", "Benchmarks")
    ctx = (
        f"colleague/usecases/agency_client_reporting/{run_id}"
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
        "experiment": "usecases/agency_client_reporting",
        "system": "unify",
        "use_case_slug": "agency-client-reporting",
        "run_id": run_id,
        "orchestra_url": os.environ["ORCHESTRA_URL"],
        "context": ctx,
        "seed": seed,
        "anchor_month": boot_anchor,
        "n_runs": n_runs,
        "quiesce_idle_s": quiesce_idle_s,
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

    # ── Phase: setup (the brief → a recurring monthly task) ─────────────────
    print("[setup] issuing the brief ...")
    with ledger.phase("setup"):
        # Unattended, as the page describes it: nobody is watching the 1st-of-
        # the-month wake. With clarification on, an ambiguity in the brief stops
        # the actor to ask and no task is ever created — the trading-review
        # brief hit exactly that over the timezone of "Monday at 07:00".
        # Whatever it settles on unattended is part of what this measures.
        handle = await actor.act(utterance, persist=False, clarification_enabled=False)
        setup_status, setup_text = await _await_handle(handle, phase_timeout_s)
        # Detached post-act work (storage review) belongs to setup: wait for it.
        if not await ledger.wait_quiescent(
            idle_seconds=quiesce_idle_s,
            timeout_seconds=quiesce_timeout_s,
        ):
            print("[setup] warning: LLM activity still ongoing at quiesce timeout")
    print(f"[setup] {setup_status}: {setup_text[:300]}")
    results["setup"] = {"status": setup_status, "result": setup_text}

    # The brief asks for a schedule and never says "don't run one now", so a
    # dry run during setup is a legitimate reading of it. Those deliveries are
    # setup's, not the first month's: close the window here so per-report cost
    # is divided by reports the metered run actually produced.
    setup_deliveries = fixture.sink.snapshot()
    deliveries_seen = len(setup_deliveries)
    results["setup"]["deliveries_posted"] = deliveries_seen
    if deliveries_seen:
        # Scored at the boot anchor: that is what the fixture was serving while
        # setup ran, so it is the only pair this dry run could have seen —
        # whatever month it chose to call "last month".
        dry_score = score_run(
            setup_deliveries,
            seed=seed,
            anchor=boot_anchor,
            # Everything that has failed so far belongs to setup.
            infra_failures=len(ledger.failures()),
        )
        dry_score["window"] = _window_alignment(dry_score, boot_anchor)
        results["setup"]["dry_run_score"] = dry_score
        print(
            f"[setup] posted {deliveries_seen} deliveries during setup "
            f"(scored separately, "
            f"{'aligned' if dry_score['window']['aligned'] else 'WINDOW MISALIGNED'})",
        )

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
    activation_anchor = _activation_anchor(start_at)
    results["activation_start_at"] = start_at
    results["activation_anchor"] = activation_anchor
    if start_at:
        print(
            f"[align] task activates {start_at} (reports {activation_anchor}); "
            f"fixture booted pinned to {anchor}",
        )

    # ── Phases: monthly wakes ───────────────────────────────────────────────
    delegate = _MeasuredTaskExecutionDelegate(actor)
    for i in range(1, n_runs + 1):
        before = scheduler._filter_tasks(filter=f"task_id == {task.task_id}")[0]
        regime = "entrypoint" if before.entrypoint is not None else "description"
        # Move the plants onto the pair this run is going to compare, before it
        # runs. Data is generated per request, so re-anchoring takes effect for
        # the next fetch; a run's own two months are therefore internally
        # consistent even when a later run is measured against a different pair.
        # By the time this runs, setup has already been paid for. A defect in
        # re-anchoring must not take the cycle down with it: fall back to the
        # anchor the fixture is already serving, record that it happened, and
        # let the alignment guard downstream decide what the run is worth.
        try:
            run_anchor = _expected_anchor(regime, activation_anchor, boot_anchor)
            if run_anchor != fixture.anchor:
                fixture.set_anchor(run_anchor)
                print(
                    f"[align] run_{i} runs {regime}, so it reports {run_anchor}; "
                    f"re-anchoring the fixture from {anchor} and re-deriving "
                    f"ground truth",
                )
            # Prove the fixture and the scorer at this anchor, not just at boot:
            # the sweep and the planted set are anchor-dependent, and this is
            # the ground truth the run about to execute is scored against.
            run_truth = fixture_selftest(seed, run_anchor)
            scorer_selftest(seed, run_anchor)
            anchor = run_anchor
            results.setdefault("ground_truth_by_anchor", {})[anchor] = run_truth
            print(
                f"[run_{i}] anchor={anchor} "
                f"planted_flags={run_truth['flagged_campaigns']} "
                f"across {len(run_truth['flagged_clients'])} clients",
            )
        except Exception as exc:
            realign_error = f"{type(exc).__name__}: {exc}"
            results.setdefault("realign_failures", []).append(
                {"run": i, "regime": regime, "error": realign_error},
            )
            fixture.set_anchor(anchor)
            print(
                f"[align] run_{i} re-anchoring FAILED ({realign_error}); "
                f"leaving the fixture on {anchor} — this run measures detection "
                f"only if it happens to report that month",
            )
        print(f"[run_{i}] executing (entrypoint before: {before.entrypoint}) ...")
        # Provider failures across this cycle, execution plus its review tail.
        # A dead call is why a client's report can come back empty on analysis
        # that never failed, so the scorer needs the count to decide whether an
        # unanswered client is a miss or unmeasurable.
        failures_before = len(ledger.failures())
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
        # is a month away, so reviews always finish in between. Restore that
        # invariant and attribute the review tail to its own phase.
        with ledger.phase(f"run_{i}_review"):
            if not await ledger.wait_quiescent(
                idle_seconds=quiesce_idle_s,
                timeout_seconds=quiesce_timeout_s,
            ):
                print(f"[run_{i}] warning: LLM activity still ongoing at quiesce timeout")

        after = scheduler._filter_tasks(filter=f"task_id == {task.task_id}")[0]
        delivered = fixture.sink.snapshot()[deliveries_seen:]
        deliveries_seen += len(delivered)
        run_failures = len(ledger.failures()) - failures_before
        scored = score_run(
            delivered,
            seed=seed,
            anchor=anchor,
            infra_failures=run_failures,
        )
        row = {
            "run": i,
            "status": run_status,
            "entrypoint_before": before.entrypoint,
            "entrypoint_after": after.entrypoint,
            "regime": regime,
            "anchor": anchor,
            "window": _window_alignment(scored, anchor),
            **scored,
            "result": run_text[:2000],
        }
        results["runs"].append(row)
        print(
            f"[run_{i}] {run_status} ({row['regime']}); "
            f"delivered={row['clients_delivered']}"
            f"/{row['clients_total']} drafted={row['reports_drafted']} "
            f"blocked={row['reports_blocked']} flags={row['flags_matched_total']}"
            f"/{row['flags_measurable_total']} extra={row['flags_extra_total']} "
            f"entrypoint_after={after.entrypoint}",
        )
        if row["detection_status"] == "error":
            print(
                f"[run_{i}] DETECTION VOID: {row['flags_void_total']} planted flag(s) "
                f"sat in client(s) {', '.join(row['clients_void'])}, whose report died "
                f"while {run_failures} provider call(s) failed in this cycle. Detection "
                f"is unmeasured for this run, not low — the figure is withheld rather "
                f"than published against a denominator the run never reached.",
            )
        if not row["window"]["aligned"]:
            print(
                f"[run_{i}] WINDOW MISALIGNED: reported "
                f"{row['window']['months_reported']} but anomalies were re-anchored "
                f"to {anchor} for this {regime} run — flag counts from this run mean "
                f"nothing, and the run read its window from neither its activation "
                f"({activation_anchor}) nor the clock ({boot_anchor})",
            )

    final_task = scheduler._filter_tasks(filter=f"task_id == {task.task_id}")[0]
    results["task_final"] = _task_snapshot(final_task)
    if final_task.entrypoint is not None:
        results["entrypoint_function"] = _function_snapshot(final_task.entrypoint)

    _finalize(results, ledger, results_dir, fixture)
    return 0


def _usd(amount: float) -> str:
    """Money at the precision the number actually carries."""
    if amount >= 1:
        return f"${amount:.2f}"
    if amount >= 0.10:
        return f"${amount:.3f}"
    return f"${amount:.4f}"


def _transcription_block(results: dict[str, Any], phases: list[Any]) -> list[str]:
    """The figures eligible for the landing page, and the ones that are not.

    Figures come from the first metered month, whichever regime it ran in,
    and the regime is named beside them: a run executing a stored entrypoint
    is cheaper than one reasoning from the description, so a cost quoted
    without its regime describes a steady state a first month may not have
    reached. A run whose reported month missed the anomalies yields nothing —
    it looks like a clean sweep and is worth less than no measurement.
    """
    runs = results.get("runs") or []
    if not runs:
        return ["", "## Landing-page transcription", "", "No run completed — nothing eligible."]
    # The earliest run that actually looked at the anomalies. A description-driven
    # first month can miss the window while the entrypoint month after it lands.
    first = next((r for r in runs if r["window"]["aligned"]), None)
    if first is None:
        return [
            "",
            "## Landing-page transcription",
            "",
            f"**Nothing is eligible.** No run reported on {runs[0]['window']['anchor']}, "
            f"where the anomalies are pinned — months seen: "
            f"{[r['window']['months_reported'] for r in runs]}. Those flag counts are "
            f"not detection rates, and those costs are for reports with fewer flagged "
            f"campaigns to write up.",
        ]
    by_name = {p.to_json()["name"]: p.to_json() for p in phases}
    exec_phase = by_name.get(f"run_{first['run']}", {})
    review_phase = by_name.get(f"run_{first['run']}_review", {})
    setup_phase = by_name.get("setup", {})
    reports = first["reports_drafted"]
    exec_cost = float(exec_phase.get("provider_cost_usd") or 0.0)
    review_cost = float(review_phase.get("provider_cost_usd") or 0.0)
    wall_min = float(exec_phase.get("wall_seconds") or 0.0) / 60.0
    # A phase that did real work and metered no calls is a missing measurement,
    # not a free run: the unillm hook has gone missing mid-run before. Quoting
    # its zero as a cost is how a $0.0000 reaches a page.
    exec_metered = bool(exec_phase.get("llm_calls"))
    lines = [
        "",
        "## Landing-page transcription",
        "",
        f"Brief sha256 `{results['brief_sha256'][:16]}` · seed `{results['seed']}` "
        f"· month `{first.get('anchor') or first['window']['anchor']}`",
        "",
        "| page figure | value | where it comes from |",
        "|---|---|---|",
    ]
    if reports and exec_metered:
        lines.append(
            f"| cost of one client's report | {_usd(exec_cost / reports)} | "
            f"run_1 ({first['regime']} regime) provider cost {_usd(exec_cost)} / "
            f"{reports} reports drafted |",
        )
    elif reports:
        lines.append(
            "| cost of one client's report | **not measured** | the ledger recorded "
            "0 calls for this phase, so its cost is missing rather than zero — "
            "reconstruct from billing before any cost figure goes on the page |",
        )
    if reports:
        lines += [
            f"| one reporting cycle | {wall_min:.0f} min | "
            f"run_1 wall time, all {first['clients_total']} clients |",
        ]
        # A void client means detection was not measured. Publishing
        # `matched / planted` there would quote a real number against a
        # denominator the run never reached, which is how an infrastructure
        # timeout becomes a product weakness on a page.
        if first.get("detection_status") == "error":
            lines.append(
                f"| flagged campaigns | — | **not measured**: "
                f"{first['flags_void_total']} planted flag(s) sat in client(s) "
                f"{', '.join(first['clients_void'])}, whose report died alongside "
                f"{first.get('infra_failures', 0)} failed provider call(s). "
                f"Re-run before quoting a detection figure |",
            )
        else:
            lines.append(
                f"| flagged campaigns | {first['flags_matched_total']} | "
                f"matched of {first['flags_measurable_total']} measurable, "
                f"{first['flags_extra_total']} extra, "
                f"{first['flags_missed_total']} missed |",
            )
    else:
        lines.append("| — | — | no report was drafted; nothing is eligible |")
    lines += [
        "",
        "Not page-eligible:",
        "",
        f"- setup (one-off, utterance → task): {_usd(float(setup_phase.get('provider_cost_usd') or 0.0))}",
        f"- run_1 post-run review tail (once per cycle, not per report): {_usd(review_cost)}",
    ]
    for row in runs[1:]:
        name = f"run_{row['run']}"
        cost = float(by_name.get(name, {}).get("provider_cost_usd") or 0.0)
        lines.append(
            f"- {name} (converged regime, cheaper than any first month): {_usd(cost)}, "
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
    # The unillm hook has been lost mid-run before, leaving a phase table of
    # zeros for a run that was really billed (see the NOTE.md in
    # results/2026-08-04T17-36-52Z-unify). Name those phases here so a reader
    # of the committed file cannot mistake a missing measurement for a cheap
    # one, and so the transcription block refuses to quote their cost.
    results["ledger_void_phases"] = [
        j["name"]
        for j in results["phases"]
        if not j["llm_calls"] and float(j.get("wall_seconds") or 0.0) > 30.0
    ]
    # Every delivery, verbatim, so a transcribed figure can be re-derived from
    # what the system actually posted rather than from this file's arithmetic.
    results["deliveries"] = fixture.sink.snapshot()
    results["finished_at"] = datetime.now(timezone.utc).isoformat()

    ledger.dump(results_dir / "ledger.jsonl")
    with open(results_dir / "results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    lines = [
        f"# agency-client-reporting (unify arm) — {results['run_id']}",
        "",
        f"- orchestra: `{results['orchestra_url']}`",
        f"- context: `{results['context']}`",
        f"- UNILLM_CACHE: `{results.get('unillm_cache')}`",
        f"- fixture booted on `{results['anchor_month']}` (the month before now) "
        f"· seed `{results['seed']}`",
        f"- task activates `{results.get('activation_start_at') or '—'}`, which reports "
        f"`{results.get('activation_anchor') or '—'}`; each run is re-anchored to the "
        f"pair its own regime compares",
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
    if results.get("ledger_void_phases"):
        lines += [
            "",
            f"> **The cost column is void for "
            f"{', '.join('`' + n + '`' for n in results['ledger_void_phases'])}.** "
            f"Those phases did real work and the ledger metered no calls, so their "
            f"cost is missing, not zero. Reconstruct from "
            f"`GET /v0/credits/transactions?category=llm` and cross-check against the "
            f"account balance delta before any cost figure is quoted.",
        ]
    lines += [
        "",
        "| run | regime | month | status | delivered | drafted | blocked | flags matched | extra | missed |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results.get("runs", []):
        window = "" if r["window"]["aligned"] else " ⚠︎"
        lines.append(
            f"| {r['run']} | {r['regime']} | `{r.get('anchor', '—')}`{window} "
            f"| {r['status']} | {r['clients_delivered']}/{r['clients_total']} "
            f"| {r['reports_drafted']} | {r['reports_blocked']} | "
            f"{r['flags_matched_total']}/{r['flags_measurable_total']}"
            f"{' ⚠︎void' if r['detection_status'] == 'error' else ''} | "
            f"{r['flags_extra_total']} | {r['flags_missed_total']} |",
        )
    for r in results.get("runs", []):
        if r["detection_status"] == "error":
            lines += [
                "",
                f"⚠︎ Run {r['run']} — detection void. {r['flags_void_total']} planted "
                f"flag(s) were in client(s) "
                f"{', '.join('`' + c + '`' for c in r['clients_void'])}, whose report "
                f"died while {r.get('infra_failures', 0)} provider call(s) failed. "
                f"Those flags are excluded from the denominator rather than counted "
                f"as missed: detection is arithmetic over the served data and needs no "
                f"model, so a dead model call says nothing about whether the system "
                f"would have found them. Not a detection rate.",
            ]
    for r in results.get("runs", []):
        if not r["window"]["aligned"]:
            lines += [
                "",
                f"⚠︎ Run {r['run']} reported {r['window']['months_reported']}, not "
                f"`{r['window']['anchor']}` where the anomalies were pinned for it. "
                f"Its flag count is not a detection rate.",
            ]
    for r in results.get("runs", []):
        broken = r["broken_meta_client"]
        lines += [
            "",
            f"Run {r['run']} — client `{broken['client_id']}` (expired Meta connection): "
            f"status `{broken['status']}`, reason: {broken['blocked_reason'] or '—'}",
        ]
    lines += _transcription_block(results, phases)
    summary = "\n".join(lines) + "\n"
    with open(results_dir / "summary.md", "w", encoding="utf-8") as f:
        f.write(summary)

    fixture.stop()
    print(f"\n{summary}")
    print(f"[done] results in {results_dir}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
