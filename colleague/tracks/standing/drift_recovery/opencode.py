"""Drift-recovery benchmark: OpenCode arm.

Identical utterance and fire protocol as the other arms, using the shared
OpenCode toolkit (isolated XDG dirs, recording proxy, pre-registered
firing rule — see ``colleague/arms/opencode.py`` for why
the harness supplies the wake).

Recovery protocol mirrors the hermes and openclaw arms: after
OPERATOR_FIX_AFTER_FAILURES consecutive failed fires, the harness plays
the realistic operator move — one natural-language message asking the
agent to investigate and fix its own automation — measured like any other
phase. Fires then continue.

Launch via run_opencode.sh.
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
from colleague.harness.ledger import PhaseLedger  # noqa: E402
from colleague.arms.opencode import (  # noqa: E402
    BENCH_MODEL,
    OPENCODE_REPO,
    arm_crontab_guard,
    defuse_host_artifacts,
    snapshot_crontab,
    WAKE_PROMPT,
    discover_commands,
    discover_scripts,
    fire_automation,
    prepare_workspace,
    require_opencode,
    run_opencode,
    scrub_state_archive,
    workspace_files,
    write_opencode_config,
)
from colleague.arms.proxy import (  # noqa: E402
    RecordingProxy,
)

OPERATOR_FIX_AFTER_FAILURES = 2

OPERATOR_FIX_MESSAGE = (
    "The hourly order-processing automation you set up has been failing on "
    "its recent runs. Please investigate and fix it so it resumes working "
    "unattended, including catching up on anything it missed. Do not ask "
    "for confirmation."
)


def _snapshot(workspace: Path) -> dict[str, Any]:
    return {
        "workspace_files": workspace_files(workspace),
        "commands": discover_commands(workspace),
        "scripts": [p.name for p in discover_scripts(workspace)],
    }


def main() -> int:
    require_opencode()

    seed = int(os.environ.get("DR_SEED", DEFAULT_SEED))
    fixture_port = int(os.environ.get("DR_PORT", DEFAULT_PORT))
    proxy_port = int(os.environ.get("DR_PROXY_PORT", "8175"))
    phase_timeout_s = float(os.environ.get("DR_PHASE_TIMEOUT_S", "1800"))
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + "-opencode"

    results_dir = EXPERIMENT_DIR / "results" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)
    state_root = results_dir / "opencode_state"
    workspace = results_dir / "workspace"
    config_path = results_dir / "opencode.json"
    log_path = results_dir / "opencode_cli.log"
    prepare_workspace(workspace)
    crontab_before = snapshot_crontab()
    arm_crontab_guard(results_dir, crontab_before)

    proxy = RecordingProxy(
        port=proxy_port,
        ledger_path=results_dir / "proxy_ledger.jsonl",
    ).start()
    fixture = DriftFixtureServer(seed=seed, port=fixture_port).start()
    print(f"[fixture] {fixture.base_url} (seed={seed})")
    print(f"[proxy] {proxy.base_url} -> openrouter.ai")

    write_opencode_config(config_path, proxy_base_url=proxy.base_url)
    ledger = PhaseLedger(results_dir / "proxy_ledger.jsonl")

    utterance = UTTERANCE_TEMPLATE.format(base_url=fixture.base_url)
    results: dict[str, Any] = {
        "experiment": "drift_recovery",
        "system": "opencode",
        "run_id": run_id,
        "opencode_repo": str(OPENCODE_REPO),
        "model": BENCH_MODEL,
        "seed": seed,
        "n_fires": N_FIRES,
        "drift_after_fire": DRIFT_AFTER_FIRE,
        "operator_fix_after_failures": OPERATOR_FIX_AFTER_FAILURES,
        "operator_fix_message": OPERATOR_FIX_MESSAGE,
        "utterance": utterance,
        "wake_prompt": WAKE_PROMPT,
        "fires": [],
    }

    try:
        print("[setup] issuing utterance to opencode ...")
        start = ledger.count()
        t0 = time.monotonic()
        code, out = run_opencode(
            ["run", utterance],
            workspace=workspace,
            state_root=state_root,
            config_path=config_path,
            log_path=log_path,
            timeout_s=phase_timeout_s,
        )
        ledger.mark("setup", start, ledger.count(), time.monotonic() - t0)
        results["setup"] = {"exit_code": code, "output_tail": out[-2000:]}
        results["profile_after_setup"] = _snapshot(workspace)
        print(f"[setup] exit={code} persisted={results['profile_after_setup']}")

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
                print("[operator_fix] issuing fix request to opencode ...")
                start = ledger.count()
                t0 = time.monotonic()
                code, _ = run_opencode(
                    ["run", OPERATOR_FIX_MESSAGE],
                    workspace=workspace,
                    state_root=state_root,
                    config_path=config_path,
                    log_path=log_path,
                    timeout_s=phase_timeout_s,
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
            fire = fire_automation(
                workspace=workspace,
                state_root=state_root,
                config_path=config_path,
                log_path=log_path,
                timeout_s=phase_timeout_s,
            )
            ledger.mark(f"fire_{i}", start, ledger.count(), time.monotonic() - t0)

            row = {
                "fire": i,
                "drifted": i > DRIFT_AFTER_FIRE,
                "fire_mode": fire["fire_mode"],
                "exit_code": fire["exit_code"],
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
                f"[fire_{i}] mode={fire['fire_mode']} "
                f"delivered={row['batches_delivered']} correct={row['correct']}",
            )

        results["profile_final"] = _snapshot(workspace)
    finally:
        results["defuse_actions"] = defuse_host_artifacts(
            results_dir,
            crontab_before,
        )
        if results["defuse_actions"]:
            print(f"[defuse] {results['defuse_actions']}")
        scrub_state_archive(state_root, workspace)
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
        f"# drift_recovery (opencode arm) — {results['run_id']}",
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
        "| fire | drifted | mode | delivered | correct |",
        "|---|---|---|---|---|",
    ]
    for r in results.get("fires", []):
        lines.append(
            f"| {r['fire']} | {r['drifted']} | {r['fire_mode']} | "
            f"{r['batches_delivered']} | {r['correct']} |",
        )
    summary = "\n".join(lines) + "\n"
    (results_dir / "summary.md").write_text(summary, encoding="utf-8")
    fixture.stop()
    proxy.stop()
    print(f"\n{summary}")
    print(f"[done] results in {results_dir}")


if __name__ == "__main__":
    sys.exit(main())
