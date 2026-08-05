"""Drift-recovery benchmark: OpenClaw arm.

Identical utterance and fire protocol as the unify and hermes arms. Reuses
the exp-1 OpenClaw machinery: throwaway ``OPENCLAW_STATE_DIR``, managed
Gateway child, model pinned via the repointed OpenRouter provider
(recording proxy), fires via ``openclaw cron run``.

Recovery protocol mirrors the hermes arm: if the automation fails
OPERATOR_FIX_AFTER_FAILURES consecutive fires, the harness plays the
realistic operator move — one natural-language message into the same agent
session asking it to investigate and fix its own automation — and measures
that session like any other phase. Fires then continue.

Launch via run_openclaw.sh.
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

from colleague.arms.openclaw import (  # noqa: E402
    BENCH_MODEL,
    OPENCLAW_REPO,
    GatewayProcess,
    cron_fire,
    cron_jobs,
    defuse_openclaw_artifacts,
    extract_json,
    run_openclaw,
    snapshot_artifacts,
    write_openclaw_config,
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
        raise SystemExit("OPENROUTER_API_KEY is required (use run_openclaw.sh)")
    if not (OPENCLAW_REPO / "dist").is_dir():
        raise SystemExit(
            f"OpenClaw build output missing — run `pnpm install && pnpm build` "
            f"in {OPENCLAW_REPO}",
        )

    seed = int(os.environ.get("DR_SEED", DEFAULT_SEED))
    fixture_port = int(os.environ.get("DR_PORT", DEFAULT_PORT))
    proxy_port = int(os.environ.get("DR_PROXY_PORT", "8159"))
    gateway_port = int(os.environ.get("OC_GATEWAY_PORT", "18936"))
    phase_timeout_s = float(os.environ.get("DR_PHASE_TIMEOUT_S", "1800"))
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
    fixture = DriftFixtureServer(seed=seed, port=fixture_port).start()
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
        "experiment": "drift_recovery",
        "system": "openclaw",
        "run_id": run_id,
        "openclaw_repo": str(OPENCLAW_REPO),
        "model": BENCH_MODEL,
        "seed": seed,
        "n_fires": N_FIRES,
        "drift_after_fire": DRIFT_AFTER_FIRE,
        "operator_fix_after_failures": OPERATOR_FIX_AFTER_FAILURES,
        "operator_fix_message": OPERATOR_FIX_MESSAGE,
        "utterance": utterance,
        "fires": [],
    }

    try:
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
        job_id = str(jobs[0].get("id"))
        print(f"[setup] cron job created: {job_id} ({jobs[0].get('name')})")

        consecutive_failures = 0
        operator_fix_done = False
        for i in range(1, N_FIRES + 1):
            if i == DRIFT_AFTER_FIRE + 1:
                fixture.stream.set_drift(True)
                print(
                    f"[drift] applied before fire {i}: "
                    "unit_price_cents -> unit_price_minor",
                )

            if (
                consecutive_failures >= OPERATOR_FIX_AFTER_FAILURES
                and not operator_fix_done
            ):
                print("[operator_fix] issuing fix request to openclaw ...")
                start = ledger.count()
                t0 = time.monotonic()
                code, _ = run_openclaw(
                    [
                        "agent",
                        "--session-id",
                        "benchmark-setup",
                        "-m",
                        OPERATOR_FIX_MESSAGE,
                        "--json",
                        "--timeout",
                        str(int(phase_timeout_s)),
                    ],
                    state_dir=state_dir,
                    gateway_port=gateway_port,
                    log_path=log_path,
                    timeout_s=phase_timeout_s + 60,
                )
                ledger.mark(
                    "operator_fix",
                    start,
                    ledger.count(),
                    time.monotonic() - t0,
                )
                results["operator_fix"] = {"exit_code": code, "before_fire": i}
                operator_fix_done = True
                print(f"[operator_fix] exit={code}")

            cursor_before, released_now, batches_before = prepare_fire(fixture)
            print(f"[fire_{i}] pending seqs {cursor_before + 1}..{released_now}")
            start = ledger.count()
            t0 = time.monotonic()
            fire = cron_fire(
                job_id,
                state_dir=state_dir,
                gateway_port=gateway_port,
                log_path=log_path,
                timeout_s=phase_timeout_s,
            )
            ledger.mark(f"fire_{i}", start, ledger.count(), time.monotonic() - t0)

            row = {
                "fire": i,
                "drifted": i > DRIFT_AFTER_FIRE,
                "fire_status": fire.get("status"),
                **score_fire(
                    fixture,
                    cursor_before=cursor_before,
                    released_now=released_now,
                    batches_before=batches_before,
                ),
            }
            results["fires"].append(row)
            consecutive_failures = 0 if row["correct"] else consecutive_failures + 1
            print(
                f"[fire_{i}] status={fire.get('status')} "
                f"delivered={row['batches_delivered']} correct={row['correct']}",
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
        f"# drift_recovery (openclaw arm) — {results['run_id']}",
        "",
        f"- model: `{results['model']}` via recording proxy -> OpenRouter",
        f"- drift after fire {results['drift_after_fire']}: "
        "`unit_price_cents -> unit_price_minor`",
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
        "| fire | drifted | delivered | correct | fire status |",
        "|---|---|---|---|---|",
    ]
    for r in results.get("fires", []):
        lines.append(
            f"| {r['fire']} | {r['drifted']} | {r['batches_delivered']} | "
            f"{r['correct']} | {r['fire_status']} |",
        )
    summary = "\n".join(lines) + "\n"
    (results_dir / "summary.md").write_text(summary, encoding="utf-8")
    fixture.stop()
    proxy.stop()
    print(f"\n{summary}")
    print(f"[done] results in {results_dir}")


if __name__ == "__main__":
    sys.exit(main())
