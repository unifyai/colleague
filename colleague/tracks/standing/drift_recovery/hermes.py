"""Drift-recovery benchmark: hermes-agent arm.

Identical utterance and fire protocol as the unify arm. Reuses the exp-1
hermes machinery: throwaway HERMES_HOME, model pinned via config +
OPENROUTER_BASE_URL recording proxy, fires via ``hermes cron run``.

Recovery protocol: hermes's zero-LLM ``no_agent`` script mode has no model
in the loop, so nothing self-heals after the API drift. After
OPERATOR_FIX_AFTER_FAILURES consecutive failed fires, the harness plays the
realistic operator move — one natural-language chat message asking hermes to
investigate and fix its own automation — and measures that session like any
other phase. Fires then continue.

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
from colleague.tracks.standing.drift_recovery.fixture import (  # noqa: E402
    DEFAULT_PORT,
    DEFAULT_SEED,
    DriftFixtureServer,
)
from colleague.tracks.standing.drift_recovery.protocol import (  # noqa: E402
    DRIFT_AFTER_FIRE,
    N_FIRES,
    UTTERANCE_TEMPLATE,
    prepare_fire,
    score_fire,
)

OPERATOR_FIX_AFTER_FAILURES = 2

OPERATOR_FIX_MESSAGE = (
    "The hourly order-processing automation you set up has been failing on "
    "its recent runs. Please investigate and fix it so it resumes working "
    "unattended, including catching up on anything it missed. Do not ask "
    "for confirmation."
)


def main() -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY is required (use run_hermes.sh)")
    if not (HERMES_REPO / ".venv" / "bin" / "hermes").exists():
        raise SystemExit(f"hermes binary missing — run `uv sync` in {HERMES_REPO}")

    seed = int(os.environ.get("DR_SEED", DEFAULT_SEED))
    fixture_port = int(os.environ.get("DR_PORT", DEFAULT_PORT))
    proxy_port = int(os.environ.get("DR_PROXY_PORT", "8126"))
    phase_timeout_s = float(os.environ.get("DR_PHASE_TIMEOUT_S", "1800"))
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
    fixture = DriftFixtureServer(seed=seed, port=fixture_port).start()
    print(f"[fixture] {fixture.base_url} (seed={seed})")
    print(f"[proxy] {proxy.base_url} -> openrouter.ai")

    (hermes_home / "config.yaml").write_text(
        CONFIG_TEMPLATE.format(model=BENCH_MODEL),
        encoding="utf-8",
    )
    ledger = PhaseLedger(results_dir / "proxy_ledger.jsonl")

    utterance = UTTERANCE_TEMPLATE.format(base_url=fixture.base_url)
    results: dict[str, Any] = {
        "experiment": "drift_recovery",
        "system": "hermes-agent",
        "run_id": run_id,
        "hermes_repo": str(HERMES_REPO),
        "model": BENCH_MODEL,
        "seed": seed,
        "n_fires": N_FIRES,
        "drift_after_fire": DRIFT_AFTER_FIRE,
        "operator_fix_after_failures": OPERATOR_FIX_AFTER_FAILURES,
        "operator_fix_message": OPERATOR_FIX_MESSAGE,
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
        _finalize(results, ledger, results_dir, fixture, proxy)
        print(f"[abort] expected exactly one cron job after setup, found {len(jobs)}")
        return 1
    job_id = str(jobs[0].get("id"))
    print(f"[setup] cron job created: {job_id} ({jobs[0].get('name')})")

    consecutive_failures = 0
    operator_fix_done = False
    for i in range(1, N_FIRES + 1):
        if i == DRIFT_AFTER_FIRE + 1:
            fixture.stream.set_drift(True)
            print(
                f"[drift] applied before fire {i}: unit_price_cents -> unit_price_minor",
            )

        if (
            consecutive_failures >= OPERATOR_FIX_AFTER_FAILURES
            and not operator_fix_done
        ):
            print("[operator_fix] issuing fix request to hermes ...")
            start = ledger.count()
            t0 = time.monotonic()
            code, tail = _run_hermes(
                ["chat", "-q", OPERATOR_FIX_MESSAGE],
                hermes_home=hermes_home,
                workdir=workdir,
                proxy_base_url=proxy.base_url,
                log_path=log_path,
                timeout_s=phase_timeout_s,
            )
            ledger.mark("operator_fix", start, ledger.count(), time.monotonic() - t0)
            results["operator_fix"] = {"exit_code": code, "before_fire": i}
            operator_fix_done = True
            print(f"[operator_fix] exit={code}")

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
            "drifted": i > DRIFT_AFTER_FIRE,
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
        consecutive_failures = 0 if row["correct"] else consecutive_failures + 1
        print(
            f"[fire_{i}] exit={code} delivered={row['batches_delivered']} "
            f"correct={row['correct']} job_status={row['job_last_status']}",
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
        f"# drift_recovery (hermes-agent arm) — {results['run_id']}",
        "",
        f"- model: `{results['model']}` via recording proxy -> OpenRouter",
        f"- drift after fire {results['drift_after_fire']}: `unit_price_cents -> unit_price_minor`",
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
        "| fire | drifted | delivered | correct | job status |",
        "|---|---|---|---|---|",
    ]
    for r in results.get("fires", []):
        lines.append(
            f"| {r['fire']} | {r['drifted']} | {r['batches_delivered']} | "
            f"{r['correct']} | {r['job_last_status']} |",
        )
    summary = "\n".join(lines) + "\n"
    (results_dir / "summary.md").write_text(summary, encoding="utf-8")
    fixture.stop()
    proxy.stop()
    print(f"\n{summary}")
    print(f"[done] results in {results_dir}")


if __name__ == "__main__":
    sys.exit(main())
