"""agency-client-reporting: the unify-cm arm, person-shaped.

Delivers the landing page's `brief` verbatim as one owner message through
the ConversationManager session — the same door every conversational track
uses — and lets the system decide how the monthly work comes to recur.
Each metered month is then the clock: the harness re-anchors the fixture,
delivers a due tick for whatever task the system itself scheduled (through
the CM's own due-task path, `arms/sessions/unify_cm_session.py`), and
observes the fixture's sink. Every LLM call is metered per phase; every
delivered report is scored against ground truth recomputed from the served
data.

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
            "Environment not prepared (use run_unify.sh):\n  - "
            + "\n  - ".join(problems),
        )
    if (
        STAGING_ORCHESTRA_HOST not in orchestra_url
        and os.environ.get("ACR_ALLOW_NON_STAGING") != "true"
    ):
        raise SystemExit(
            f"ORCHESTRA_URL={orchestra_url} is not staging. "
            f"Set ACR_ALLOW_NON_STAGING=true to override.",
        )


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

    from colleague.harness.llm_ledger import LLMLedger
    from colleague.tracks.usecases.agency_client_reporting.fixture import (
        DEFAULT_PORT,
        DEFAULT_SEED,
        FixtureServer,
    )
    from colleague.tracks.usecases.agency_client_reporting.fixture import (
        selftest as fixture_selftest,
    )
    from colleague.tracks.usecases.agency_client_reporting.protocol import (
        DEFAULT_USECASES_TSX,
        brief_digest,
        extract_brief,
        score_run,
    )
    from colleague.tracks.usecases.agency_client_reporting.protocol import (
        selftest as scorer_selftest,
    )
    from colleague.tracks.usecases.agency_client_reporting.protocol import (
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
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + "-unify-cm"

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

    # ── Boot the ConversationManager session (the arm's one door) ──────────
    from colleague.arms.sessions import build as build_session

    project = os.environ.get("ACR_PROJECT", "Benchmarks")
    print(f"[boot] orchestra={os.environ['ORCHESTRA_URL']}")
    session: Any = None
    if not check_only:
        session = build_session(
            "unify-cm",
            run_id=run_id,
            track="usecases/agency_client_reporting",
            results_dir=results_dir,
            ledger=ledger,
        )
        session.setup()
        # The phases below own the attribution; turn marks would fragment it.
        session.auto_turn_boundaries = False
        print(f"[boot] context={session.context}")

    results: dict[str, Any] = {
        "experiment": "usecases/agency_client_reporting",
        "system": "unify-cm",
        "regime": "person",
        "use_case_slug": "agency-client-reporting",
        "run_id": run_id,
        "orchestra_url": os.environ["ORCHESTRA_URL"],
        "context": session.context if session is not None else None,
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

    # ── Phase: setup (the brief, as one owner message) ──────────────────────
    # The brief arrives the way a person's would: through the CM, from the
    # owner. The CM's clarification channel is real here — the owner is right
    # there, having just sent the brief — so questions are answered, with one
    # scripted, information-free line: the brief is complete by construction,
    # and whatever the system settles on is part of what this measures.
    from colleague.tracks.standing.series.person import OWNER_CLARIFICATION_REPLY

    clarifications: list[dict[str, Any]] = []

    def _responder(question: str, who: str | None = None) -> str:
        clarifications.append({"question": question, "who": who})
        return OWNER_CLARIFICATION_REPLY

    session.on_clarification(_responder)

    print("[setup] issuing the brief ...")
    with ledger.phase("setup"):
        reply = session.send(utterance, timeout=phase_timeout_s)
        setup_status = "completed" if reply.ok else "error"
        setup_text = str(reply.text or reply.error)
        # Detached post-turn work (storage review) belongs to setup: wait for it.
        if not await ledger.wait_quiescent(
            idle_seconds=quiesce_idle_s,
            timeout_seconds=quiesce_timeout_s,
        ):
            print("[setup] warning: LLM activity still ongoing at quiesce timeout")
    print(f"[setup] {setup_status}: {setup_text[:300]}")
    results["setup"] = {"status": setup_status, "result": setup_text}
    results["clarifications"] = clarifications

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

    # What the system bound to the clock — an observation, not a gate. The
    # old regime aborted unless exactly one recurring task existed; person-
    # shaped, a system that scheduled nothing simply has nothing fire, and
    # the transcription block reports nothing eligible.
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
    activation_anchor = _activation_anchor(start_at)
    results["activation_start_at"] = start_at
    results["activation_anchor"] = activation_anchor
    if start_at:
        print(
            f"[align] task activates {start_at} (reports {activation_anchor}); "
            f"fixture booted pinned to {anchor}",
        )

    # ── Phases: monthly wakes — the harness is only the clock ──────────────
    for i in range(1, n_runs + 1):
        before_tasks = session.scheduled_recurrences()
        entrypoint_before = next(
            (t["entrypoint"] for t in before_tasks if t["entrypoint"] is not None),
            None,
        )
        regime = "entrypoint" if entrypoint_before is not None else "description"
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
        print(f"[run_{i}] the clock ticks (entrypoint before: {entrypoint_before}) ...")
        # Provider failures across this cycle, execution plus its review tail.
        # A dead call is why a client's report can come back empty on analysis
        # that never failed, so the scorer needs the count to decide whether an
        # unanswered client is a miss or unmeasurable.
        failures_before = len(ledger.failures())
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

        # Post-run reviews detach from the fire; in production the next wake
        # is a month away, so reviews always finish in between. Restore that
        # invariant and attribute the review tail to its own phase.
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
            "fired": fired,
            "entrypoint_before": entrypoint_before,
            "entrypoint_after": entrypoint_after,
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
            f"entrypoint_after={entrypoint_after}",
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

    final_tasks = session.scheduled_recurrences()
    results["task_final"] = final_tasks[0] if len(final_tasks) == 1 else None
    results["recurring_tasks_final"] = final_tasks
    final_entrypoint = next(
        (t["entrypoint"] for t in final_tasks if t["entrypoint"] is not None),
        None,
    )
    if final_entrypoint is not None:
        results["entrypoint_function"] = _function_snapshot(final_entrypoint)

    _finalize(results, ledger, results_dir, fixture)
    session.close()
    return 0


def _usd(amount: float | None) -> str:
    """Money at the precision the number actually carries."""
    if amount is None:
        return "**not measured**"
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
        return [
            "",
            "## Landing-page transcription",
            "",
            "No run completed — nothing eligible.",
        ]
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
    exec_cost = exec_phase.get("provider_cost_usd")
    review_cost = review_phase.get("provider_cost_usd")
    wall_min = float(exec_phase.get("wall_seconds") or 0.0) / 60.0
    # A phase that did real work and metered no calls is a missing measurement,
    # not a free run: the unillm hook has gone missing mid-run before. Quoting
    # its zero as a cost is how a $0.0000 reaches a page.
    exec_metered = bool(exec_phase.get("llm_calls")) and exec_cost is not None
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
            f"| cost of one client's report | {_usd(float(exec_cost) / reports)} | "
            f"run_1 ({first['regime']} regime) provider cost {_usd(float(exec_cost))} / "
            f"{reports} reports drafted |",
        )
    elif reports:
        lines.append(
            "| cost of one client's report | **not measured** | the ledger recorded "
            "no complete provider price for this phase, so its cost is missing rather than zero — "
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
        f"- setup (one-off, utterance → task): {_usd(setup_phase.get('provider_cost_usd'))}",
        f"- run_1 post-run review tail (once per cycle, not per report): {_usd(review_cost)}",
    ]
    for row in runs[1:]:
        name = f"run_{row['run']}"
        cost = by_name.get(name, {}).get("provider_cost_usd")
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
    # What the ledger itself knows about its losses: exact where the wall-clock
    # heuristic below can only guess. Non-null means some spending happened that
    # was never recorded, so no figure in this file is complete.
    results["ledger_metering_fault"] = ledger.metering_fault()
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
        f"# agency-client-reporting (unify-cm arm, person-shaped) — {results['run_id']}",
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
    if results.get("ledger_metering_fault"):
        lines += [
            "",
            f"> **Metering failed: {results['ledger_metering_fault']}.** Every "
            f"figure in the table above is incomplete by an unknown amount. "
            f"Reconstruct from `GET /v0/credits/transactions?category=llm`.",
        ]
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
