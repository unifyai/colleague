"""Semantic triage benchmark: OpenCode arm.

Identical utterance and fire protocol as the other arms, using the shared
OpenCode toolkit (isolated XDG dirs, recording proxy, pre-registered
firing rule — see ``colleague/arms/opencode.py``). No
drift, no operator intervention: the measurement is the steady-state
per-fire cost and accuracy of whatever the agent persisted for recurring
work with a judgment substep.

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


def _snapshot(workspace: Path) -> dict[str, Any]:
    return {
        "workspace_files": workspace_files(workspace),
        "commands": discover_commands(workspace),
        "scripts": [p.name for p in discover_scripts(workspace)],
    }


def main() -> int:
    require_opencode()

    seed = int(os.environ.get("ST_SEED", DEFAULT_SEED))
    fixture_port = int(os.environ.get("ST_PORT", DEFAULT_PORT))
    proxy_port = int(os.environ.get("ST_PROXY_PORT", "8176"))
    n_fires = int(os.environ.get("ST_FIRES", N_FIRES))
    phase_timeout_s = float(os.environ.get("ST_PHASE_TIMEOUT_S", "1800"))
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
    fixture = TriageFixtureServer(seed=seed, port=fixture_port).start()
    print(f"[fixture] {fixture.base_url} (seed={seed})")
    print(f"[proxy] {proxy.base_url} -> openrouter.ai")

    write_opencode_config(config_path, proxy_base_url=proxy.base_url)
    ledger = PhaseLedger(results_dir / "proxy_ledger.jsonl")

    utterance = UTTERANCE_TEMPLATE.format(base_url=fixture.base_url)
    results: dict[str, Any] = {
        "experiment": "semantic_triage",
        "system": "opencode",
        "run_id": run_id,
        "opencode_repo": str(OPENCODE_REPO),
        "model": BENCH_MODEL,
        "seed": seed,
        "n_fires": n_fires,
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

        for i in range(1, n_fires + 1):
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
            print(
                f"[fire_{i}] mode={fire['fire_mode']} "
                f"delivered={row['batches_delivered']} correct={row['correct']} "
                f"accuracy={row.get('accuracy')}",
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
        f"# semantic_triage (opencode arm) — {results['run_id']}",
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
        "| fire | mode | delivered | correct | accuracy |",
        "|---|---|---|---|---|",
    ]
    for r in results.get("fires", []):
        lines.append(
            f"| {r['fire']} | {r['fire_mode']} | {r['batches_delivered']} | "
            f"{r['correct']} | {r.get('accuracy')} |",
        )
    summary = "\n".join(lines) + "\n"
    (results_dir / "summary.md").write_text(summary, encoding="utf-8")
    fixture.stop()
    proxy.stop()
    print(f"\n{summary}")
    print(f"[done] results in {results_dir}")


if __name__ == "__main__":
    sys.exit(main())
