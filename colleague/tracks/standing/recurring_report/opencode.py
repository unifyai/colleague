"""Recurring weekly report benchmark: OpenCode comparison arm.

Same protocol as the unify / hermes / openclaw drivers, with one
structural difference that has to be stated up front because it changes
what "firing" means.

**OpenCode ships no scheduler.** There is no cron surface, so the agent
cannot register a recurring job the way the other three arms do; something
outside it has to supply the wake. The harness therefore plays the
scheduler, executing whatever the agent itself declared, in this
precedence:

  1. If the agent wrote a **crontab spec** into the workspace, run the
     command that spec names. This is the agent stating outright what
     should run on a schedule, and is the direct analogue of reading a job
     row out of hermes's or openclaw's cron store.
  2. Else, if it declared a **custom command** (`.opencode/command*/*.md`
     — OpenCode's named-invocable-prompt mechanism), fire it with
     ``opencode run --command <name>``.
  3. Else, if it left exactly one **runnable script** (`*.py` / `*.sh` at
     the workspace root, under `scripts/`, or under `.opencode/`), execute
     that directly — the zero-token path, matching how the hermes arm's
     ``no_agent`` script is fired.
  4. Else, fire a fixed neutral wake prompt (``WAKE_PROMPT``), which is
     what a scheduler with nothing declared would have to do.

Rules 2-4 were fixed before any run. Rule 1 was added after the first
triage runs showed the agent declaring its automation in a `.cron` file
that rules 2-3 could not see — a gap in the harness, not a property of
the system under test. The revision moves strictly toward executing the
agent's own declaration rather than a harness guess, and every experiment
in this arm is run under it.

Which rule fired is recorded per fire in ``results.json`` as
``fire_mode``, so the report can never quietly depend on the choice.
Fires use a fresh session (no ``--continue``), because a scheduler wake
carries no conversation — the same way the other arms' isolated cron
sessions start cold. Whatever the agent persisted into the workspace is
therefore the only thing carried between fires, which is exactly the
property under test.

Metering is neutral: the OpenRouter provider's ``baseURL`` is repointed at
the local recording proxy. Both ``model`` and ``small_model`` are pinned to
``openai/gpt-5.6-sol`` — OpenCode otherwise picks a cheaper model for
title generation, which would leave part of its real cost on a different
provider and off the comparison.

Isolation: per-run XDG dirs (``XDG_{DATA,CACHE,CONFIG,STATE}_HOME``) plus a
fresh git-initialised workspace, so the real ``~/.local/share/opencode``
profile is never read or written.

This module doubles as the shared OpenCode toolkit for the other
experiments' drivers.

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

from colleague.arms.opencode import (  # noqa: E402
    BENCH_MODEL,
    EXPERIMENT_DIR,
    OPENCODE_REPO,
    WAKE_PROMPT,
    arm_crontab_guard,
    defuse_host_artifacts,
    discover_commands,
    discover_scripts,
    fire_automation,
    prepare_workspace,
    require_opencode,
    run_opencode,
    scrub_state_archive,
    snapshot_crontab,
    workspace_files,
    write_opencode_config,
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
    require_opencode()

    seed = int(os.environ.get("RWR_SEED", DEFAULT_SEED))
    fixture_port = int(os.environ.get("RWR_PORT", DEFAULT_PORT))
    proxy_port = int(os.environ.get("RWR_PROXY_PORT", "8174"))
    n_runs = int(os.environ.get("RWR_RUNS", "4"))
    phase_timeout_s = float(os.environ.get("RWR_PHASE_TIMEOUT_S", "1800"))
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
    fixture = FixtureServer(seed=seed, port=fixture_port).start()
    print(f"[fixture] {fixture.base_url} (seed={seed})")
    print(f"[proxy] {proxy.base_url} -> openrouter.ai")

    write_opencode_config(config_path, proxy_base_url=proxy.base_url)
    ledger = PhaseLedger(results_dir / "proxy_ledger.jsonl")

    utterance = UTTERANCE_TEMPLATE.format(base_url=fixture.base_url)
    results: dict[str, Any] = {
        "experiment": "recurring_weekly_report",
        "system": "opencode",
        "run_id": run_id,
        "opencode_repo": str(OPENCODE_REPO),
        "model": BENCH_MODEL,
        "seed": seed,
        "n_runs": n_runs,
        "utterance": utterance,
        "wake_prompt": WAKE_PROMPT,
        "runs": [],
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
        print(f"[setup] exit={code}")

        results["profile_after_setup"] = {
            "workspace_files": workspace_files(workspace),
            "commands": discover_commands(workspace),
            "scripts": [p.name for p in discover_scripts(workspace)],
        }
        print(f"[setup] persisted: {results['profile_after_setup']}")

        reports_seen = 0
        for i in range(1, n_runs + 1):
            run_date = datetime.now(timezone.utc).date()
            print(f"[run_{i}] firing ...")
            start = ledger.count()
            t0 = time.monotonic()
            fire = fire_automation(
                workspace=workspace,
                state_root=state_root,
                config_path=config_path,
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
                "fire_mode": fire["fire_mode"],
                "exit_code": fire["exit_code"],
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

        results["profile_final"] = {
            "workspace_files": workspace_files(workspace),
            "commands": discover_commands(workspace),
            "scripts": [p.name for p in discover_scripts(workspace)],
        }
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
        f"# recurring_weekly_report (opencode arm) — {results['run_id']}",
        "",
        f"- model: `{results['model']}` via local recording proxy -> OpenRouter",
        f"- opencode repo: `{results['opencode_repo']}`",
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
