"""Recurring weekly report benchmark: OpenClaw comparison arm.

Identical protocol to the unify and hermes drivers, applied to OpenClaw:

  - The literally identical natural-language utterance is delivered as one
    headless agent turn (``openclaw agent -m ...``). No manual cron setup —
    the agent self-organizes with its own cron tool.
  - Whatever recurring automation the agent created is then fired N times
    via OpenClaw's own manual trigger (``openclaw cron run <id>``), executed
    by the same Gateway scheduler a production deployment would use.
  - The same seeded fixture serves the data and receives the reports, and
    the same ground-truth scorer grades every delivered report.

Metering is neutral: the OpenRouter provider's ``baseUrl`` is repointed at
the local recording proxy (openrouter_proxy.py), which forwards to
OpenRouter unchanged and records provider-reported usage per call. Model is
pinned to the same ``openai/gpt-5.6-sol``.

Isolation: a throwaway ``OPENCLAW_STATE_DIR`` under the results directory
(config, cron store, sessions, workspace all live inside it), a dedicated
Gateway port, and no channels configured — the real ``~/.openclaw`` profile
is never read or written. The Gateway runs as a managed child process for
exactly the duration of the run; ``defuse_openclaw_artifacts`` disables
every cron job, stops the Gateway, and sweeps for any daemon artifacts
before the results directory is committed.

This module doubles as the shared OpenClaw toolkit for the other
experiments' drivers (config template, gateway lifecycle, CLI helpers).

Launch via run_openclaw.sh.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPERIMENT_DIR = Path(__file__).resolve().parent

from colleague.tracks.standing.recurring_report.fixture import (  # noqa: E402
    DEFAULT_PORT,
    DEFAULT_SEED,
    FixtureServer,
    expected_report,
    score_report,
)
from colleague.tracks.standing.recurring_report.harness import (
    UTTERANCE_TEMPLATE,
)  # noqa: E402
from colleague.harness.ledger import PhaseLedger  # noqa: E402
from colleague.arms.proxy import (  # noqa: E402
    RecordingProxy,
)

from colleague.arms.openclaw import (  # noqa: E402
    BENCH_MODEL,
    EXPERIMENT_DIR,
    GatewayProcess,
    OPENCLAW_REPO,
    cron_fire,
    cron_jobs,
    defuse_openclaw_artifacts,
    extract_json,
    run_openclaw,
    snapshot_artifacts,
    write_openclaw_config,
)


def main() -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY is required (use run_openclaw.sh)")
    if not (OPENCLAW_REPO / "dist").is_dir():
        raise SystemExit(
            f"OpenClaw build output missing — run `pnpm install && pnpm build` "
            f"in {OPENCLAW_REPO}",
        )

    seed = int(os.environ.get("RWR_SEED", DEFAULT_SEED))
    fixture_port = int(os.environ.get("RWR_PORT", DEFAULT_PORT))
    proxy_port = int(os.environ.get("RWR_PROXY_PORT", "8154"))
    gateway_port = int(os.environ.get("OC_GATEWAY_PORT", "18931"))
    n_runs = int(os.environ.get("RWR_RUNS", "4"))
    phase_timeout_s = float(os.environ.get("RWR_PHASE_TIMEOUT_S", "1800"))
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + "-openclaw"

    results_dir = EXPERIMENT_DIR / "results" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)
    state_dir = results_dir / "openclaw_state"
    workspace = results_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    log_path = results_dir / "openclaw_cli.log"

    proxy = RecordingProxy(
        port=proxy_port,
        ledger_path=results_dir / "proxy_ledger.jsonl",
    ).start()
    fixture = FixtureServer(seed=seed, port=fixture_port).start()
    print(f"[fixture] {fixture.base_url} (seed={seed})")
    print(f"[proxy] {proxy.base_url} -> openrouter.ai")

    write_openclaw_config(
        state_dir,
        proxy_base_url=proxy.base_url,
        workspace=workspace,
    )
    ledger = PhaseLedger(results_dir / "proxy_ledger.jsonl")

    gateway = GatewayProcess(
        state_dir=state_dir,
        gateway_port=gateway_port,
        log_path=results_dir / "gateway.log",
    ).start()
    print(f"[gateway] up on port {gateway_port}")

    utterance = UTTERANCE_TEMPLATE.format(base_url=fixture.base_url)
    results: dict[str, Any] = {
        "experiment": "recurring_weekly_report",
        "system": "openclaw",
        "run_id": run_id,
        "openclaw_repo": str(OPENCLAW_REPO),
        "model": BENCH_MODEL,
        "seed": seed,
        "n_runs": n_runs,
        "utterance": utterance,
        "runs": [],
    }

    try:
        # ── Phase: setup (identical utterance, one headless agent turn) ────
        print("[setup] issuing utterance to openclaw ...")
        start = ledger.count()
        t0 = time.monotonic()
        code, out = run_openclaw(
            [
                "agent",
                "--session-id",
                "benchmark-setup",
                "-m",
                utterance,
                "--json",
                "--timeout",
                str(int(phase_timeout_s)),
            ],
            state_dir=state_dir,
            gateway_port=gateway_port,
            log_path=log_path,
            timeout_s=phase_timeout_s + 60,
        )
        ledger.mark("setup", start, ledger.count(), time.monotonic() - t0)
        payload = extract_json(out)
        results["setup"] = {
            "exit_code": code,
            "final_text": (
                (payload or {}).get("result", {}).get("finalAssistantVisibleText")
                if isinstance(payload, dict)
                else None
            ),
        }
        print(f"[setup] exit={code}")

        jobs = cron_jobs(state_dir, gateway_port, log_path)
        results["profile_after_setup"] = snapshot_artifacts(
            state_dir,
            workspace,
            gateway_port,
            log_path,
        )
        if len(jobs) != 1:
            print(
                f"[abort] expected exactly one cron job after setup, found {len(jobs)}",
            )
            return 1
        job = jobs[0]
        job_id = str(job.get("id"))
        print(f"[setup] cron job created: {job_id} ({job.get('name')})")

        # ── Phases: N manual fires of the agent-created job ────────────────
        reports_seen = 0
        for i in range(1, n_runs + 1):
            run_date = datetime.now(timezone.utc).date()
            print(f"[run_{i}] firing cron job {job_id} ...")
            start = ledger.count()
            t0 = time.monotonic()
            fire = cron_fire(
                job_id,
                state_dir=state_dir,
                gateway_port=gateway_port,
                log_path=log_path,
                timeout_s=phase_timeout_s,
            )
            ledger.mark(f"run_{i}", start, ledger.count(), time.monotonic() - t0)

            delivered = fixture.sink.snapshot()[reports_seen:]
            reports_seen += len(delivered)
            expected = expected_report(seed, run_date)
            scores = [score_report(r["body"], expected) for r in delivered]
            run_row = {
                "run": i,
                "run_date": run_date.isoformat(),
                "fire_status": fire.get("status"),
                "reports_delivered": len(delivered),
                "reports": [r["body"] for r in delivered],
                "expected_report": expected,
                "scores": scores,
                "correct": (
                    len(delivered) == 1 and scores[0]["correct"] if scores else False
                ),
            }
            results["runs"].append(run_row)
            print(
                f"[run_{i}] status={fire.get('status')} reports={len(delivered)} "
                f"correct={run_row['correct']}",
            )

        results["profile_final"] = snapshot_artifacts(
            state_dir,
            workspace,
            gateway_port,
            log_path,
        )
    finally:
        results["defuse_actions"] = defuse_openclaw_artifacts(
            state_dir,
            gateway,
            gateway_port,
            log_path,
        )
        _finalize(results, ledger, results_dir, fixture, proxy)
    return 0


def _finalize(
    results: dict[str, Any],
    ledger: PhaseLedger,
    results_dir: Path,
    fixture: Any,
    proxy: Any,
) -> None:
    results["phases"] = ledger.summarize()
    results["finished_at"] = datetime.now(timezone.utc).isoformat()
    with open(results_dir / "results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    lines = [
        f"# recurring_weekly_report (openclaw arm) — {results['run_id']}",
        "",
        f"- model: `{results['model']}` via local recording proxy -> OpenRouter",
        f"- openclaw repo: `{results['openclaw_repo']}`",
        "",
        "| phase | LLM calls | prompt tok | completion tok | usage-missing | wall (s) |",
        "|---|---|---|---|---|---|",
    ]
    for p in results["phases"]:
        lines.append(
            f"| {p['name']} | {p['llm_calls']} | {p['prompt_tokens']} | "
            f"{p['completion_tokens']} | {p['usage_missing_calls']} | {p['wall_seconds']} |",
        )
    lines += [
        "",
        "| run | fire status | reports | correct |",
        "|---|---|---|---|",
    ]
    for r in results.get("runs", []):
        lines.append(
            f"| {r['run']} | {r['fire_status']} | {r['reports_delivered']} | "
            f"{r['correct']} |",
        )
    summary = "\n".join(lines) + "\n"
    (results_dir / "summary.md").write_text(summary, encoding="utf-8")

    fixture.stop()
    proxy.stop()
    print(f"\n{summary}")
    print(f"[done] results in {results_dir}")


if __name__ == "__main__":
    sys.exit(main())
