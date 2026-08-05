"""Policy propagation benchmark: OpenCode arm.

Identical protocol to the other arms: three separate automation requests
over one inquiry stream, PRE_CHANGE_ROUNDS rounds of fires, one
natural-language policy update, POST_CHANGE_ROUNDS more rounds. Uses the
shared OpenCode toolkit (isolated XDG dirs, recording proxy,
pre-registered firing rule — see
``colleague/arms/opencode.py``).

The three automations share one workspace, because that is what a user
would have: three requests into the same project. Each automation is
fired by name — the firing rule resolves per-automation custom commands
when the agent declared them, so ``fire_mode`` records exactly what was
executed for each.

Change attribution: every workspace file is hashed before and after the
policy-change session, so the results record which artifacts the agent
touched to propagate the new threshold.

Launch via run_opencode.sh.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPERIMENT_DIR = Path(__file__).resolve().parent

from colleague.arms.opencode import (  # noqa: E402
    BENCH_MODEL,
    OPENCODE_REPO,
    WAKE_PROMPT,
    arm_crontab_guard,
    defuse_host_artifacts,
    discover_commands,
    discover_scripts,
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
from colleague.tracks.standing.policy_propagation.fixture import (  # noqa: E402
    DEFAULT_PORT,
    DEFAULT_SEED,
    INITIAL_THRESHOLD,
    POLICY_UPDATE_MESSAGE,
    UPDATED_THRESHOLD,
    PolicyFixtureServer,
)
from colleague.tracks.standing.policy_propagation.protocol import (  # noqa: E402
    AUTOMATIONS,
    POST_CHANGE_ROUNDS,
    PRE_CHANGE_ROUNDS,
    build_utterance,
    prepare_fire,
    release_round,
    score_fire,
)


def _declared_for(workspace: Path, automation: str) -> list[str]:
    """Artifacts that genuinely implement this automation.

    Name matching is not enough: a run was observed where the command
    named `triage-support` read and posted to the *digests* sink, so the
    triage automation did not exist while appearing to. The check is
    therefore on content — the artifact must reference this automation's
    own sink endpoint (`/triage`, `/digests`, `/audits`) — and the caller
    additionally requires the three automations to be disjoint.
    """
    endpoint = f"/{automation}"
    key = automation[:5]
    found: list[str] = []
    for name in discover_commands(workspace):
        for sub in ("command", "commands"):
            f = workspace / ".opencode" / sub / f"{name}.md"
            if f.is_file() and endpoint in f.read_text(errors="replace"):
                found.append(f"command:{name}")
    for p in discover_scripts(workspace):
        if endpoint in p.read_text(errors="replace") and key in p.name.lower():
            found.append(f"script:{p.name}")
    return sorted(set(found))


def _artifact_shas(workspace: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in workspace_files(workspace):
        out[rel] = hashlib.sha256(
            (workspace / rel).read_bytes(),
        ).hexdigest()[:12]
    return out


def _fire_named(
    automation: str,
    *,
    workspace: Path,
    state_root: Path,
    config_path: Path,
    log_path: Path,
    timeout_s: float,
) -> dict[str, Any]:
    """Fire one automation, resolving its own declared artifact by name.

    Same pre-registered precedence as the shared rule (command, then a
    single script, then the neutral wake), but matched to this automation
    so a three-automation workspace fires the right one.
    """
    # Resolve by content, not by name: the setup gate validates which
    # artifact implements this automation's sink, and firing must agree
    # with it or a fire consumes a sibling's pending range.
    declared = _declared_for(workspace, automation)
    commands = [d.split(":", 1)[1] for d in declared if d.startswith("command:")]
    if commands:
        code, out = run_opencode(
            ["run", "--command", commands[0]],
            workspace=workspace,
            state_root=state_root,
            config_path=config_path,
            log_path=log_path,
            timeout_s=timeout_s,
        )
        return {
            "fire_mode": f"command:{commands[0]}",
            "exit_code": code,
            "output_tail": out[-1000:],
        }

    script_names = {d.split(":", 1)[1] for d in declared if d.startswith("script:")}
    scripts = [p for p in discover_scripts(workspace) if p.name in script_names]
    if len(scripts) == 1:
        script = scripts[0]
        runner = (
            ["python3", str(script)]
            if script.suffix == ".py"
            else [
                "bash",
                str(script),
            ]
        )
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"\n===== script fire {script.name} ({automation})\n")
            proc = subprocess.run(
                runner,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout_s,
            )
            log.write(proc.stdout)
            log.write(proc.stderr)
        return {
            "fire_mode": f"script:{script.name}",
            "exit_code": proc.returncode,
            "output_tail": proc.stdout[-1000:],
        }

    code, out = run_opencode(
        ["run", f"{WAKE_PROMPT} Run the {automation} automation."],
        workspace=workspace,
        state_root=state_root,
        config_path=config_path,
        log_path=log_path,
        timeout_s=timeout_s,
    )
    return {
        "fire_mode": "wake_prompt",
        "exit_code": code,
        "output_tail": out[-1000:],
    }


def main() -> int:
    require_opencode()

    seed = int(os.environ.get("PP_SEED", DEFAULT_SEED))
    fixture_port = int(os.environ.get("PP_PORT", DEFAULT_PORT))
    proxy_port = int(os.environ.get("PP_PROXY_PORT", "8177"))
    phase_timeout_s = float(os.environ.get("PP_PHASE_TIMEOUT_S", "1800"))
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
    fixture = PolicyFixtureServer(seed=seed, port=fixture_port).start()
    print(f"[fixture] {fixture.base_url} (seed={seed})")
    print(f"[proxy] {proxy.base_url} -> openrouter.ai")

    write_opencode_config(config_path, proxy_base_url=proxy.base_url)
    ledger = PhaseLedger(results_dir / "proxy_ledger.jsonl")

    results: dict[str, Any] = {
        "experiment": "policy_propagation",
        "system": "opencode",
        "run_id": run_id,
        "opencode_repo": str(OPENCODE_REPO),
        "model": BENCH_MODEL,
        "seed": seed,
        "automations": list(AUTOMATIONS),
        "pre_change_rounds": PRE_CHANGE_ROUNDS,
        "post_change_rounds": POST_CHANGE_ROUNDS,
        "initial_threshold": INITIAL_THRESHOLD,
        "updated_threshold": UPDATED_THRESHOLD,
        "policy_update_message": POLICY_UPDATE_MESSAGE,
        "utterances": {a: build_utterance(a, fixture.base_url) for a in AUTOMATIONS},
        "fires": [],
    }

    try:
        for automation in AUTOMATIONS:
            print(f"[setup_{automation}] issuing utterance to opencode ...")
            start = ledger.count()
            t0 = time.monotonic()
            code, _ = run_opencode(
                ["run", build_utterance(automation, fixture.base_url)],
                workspace=workspace,
                state_root=state_root,
                config_path=config_path,
                log_path=log_path,
                timeout_s=phase_timeout_s,
            )
            ledger.mark(
                f"setup_{automation}",
                start,
                ledger.count(),
                time.monotonic() - t0,
            )
            results[f"setup_{automation}"] = {"exit_code": code}
            # Every arm's driver aborts when a setup fails to register its
            # automation. OpenCode's setup is bimodal, and a missing
            # automation does not just cost its own fires: the wake-prompt
            # fallback sends an agent into a shared workspace where it finds
            # and runs a *sibling* automation, consuming that sibling's
            # pending range before the sibling's own fire is scored. One
            # missing automation therefore corrupts two. Fail fast instead.
            declared = _declared_for(workspace, automation)
            results[f"setup_{automation}"]["declared"] = declared
            # Automations must also be disjoint: one artifact cannot serve
            # as two automations, or a fire for one consumes the other's
            # pending range and both score zero.
            claimed = {
                art
                for other in AUTOMATIONS
                if other != automation
                for art in results.get(f"setup_{other}", {}).get("declared", [])
            }
            if set(declared) & claimed:
                results["aborted"] = (
                    f"setup_{automation} reused another automation's artifact "
                    f"{sorted(set(declared) & claimed)}; rerun required"
                )
                print(f"[abort] setup_{automation} collided with a sibling")
                return 2
            if code != 0 or not declared:
                results["aborted"] = (
                    f"setup_{automation} produced no automation "
                    f"(exit {code}); rerun required"
                )
                print(f"[abort] setup_{automation} declared nothing — {declared}")
                return 2
            print(f"[setup_{automation}] exit={code} declared={declared}")
        results["profile_after_setup"] = {
            "workspace_files": workspace_files(workspace),
            "commands": discover_commands(workspace),
            "scripts": [p.name for p in discover_scripts(workspace)],
        }
        print(f"[setup] persisted: {results['profile_after_setup']}")

        def fire(automation: str, round_no: int, threshold: int) -> None:
            cursor_before, released_now, batches_before = prepare_fire(
                fixture,
                automation,
            )
            label = f"round{round_no}_{automation}"
            print(f"[fire_{label}] pending {cursor_before + 1}..{released_now}")
            start = ledger.count()
            t0 = time.monotonic()
            outcome = _fire_named(
                automation,
                workspace=workspace,
                state_root=state_root,
                config_path=config_path,
                log_path=log_path,
                timeout_s=phase_timeout_s,
            )
            ledger.mark(f"fire_{label}", start, ledger.count(), time.monotonic() - t0)
            row = {
                "round": round_no,
                "automation": automation,
                "threshold": threshold,
                "fire_mode": outcome["fire_mode"],
                **score_fire(
                    fixture,
                    automation,
                    cursor_before=cursor_before,
                    released_now=released_now,
                    batches_before=batches_before,
                    threshold=threshold,
                ),
            }
            results["fires"].append(row)
            print(
                f"[fire_{label}] mode={outcome['fire_mode']} "
                f"delivered={row['batches_delivered']} correct={row['correct']} "
                f"accuracy={row['accuracy']}",
            )

        round_no = 0
        for _ in range(PRE_CHANGE_ROUNDS):
            round_no += 1
            release_round(fixture)
            for automation in AUTOMATIONS:
                fire(automation, round_no, INITIAL_THRESHOLD)

        artifacts_before = _artifact_shas(workspace)
        print("[policy_change] issuing update to opencode ...")
        start = ledger.count()
        t0 = time.monotonic()
        code, _ = run_opencode(
            ["run", POLICY_UPDATE_MESSAGE],
            workspace=workspace,
            state_root=state_root,
            config_path=config_path,
            log_path=log_path,
            timeout_s=phase_timeout_s,
        )
        ledger.mark("policy_change", start, ledger.count(), time.monotonic() - t0)
        artifacts_after = _artifact_shas(workspace)
        changed = sorted(
            key
            for key in set(artifacts_before) | set(artifacts_after)
            if artifacts_before.get(key) != artifacts_after.get(key)
        )
        results["policy_change"] = {
            "exit_code": code,
            "artifacts_changed": changed,
            "artifacts_total": len(artifacts_after),
        }
        print(f"[policy_change] exit={code}; artifacts touched: {changed}")

        for _ in range(POST_CHANGE_ROUNDS):
            round_no += 1
            release_round(fixture)
            for automation in AUTOMATIONS:
                fire(automation, round_no, UPDATED_THRESHOLD)

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
        f"# policy_propagation (opencode arm) — {results['run_id']}",
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
        "| round | automation | threshold | mode | delivered | contract | accuracy |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results.get("fires", []):
        lines.append(
            f"| {r['round']} | {r['automation']} | ${r['threshold']} | "
            f"{r['fire_mode']} | {r['batches_delivered']} | {r['correct']} | "
            f"{r['accuracy']} |",
        )
    summary = "\n".join(lines) + "\n"
    (results_dir / "summary.md").write_text(summary, encoding="utf-8")
    fixture.stop()
    proxy.stop()
    print(f"\n{summary}")
    print(f"[done] results in {results_dir}")


if __name__ == "__main__":
    sys.exit(main())
