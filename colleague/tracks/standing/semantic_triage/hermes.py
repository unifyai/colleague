"""Semantic triage benchmark: hermes-agent arm.

Identical utterance and fire protocol as the unify arm; same machinery as
the drift_recovery hermes driver (throwaway HERMES_HOME, recording proxy,
``hermes cron run`` fires, artifact defusing at finalize). No drift, no
operator intervention — the measurement is the steady-state per-fire cost
and accuracy of whatever the agent converges to for recurring work with a
judgment substep. A ``no_agent`` script cannot classify language, so the
natural outcomes are either a full agent boot per fire or an agent-authored
script that calls a model API directly; both are legitimate results and the
proxy meters either.

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
from colleague.tracks.standing.semantic_triage.fixture import (  # noqa: E402
    DEFAULT_PORT,
    DEFAULT_SEED,
    TriageFixtureServer,
)
from colleague.tracks.standing.semantic_triage.protocol import (  # noqa: E402
    N_FIRES,
    UTTERANCE_TEMPLATE,
    prepare_fire,
    score_fire,
)


def main() -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY is required (use run_hermes.sh)")
    if not (HERMES_REPO / ".venv" / "bin" / "hermes").exists():
        raise SystemExit(f"hermes binary missing — run `uv sync` in {HERMES_REPO}")

    seed = int(os.environ.get("ST_SEED", DEFAULT_SEED))
    fixture_port = int(os.environ.get("ST_PORT", DEFAULT_PORT))
    proxy_port = int(os.environ.get("ST_PROXY_PORT", "8131"))
    phase_timeout_s = float(os.environ.get("ST_PHASE_TIMEOUT_S", "1800"))
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
    fixture = TriageFixtureServer(seed=seed, port=fixture_port).start()
    print(f"[fixture] {fixture.base_url} (seed={seed})")
    print(f"[proxy] {proxy.base_url} -> openrouter.ai")

    (hermes_home / "config.yaml").write_text(
        CONFIG_TEMPLATE.format(model=BENCH_MODEL),
        encoding="utf-8",
    )
    ledger = PhaseLedger(results_dir / "proxy_ledger.jsonl")

    utterance = UTTERANCE_TEMPLATE.format(base_url=fixture.base_url)
    results: dict[str, Any] = {
        "experiment": "semantic_triage",
        "system": "hermes-agent",
        "run_id": run_id,
        "hermes_repo": str(HERMES_REPO),
        "model": BENCH_MODEL,
        "seed": seed,
        "n_fires": N_FIRES,
        "utterance": utterance,
        "fires": [],
    }

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
        results["defuse_actions"] = defuse_hermes_artifacts(hermes_home)
        _finalize(results, ledger, results_dir, fixture, proxy)
        print(f"[abort] expected exactly one cron job after setup, found {len(jobs)}")
        return 1
    job_id = str(jobs[0].get("id"))
    print(f"[setup] cron job created: {job_id} ({jobs[0].get('name')})")

    for i in range(1, N_FIRES + 1):
        cursor_before, released_now, batches_before = prepare_fire(fixture)
        print(f"[fire_{i}] pending seqs {cursor_before + 1}..{released_now}")
        start = ledger.count()
        t0 = time.monotonic()
        code, _ = _run_hermes(
            ["cron", "run", job_id],
            hermes_home=hermes_home,
            workdir=workdir,
            proxy_base_url=proxy.base_url,
            log_path=log_path,
            timeout_s=phase_timeout_s,
        )
        ledger.mark(f"fire_{i}", start, ledger.count(), time.monotonic() - t0)

        row = {
            "fire": i,
            "exit_code": code,
            **score_fire(
                fixture,
                cursor_before=cursor_before,
                released_now=released_now,
                batches_before=batches_before,
            ),
        }
        jobs_now = _load_cron_jobs(hermes_home)
        row["job_last_status"] = jobs_now[0].get("last_status") if jobs_now else None
        results["fires"].append(row)
        print(
            f"[fire_{i}] exit={code} delivered={row['batches_delivered']} "
            f"correct={row['correct']} accuracy={row['accuracy']} "
            f"job_status={row['job_last_status']}",
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
        f"# semantic_triage (hermes-agent arm) — {results['run_id']}",
        "",
        f"- model: `{results['model']}` via recording proxy -> OpenRouter",
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
        "| fire | delivered | contract | accuracy | job status |",
        "|---|---|---|---|---|",
    ]
    for r in results.get("fires", []):
        lines.append(
            f"| {r['fire']} | {r['batches_delivered']} | {r['correct']} | "
            f"{r['accuracy']} | {r['job_last_status']} |",
        )
    summary = "\n".join(lines) + "\n"
    (results_dir / "summary.md").write_text(summary, encoding="utf-8")
    fixture.stop()
    proxy.stop()
    print(f"\n{summary}")
    print(f"[done] results in {results_dir}")


if __name__ == "__main__":
    sys.exit(main())
