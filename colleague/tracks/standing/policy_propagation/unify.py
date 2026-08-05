"""Policy propagation benchmark: Unify arm.

Same standalone boot and metering as the other experiments. Three verbal
requests create three recurring automations (each stating the escalation
policy verbatim); after two rounds under the initial policy, one verbal
policy-update message is delivered, then three more rounds fire — scored
against the updated policy. Function implementations are snapshotted before
and after the change so the results record exactly which stored artifacts
the update touched.

Launch via run_unify.sh.
"""

from __future__ import annotations

import asyncio
import hashlib
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


def _function_snapshots() -> dict[int, dict[str, Any]]:
    """id -> {name, sha} for every stored compositional function."""
    from unify.manager_registry import ManagerRegistry

    fm = ManagerRegistry.get_function_manager()
    out: dict[int, dict[str, Any]] = {}
    try:
        rows = fm.filter_functions(filter=None, limit=200)
    except Exception:
        return out
    for row in rows or []:
        if not isinstance(row, dict) or row.get("function_id") is None:
            continue
        impl = str(row.get("implementation") or "")
        out[int(row["function_id"])] = {
            "name": row.get("name"),
            "sha": hashlib.sha256(impl.encode()).hexdigest()[:12],
        }
    return out


async def main() -> int:
    _require_env()

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
    from colleague.tracks.standing.recurring_report.measure import LLMLedger

    seed = int(os.environ.get("PP_SEED", DEFAULT_SEED))
    port = int(os.environ.get("PP_PORT", DEFAULT_PORT))
    phase_timeout_s = float(os.environ.get("PP_PHASE_TIMEOUT_S", "1800"))
    quiesce_idle_s = float(os.environ.get("PP_QUIESCE_IDLE_S", "180"))
    quiesce_timeout_s = float(os.environ.get("PP_QUIESCE_TIMEOUT_S", "1800"))
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + "-unify"

    results_dir = EXPERIMENT_DIR / "results" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    fixture = PolicyFixtureServer(seed=seed, port=port).start()
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
        f"colleague/policy_propagation/{run_id}"
        f"/{UNASSIGNED_USER_CONTEXT}/{UNASSIGNED_ASSISTANT_CONTEXT}"
    )
    print(f"[boot] orchestra={os.environ['ORCHESTRA_URL']}")
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
    print("[boot] actor + managers ready")

    results: dict[str, Any] = {
        "experiment": "policy_propagation",
        "system": "unify",
        "run_id": run_id,
        "orchestra_url": os.environ["ORCHESTRA_URL"],
        "context": ctx,
        "seed": seed,
        "automations": list(AUTOMATIONS),
        "pre_change_rounds": PRE_CHANGE_ROUNDS,
        "post_change_rounds": POST_CHANGE_ROUNDS,
        "initial_threshold": INITIAL_THRESHOLD,
        "updated_threshold": UPDATED_THRESHOLD,
        "policy_update_message": POLICY_UPDATE_MESSAGE,
        "utterances": {a: build_utterance(a, fixture.base_url) for a in AUTOMATIONS},
        "fires": [],
    }

    # ── Three setups; identify each automation's task by diffing ───────────
    task_ids: dict[str, int] = {}
    seen: set[int] = set()
    for automation in AUTOMATIONS:
        print(f"[setup_{automation}] issuing utterance ...")
        with ledger.phase(f"setup_{automation}"):
            handle = await actor.act(
                build_utterance(automation, fixture.base_url),
                persist=False,
            )
            status, text = await _await_handle(handle, phase_timeout_s)
            if not await ledger.wait_quiescent(
                idle_seconds=quiesce_idle_s,
                timeout_seconds=quiesce_timeout_s,
            ):
                print(f"[setup_{automation}] warning: quiesce timeout")
        recurring = [
            t
            for t in scheduler._filter_tasks(filter=None, limit=100)
            if t.repeat is not None or t.trigger is not None
        ]
        new_ids = sorted({t.task_id for t in recurring} - seen)
        seen.update(new_ids)
        results[f"setup_{automation}"] = {"status": status, "result": text[:1500]}
        if status != "completed" or len(new_ids) != 1:
            _finalize(results, ledger, results_dir, fixture)
            print(
                f"[abort] setup_{automation}: status={status}, "
                f"new recurring tasks={new_ids}",
            )
            return 1
        task_ids[automation] = new_ids[0]
        print(f"[setup_{automation}] task_id={new_ids[0]}")
    results["task_ids"] = task_ids

    delegate = _BenchmarkTaskExecutionDelegate(actor)

    async def fire(automation: str, round_no: int, threshold: int) -> None:
        cursor_before, released_now, batches_before = prepare_fire(
            fixture,
            automation,
        )
        tid = task_ids[automation]
        before = scheduler._filter_tasks(filter=f"task_id == {tid}")[0]
        label = f"round{round_no}_{automation}"
        print(
            f"[fire_{label}] pending {cursor_before + 1}..{released_now} "
            f"(entrypoint: {before.entrypoint})",
        )
        with ledger.phase(f"fire_{label}"):
            token = current_task_execution_delegate.set(delegate)
            try:
                status, text = "error", "execute() raised before returning a handle"
                handle = await scheduler.execute(
                    task_id=tid,
                    _activated_by=ActivatedBy.schedule,
                )
                status, text = await _await_handle(handle, phase_timeout_s)
            except Exception as exc:
                text = f"{type(exc).__name__}: {exc}"
            finally:
                current_task_execution_delegate.reset(token)
        with ledger.phase(f"fire_{label}_review"):
            if not await ledger.wait_quiescent(
                idle_seconds=quiesce_idle_s,
                timeout_seconds=quiesce_timeout_s,
            ):
                print(f"[fire_{label}] warning: quiesce timeout")
        after = scheduler._filter_tasks(filter=f"task_id == {tid}")[0]
        row = {
            "round": round_no,
            "automation": automation,
            "threshold": threshold,
            "status": status,
            "entrypoint_before": before.entrypoint,
            "entrypoint_after": after.entrypoint,
            **score_fire(
                fixture,
                automation,
                cursor_before=cursor_before,
                released_now=released_now,
                batches_before=batches_before,
                threshold=threshold,
            ),
            "result": text[:800],
        }
        results["fires"].append(row)
        print(
            f"[fire_{label}] {status}; delivered={row['batches_delivered']} "
            f"correct={row['correct']} accuracy={row['accuracy']}",
        )

    round_no = 0
    for _ in range(PRE_CHANGE_ROUNDS):
        round_no += 1
        release_round(fixture)
        for automation in AUTOMATIONS:
            await fire(automation, round_no, INITIAL_THRESHOLD)

    # ── The measured event: one verbal policy update ───────────────────────
    functions_before = _function_snapshots()
    print("[policy_change] issuing update ...")
    with ledger.phase("policy_change"):
        handle = await actor.act(POLICY_UPDATE_MESSAGE, persist=False)
        change_status, change_text = await _await_handle(handle, phase_timeout_s)
        if not await ledger.wait_quiescent(
            idle_seconds=quiesce_idle_s,
            timeout_seconds=quiesce_timeout_s,
        ):
            print("[policy_change] warning: quiesce timeout")
    functions_after = _function_snapshots()
    changed = {
        fid: {"before": functions_before.get(fid), "after": snap}
        for fid, snap in functions_after.items()
        if functions_before.get(fid, {}).get("sha") != snap["sha"]
    }
    results["policy_change"] = {
        "status": change_status,
        "result": change_text[:2000],
        "functions_changed": changed,
        "functions_total": len(functions_after),
    }
    print(
        f"[policy_change] {change_status}; functions touched: "
        f"{[v['after']['name'] for v in changed.values()]}",
    )

    for _ in range(POST_CHANGE_ROUNDS):
        round_no += 1
        release_round(fixture)
        for automation in AUTOMATIONS:
            await fire(automation, round_no, UPDATED_THRESHOLD)

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
        f"# policy_propagation (unify arm) — {results['run_id']}",
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
        "| round | automation | threshold | delivered | contract | accuracy |",
        "|---|---|---|---|---|---|",
    ]
    for r in results.get("fires", []):
        lines.append(
            f"| {r['round']} | {r['automation']} | ${r['threshold']} | "
            f"{r['batches_delivered']} | {r['correct']} | {r['accuracy']} |",
        )
    summary = "\n".join(lines) + "\n"
    (results_dir / "summary.md").write_text(summary, encoding="utf-8")
    fixture.stop()
    print(f"\n{summary}")
    print(f"[done] results in {results_dir}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
