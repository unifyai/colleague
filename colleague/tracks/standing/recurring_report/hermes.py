"""Recurring weekly report benchmark: hermes-agent comparison arm.

Identical protocol to the unify driver (harness.py), applied to hermes-agent:

  - The literally identical natural-language utterance is given to the hermes
    agent as one headless chat message (``cli.py -q ...``). No manual cron
    setup, no skill authoring — the agent self-organizes, exactly as the
    unify actor did.
  - Whatever recurring automation the agent created is then fired N times
    via hermes's own manual trigger (``hermes cron run <id>``), which
    executes the job in-process exactly like a scheduler tick would.
  - The same seeded fixture serves the data and receives the reports, and
    the same ground-truth scorer grades every delivered report.

Metering is neutral: hermes's OpenAI-compatible ``base_url`` points at a
local recording proxy (openrouter_proxy.py) that forwards to OpenRouter
unchanged and records provider-reported usage per call — the same source of
truth the unify arm's in-process hook read. Model is pinned to the same
``openai/gpt-5.6-sol`` via OpenRouter.

Isolation: a throwaway ``HERMES_HOME`` under the results directory, so no
real hermes profile is touched; the agent's shell cwd is a scratch
workspace.

Launch via run_hermes.sh.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPERIMENT_DIR = Path(__file__).resolve().parent

from colleague.arms.hermes import (  # noqa: E402
    BENCH_MODEL,
    CONFIG_TEMPLATE,
    EXPERIMENT_DIR,
    HERMES_REPO,
    _load_cron_jobs,
    _run_hermes,
    _snapshot_profile_artifacts,
    defuse_hermes_artifacts,
)
from colleague.arms.proxy import (  # noqa: E402
    RecordingProxy,
)
from colleague.harness.ledger import PhaseLedger  # noqa: E402
from colleague.tracks.standing.recurring_report.fixture import (  # noqa: E402
    DEFAULT_PORT,
    DEFAULT_SEED,
    FixtureServer,
    expected_report,
    score_report,
)
from colleague.tracks.standing.recurring_report.harness import (  # noqa: E402
    UTTERANCE_TEMPLATE,
)


def main() -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY is required (use run_hermes.sh)")
    if not (HERMES_REPO / ".venv" / "bin" / "hermes").exists():
        raise SystemExit(f"hermes binary missing — run `uv sync` in {HERMES_REPO}")

    seed = int(os.environ.get("RWR_SEED", DEFAULT_SEED))
    fixture_port = int(os.environ.get("RWR_PORT", DEFAULT_PORT))
    proxy_port = int(os.environ.get("RWR_PROXY_PORT", "8124"))
    n_runs = int(os.environ.get("RWR_RUNS", "4"))
    phase_timeout_s = float(os.environ.get("RWR_PHASE_TIMEOUT_S", "1800"))
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + "-hermes"

    results_dir = EXPERIMENT_DIR / "results" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)
    hermes_home = results_dir / "hermes_home"
    hermes_home.mkdir(parents=True, exist_ok=True)
    workdir = results_dir / "workspace"
    workdir.mkdir(parents=True, exist_ok=True)
    log_path = results_dir / "hermes_cli.log"

    proxy = RecordingProxy(
        port=proxy_port,
        ledger_path=results_dir / "proxy_ledger.jsonl",
    ).start()
    fixture = FixtureServer(seed=seed, port=fixture_port).start()
    print(f"[fixture] {fixture.base_url} (seed={seed})")
    print(f"[proxy] {proxy.base_url} -> openrouter.ai")

    (hermes_home / "config.yaml").write_text(
        CONFIG_TEMPLATE.format(model=BENCH_MODEL),
        encoding="utf-8",
    )
    ledger = PhaseLedger(results_dir / "proxy_ledger.jsonl")

    utterance = UTTERANCE_TEMPLATE.format(base_url=fixture.base_url)
    results: dict[str, Any] = {
        "experiment": "recurring_weekly_report",
        "system": "hermes-agent",
        "run_id": run_id,
        "hermes_repo": str(HERMES_REPO),
        "model": BENCH_MODEL,
        "seed": seed,
        "n_runs": n_runs,
        "utterance": utterance,
        "runs": [],
    }

    # ── Phase: setup (identical utterance, one headless chat message) ──────
    print("[setup] issuing utterance to hermes ...")
    start = ledger.count()
    t0 = time.monotonic()
    code, tail = _run_hermes(
        ["chat", "-q", utterance],
        hermes_home=hermes_home,
        workdir=workdir,
        proxy_base_url=proxy.base_url,
        log_path=log_path,
        timeout_s=phase_timeout_s,
    )
    ledger.mark("setup", start, ledger.count(), time.monotonic() - t0)
    results["setup"] = {"exit_code": code, "log_tail": tail}
    print(f"[setup] exit={code}")

    jobs = _load_cron_jobs(hermes_home)
    results["profile_after_setup"] = _snapshot_profile_artifacts(hermes_home)
    if len(jobs) != 1:
        _finalize(results, ledger, results_dir, fixture, proxy)
        print(f"[abort] expected exactly one cron job after setup, found {len(jobs)}")
        return 1
    job = jobs[0]
    job_id = str(job.get("id"))
    print(f"[setup] cron job created: {job_id} ({job.get('name')})")

    # ── Phases: N manual fires of the agent-created job ────────────────────
    reports_seen = 0
    for i in range(1, n_runs + 1):
        run_date = datetime.now(timezone.utc).date()
        print(f"[run_{i}] firing cron job {job_id} ...")
        start = ledger.count()
        t0 = time.monotonic()
        code, tail = _run_hermes(
            ["cron", "run", job_id],
            hermes_home=hermes_home,
            workdir=workdir,
            proxy_base_url=proxy.base_url,
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
            "exit_code": code,
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
            f"[run_{i}] exit={code} reports={len(delivered)} correct={run_row['correct']}",
        )

    results["profile_final"] = _snapshot_profile_artifacts(hermes_home)
    results["defuse_actions"] = defuse_hermes_artifacts(hermes_home)
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
        f"# recurring_weekly_report (hermes-agent arm) — {results['run_id']}",
        "",
        f"- model: `{results['model']}` via local recording proxy -> OpenRouter",
        f"- hermes repo: `{results['hermes_repo']}`",
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
        "| run | exit | reports | correct |",
        "|---|---|---|---|",
    ]
    for r in results.get("runs", []):
        lines.append(
            f"| {r['run']} | {r['exit_code']} | {r['reports_delivered']} | {r['correct']} |",
        )
    summary = "\n".join(lines) + "\n"
    (results_dir / "summary.md").write_text(summary, encoding="utf-8")

    fixture.stop()
    proxy.stop()
    print(f"\n{summary}")
    print(f"[done] results in {results_dir}")


if __name__ == "__main__":
    sys.exit(main())
