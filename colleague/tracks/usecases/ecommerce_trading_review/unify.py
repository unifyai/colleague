"""ecommerce-trading-review: the unify-cm arm, person-shaped.

Delivers the landing page's `brief` verbatim as one owner message through
the ConversationManager session and lets the system decide how the Monday
work comes to recur. Each metered run is then the clock: the harness
delivers a due tick for whatever task the system itself scheduled (through
the CM's own due-task path) and observes the fixture's sink. Every LLM call
is metered per phase; the posted review is scored against ground truth
recomputed from the served weekly series.

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
            "Environment not prepared (use run_unify.sh):\n  - "
            + "\n  - ".join(problems),
        )
    if (
        STAGING_ORCHESTRA_HOST not in orchestra_url
        and os.environ.get("ETR_ALLOW_NON_STAGING") != "true"
    ):
        raise SystemExit(
            f"ORCHESTRA_URL={orchestra_url} is not staging. "
            f"Set ETR_ALLOW_NON_STAGING=true to override.",
        )


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

    from colleague.harness.llm_ledger import LLMLedger
    from colleague.tracks.usecases.ecommerce_trading_review.fixture import (
        DEFAULT_PORT,
        DEFAULT_SEED,
        FixtureServer,
    )
    from colleague.tracks.usecases.ecommerce_trading_review.fixture import (
        selftest as fixture_selftest,
    )
    from colleague.tracks.usecases.ecommerce_trading_review.protocol import (
        DEFAULT_USECASES_TSX,
        brief_digest,
        extract_brief,
        score_run,
    )
    from colleague.tracks.usecases.ecommerce_trading_review.protocol import (
        selftest as scorer_selftest,
    )
    from colleague.tracks.usecases.ecommerce_trading_review.protocol import (
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
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + "-unify-cm"

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

    # ── Boot the ConversationManager session (the arm's one door) ──────────
    from colleague.arms.sessions import build as build_session

    project = os.environ.get("ETR_PROJECT", "Benchmarks")
    print(f"[boot] orchestra={os.environ['ORCHESTRA_URL']}")
    session: Any = None
    if not check_only:
        session = build_session(
            "unify-cm",
            run_id=run_id,
            track="usecases/ecommerce_trading_review",
            results_dir=results_dir,
            ledger=ledger,
        )
        session.setup()
        # The phases below own the attribution; turn marks would fragment it.
        session.auto_turn_boundaries = False
        print(f"[boot] context={session.context}")

    results: dict[str, Any] = {
        "experiment": "usecases/ecommerce_trading_review",
        "system": "unify-cm",
        "regime": "person",
        "use_case_slug": "ecommerce-trading-review",
        "run_id": run_id,
        "orchestra_url": os.environ["ORCHESTRA_URL"],
        "context": session.context if session is not None else None,
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

    # ── Phase: setup (the brief, as one owner message) ──────────────────────
    # The brief arrives the way a person's would: through the CM, from the
    # owner. Its clarification channel is real here — an earlier bare-actor
    # run correctly stopped to ask which timezone "Monday 07:00" means, and
    # with nobody listening no task was ever created. Now the owner answers,
    # with one scripted, information-free line; whatever the system settles
    # on is part of what this measures. (Timezone does not move the scoring:
    # the fixture's weeks are dates, not instants.)
    from colleague.tracks.standing.series.person import owner_pool

    # The owner persona: same information bound as the old scripted line
    # (the brief is complete by construction, nothing is ever added), a
    # person's wording, metered apart from the arm.
    pool = owner_pool(results_dir=results_dir, run_id=run_id)
    pool.note_authored("owner", utterance)
    clarifications: list[dict[str, Any]] = []

    def _responder(question: str, who: str | None = None) -> str:
        answer = pool.answer("owner", question)
        exchanges = pool.exchanges()
        label = exchanges[-1].get("label") if exchanges else None
        clarifications.append(
            {"question": question, "who": who, "answer": answer, "label": label},
        )
        return answer

    session.on_clarification(_responder)

    print("[setup] issuing the brief ...")
    with ledger.phase("setup"):
        reply = session.send(utterance, timeout=phase_timeout_s)
        setup_status = "completed" if reply.ok else "error"
        setup_text = str(reply.text or reply.error)
        if not await ledger.wait_quiescent(
            idle_seconds=quiesce_idle_s,
            timeout_seconds=quiesce_timeout_s,
        ):
            print("[setup] warning: LLM activity still ongoing at quiesce timeout")
    print(f"[setup] {setup_status}: {setup_text[:300]}")
    results["setup"] = {"status": setup_status, "result": setup_text}
    results["clarifications"] = clarifications

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

    # What the system bound to the clock — an observation, not a gate.
    tasks = session.scheduled_recurrences()
    results["task_after_setup"] = tasks[0] if len(tasks) == 1 else None
    results["recurring_tasks_found"] = tasks
    print(
        f"[setup] the system scheduled {len(tasks)} recurring task(s)"
        + (
            f"; task_id={tasks[0]['task_id']} entrypoint={tasks[0]['entrypoint']}"
            if len(tasks) == 1
            else ""
        ),
    )
    start_at = ((results.get("task_after_setup") or {}).get("schedule") or {}).get(
        "start_at",
    )
    if start_at:
        print(f"[align] task activates {start_at}; fixture is pinned to week {anchor}")

    # ── Phases: Monday wakes — the harness is only the clock ───────────────
    for i in range(1, n_runs + 1):
        before_tasks = session.scheduled_recurrences()
        entrypoint_before = next(
            (t["entrypoint"] for t in before_tasks if t["entrypoint"] is not None),
            None,
        )
        print(f"[run_{i}] the clock ticks (entrypoint before: {entrypoint_before}) ...")
        with ledger.phase(f"run_{i}"):
            fired = session.fire_due_recurrences()
            settled = session.settle(timeout=phase_timeout_s)
            errors = [f["error"] for f in fired if f.get("error")]
            if not fired:
                run_status = "nothing_scheduled"
                run_text = "no recurring task existed for the clock to fire"
            elif errors:
                run_status = "error"
                run_text = "; ".join(errors)
            elif not settled:
                run_status = "timeout"
                run_text = f"tick started but did not settle within {phase_timeout_s}s"
            else:
                run_status = "completed"
                run_text = json.dumps(fired)

        with ledger.phase(f"run_{i}_review"):
            if not await ledger.wait_quiescent(
                idle_seconds=quiesce_idle_s,
                timeout_seconds=quiesce_timeout_s,
            ):
                print(
                    f"[run_{i}] warning: LLM activity still ongoing at quiesce timeout",
                )

        after_tasks = session.scheduled_recurrences()
        entrypoint_after = next(
            (t["entrypoint"] for t in after_tasks if t["entrypoint"] is not None),
            None,
        )
        posted = fixture.sink.snapshot()[posts_seen:]
        posts_seen += len(posted)
        scored = score_run(posted, seed=seed, anchor=anchor)
        aligned = scored["week_reported"] == anchor
        row = {
            "run": i,
            "status": run_status,
            "fired": fired,
            "entrypoint_before": entrypoint_before,
            "entrypoint_after": entrypoint_after,
            "regime": "entrypoint" if entrypoint_before is not None else "description",
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
            f"moved={row['moved']} entrypoint_after={entrypoint_after}",
        )
        if not aligned:
            print(
                f"[run_{i}] WINDOW MISALIGNED: reported {row['week_reported']} but the "
                f"anomalies are planted in {anchor} — flags from this run mean nothing",
            )

    final_tasks = session.scheduled_recurrences()
    results["task_final"] = final_tasks[0] if len(final_tasks) == 1 else None
    results["recurring_tasks_final"] = final_tasks
    final_entrypoint = next(
        (t["entrypoint"] for t in final_tasks if t["entrypoint"] is not None),
        None,
    )
    if final_entrypoint is not None:
        results["entrypoint_function"] = _function_snapshot(final_entrypoint)

    # The environment's own spend, apart from the arm's phases; captured at
    # the end so questions raised during the metered runs are counted too.
    owner_evidence = pool.evidence()
    results["persona_exchanges"] = len(owner_evidence["persona_exchanges"])
    results["persona_tokens"] = owner_evidence["persona_tokens"]
    _finalize(results, ledger, results_dir, fixture)
    session.close()
    return 0


def _usd(amount: float | None) -> str:
    if amount is None:
        return "**not measured**"
    if amount >= 1:
        return f"${amount:.2f}"
    if amount >= 0.10:
        return f"${amount:.3f}"
    return f"${amount:.4f}"


def _transcription_block(results: dict[str, Any], phases: list[Any]) -> list[str]:
    """The figures eligible for the landing page, and the ones that are not."""
    runs = results.get("runs") or []
    if not runs:
        return [
            "",
            "## Landing-page transcription",
            "",
            "No run completed — nothing eligible.",
        ]
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
    exec_cost = exec_phase.get("provider_cost_usd")
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
        f"{_usd(setup_phase.get('provider_cost_usd'))}",
        f"- post-run review tail: {_usd(review_phase.get('provider_cost_usd'))}",
    ]
    for row in runs:
        if row is first:
            continue
        name = f"run_{row['run']}"
        cost = by_name.get(name, {}).get("provider_cost_usd")
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
        f"# ecommerce-trading-review (unify-cm arm, person-shaped) — {results['run_id']}",
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
