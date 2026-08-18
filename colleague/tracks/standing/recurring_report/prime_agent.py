"""Recurring weekly report benchmark: prime-agent arm.

Identical utterance and fire protocol as the other arms, on the shared
prime-agent arm of the fire-series engine (`PrimeAgentArm` in
``colleague/tracks/standing/series/cli_arms.py``). The structural difference
from the opencode arm has to be stated up front because it changes what a
fire costs: prime-agent's scheduler is real, but every job payload is a
prompt delivered into the job's own resident session, so the arm keeps one
long-lived RPC session across setup and every fire — the persistent IPython
kernel and anything the agent wrote are what its own daemon session would
keep. There is no cold-session zero-token path unless the agent leaves a
crontab spec or a script; the firing precedence is stated in the arm class's
docstring, and which rule fired is recorded per fire as ``fire_mode``.

Metering is neutral: the provider's base URL is repointed at the local
recording proxy, so the token column is the product's real OpenRouter
traffic.

Launch via run_prime_agent.sh.
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

from colleague.arms.proxy import RecordingProxy  # noqa: E402
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
from colleague.tracks.standing.series.cli_arms import PrimeAgentArm  # noqa: E402


def main() -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY is required (use run_prime_agent.sh)")
    seed = int(os.environ.get("RWR_SEED", DEFAULT_SEED))
    fixture_port = int(os.environ.get("RWR_PORT", DEFAULT_PORT))
    proxy_port = int(os.environ.get("RWR_PROXY_PORT", "8183"))
    n_runs = int(os.environ.get("RWR_RUNS", "4"))
    phase_timeout_s = float(os.environ.get("RWR_PHASE_TIMEOUT_S", "1800"))
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + "-prime-agent"

    results_dir = EXPERIMENT_DIR / "results" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    proxy = RecordingProxy(
        port=proxy_port,
        ledger_path=results_dir / "proxy_ledger.jsonl",
    ).start()
    fixture = FixtureServer(seed=seed, port=fixture_port).start()
    print(f"[fixture] {fixture.base_url} (seed={seed})")
    print(f"[proxy] {proxy.base_url} -> openrouter.ai")
    ledger = PhaseLedger(results_dir / "proxy_ledger.jsonl")
    arm = PrimeAgentArm(
        results_dir=results_dir,
        proxy_base_url=proxy.base_url,
        timeout_s=phase_timeout_s,
    )

    utterance = UTTERANCE_TEMPLATE.format(base_url=fixture.base_url)
    results: dict[str, Any] = {
        "experiment": "recurring_weekly_report",
        "system": "prime-agent",
        "run_id": run_id,
        **arm.describe(),
        "seed": seed,
        "n_runs": n_runs,
        "utterance": utterance,
        "runs": [],
    }

    def _phase(name: str, fn):
        start = ledger.count()
        t0 = time.monotonic()
        out = fn()
        ledger.mark(name, start, ledger.count(), time.monotonic() - t0)
        return out

    try:
        arm.start()
        print("[setup] issuing utterance to prime-agent ...")
        results["setup"] = _phase("setup", lambda: arm.setup(utterance))
        results["profile_after_setup"] = arm.snapshot()
        print(
            f"[setup] exit={results['setup'].get('exit_code')} "
            f"persisted={results['profile_after_setup']}",
        )

        reports_seen = 0
        for i in range(1, n_runs + 1):
            run_date = datetime.now(timezone.utc).date()
            print(f"[run_{i}] firing ...")
            fire = _phase(f"run_{i}", arm.fire)
            delivered = fixture.sink.snapshot()[reports_seen:]
            reports_seen += len(delivered)
            expected = expected_report(seed, run_date)
            scores = [score_report(r["body"], expected) for r in delivered]
            run_row = {
                "run": i,
                "run_date": run_date.isoformat(),
                "fire_mode": fire["fire_mode"],
                "exit_code": fire.get("exit_code"),
                "agent_runs": fire.get("agent_runs"),
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
                f"[run_{i}] mode={fire['fire_mode']} reports={len(delivered)} "
                f"correct={run_row['correct']}",
            )

        results["profile_final"] = arm.snapshot()
    finally:
        results["defuse_actions"] = arm.defuse()
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
        f"# recurring_weekly_report (prime-agent arm) — {results['run_id']}",
        "",
        f"- model: `{results['model']}` via local recording proxy -> OpenRouter",
        f"- prime-agent repo: `{results['prime_agent_repo']}`",
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
        "| run | fire mode | reports | correct |",
        "|---|---|---|---|",
    ]
    for r in results.get("runs", []):
        lines.append(
            f"| {r['run']} | {r['fire_mode']} | {r['reports_delivered']} | "
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
