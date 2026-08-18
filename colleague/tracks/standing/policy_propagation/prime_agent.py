"""Policy propagation benchmark: prime-agent arm.

Identical protocol to the other arms: three separate automation requests
over one inquiry stream, PRE_CHANGE_ROUNDS rounds of fires, one
natural-language policy update, POST_CHANGE_ROUNDS more rounds. The arm is
the shared prime-agent arm of the fire-series engine (`PrimeAgentArm` in
``colleague/tracks/standing/series/cli_arms.py``): one resident RPC session
across all three setups, every fire and the policy change — three requests
into the same project is exactly one user's daemon session.

Two departures from the opencode driver, both forced by what the product
is:

- **No abort gate on an empty declaration.** OpenCode's driver aborts when
  a setup leaves no artifact, because its fires are cold sessions — no
  artifact means the automation does not exist, and a blind wake into the
  shared workspace consumes a sibling's pending range. prime-agent's model
  has no scheduling tool on the RPC surface and holds its automations in
  the resident session (both prior standing runs persisted nothing and
  delivered correctly), so an empty workspace is not a missing automation
  and aborting would misdeclare the product as unable to reach the
  scenario.
- **Firing by name resolves against the session.** The precedence mirrors
  the arm's shared rule, matched per automation: an active prime-agent
  scheduled job whose prompt names this automation's sink endpoint; else a
  workspace script that names it; else the neutral wake prompt naming the
  automation, into the saved session. Which rule fired is recorded per
  fire as ``fire_mode``.

Change attribution: every workspace file is hashed before and after the
policy-change turn, as for the other arms — with the caveat, visible in
the results, that for this arm the propagation artifact is usually the
session itself rather than a file.

Launch via run_prime_agent.sh.
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
    WAKE_PROMPT,
    discover_scripts,
    workspace_files,
)
from colleague.arms.prime_agent import scheduled_jobs  # noqa: E402
from colleague.arms.proxy import RecordingProxy  # noqa: E402
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
from colleague.tracks.standing.series.cli_arms import PrimeAgentArm  # noqa: E402


def _declared_for(arm: PrimeAgentArm, automation: str) -> list[str]:
    """Artifacts that genuinely implement this automation.

    The content rule of the opencode driver, extended to prime-agent's own
    store: a scheduled job counts when its prompt names this automation's
    sink endpoint; a script counts when its content names the endpoint and
    its name carries the automation's key. An empty result is expected for
    this arm and is not an error — the resident session is the store the
    product actually uses.
    """
    endpoint = f"/{automation}"
    key = automation[:5]
    found: list[str] = []
    for j in scheduled_jobs(arm.session_dir):
        if j.get("status") == "active" and endpoint in str(j.get("prompt") or ""):
            found.append(f"job:{j.get('id') or j.get('name')}")
    for p in discover_scripts(arm.workspace):
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


def _fire_named(arm: PrimeAgentArm, automation: str) -> dict[str, Any]:
    """Fire one automation, resolving its own declared artifact by name."""
    declared = _declared_for(arm, automation)
    jobs = {d.split(":", 1)[1] for d in declared if d.startswith("job:")}
    if jobs:
        job = next(
            j
            for j in scheduled_jobs(arm.session_dir)
            if str(j.get("id") or j.get("name")) in jobs
        )
        out = arm.message(str(job.get("prompt") or ""))
        return {"fire_mode": "prime_agent_schedule", **out}

    script_names = {d.split(":", 1)[1] for d in declared if d.startswith("script:")}
    scripts = [p for p in discover_scripts(arm.workspace) if p.name in script_names]
    if len(scripts) == 1:
        script = scripts[0]
        runner = (
            ["python3", str(script)]
            if script.suffix == ".py"
            else ["bash", str(script)]
        )
        with open(arm.log_path, "a", encoding="utf-8") as log:
            log.write(f"\n===== script fire {script.name} ({automation})\n")
            proc = subprocess.run(
                runner,
                cwd=str(arm.workspace),
                env=arm.rpc.env(),
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=arm.timeout_s,
            )
            log.write(proc.stdout)
            log.write(proc.stderr)
        return {"fire_mode": f"script:{script.name}", "exit_code": proc.returncode}

    out = arm.message(f"{WAKE_PROMPT} Run the {automation} automation.")
    return {"fire_mode": "wake_prompt", **out}


def main() -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY is required (use run_prime_agent.sh)")
    seed = int(os.environ.get("PP_SEED", DEFAULT_SEED))
    fixture_port = int(os.environ.get("PP_PORT", DEFAULT_PORT))
    proxy_port = int(os.environ.get("PP_PROXY_PORT", "8184"))
    phase_timeout_s = float(os.environ.get("PP_PHASE_TIMEOUT_S", "1800"))
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + "-prime-agent"

    results_dir = EXPERIMENT_DIR / "results" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    proxy = RecordingProxy(
        port=proxy_port,
        ledger_path=results_dir / "proxy_ledger.jsonl",
    ).start()
    fixture = PolicyFixtureServer(seed=seed, port=fixture_port).start()
    print(f"[fixture] {fixture.base_url} (seed={seed})")
    print(f"[proxy] {proxy.base_url} -> openrouter.ai")
    ledger = PhaseLedger(results_dir / "proxy_ledger.jsonl")
    arm = PrimeAgentArm(
        results_dir=results_dir,
        proxy_base_url=proxy.base_url,
        timeout_s=phase_timeout_s,
    )

    results: dict[str, Any] = {
        "experiment": "policy_propagation",
        "system": "prime-agent",
        "run_id": run_id,
        **arm.describe(),
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

    def _phase(name: str, fn):
        start = ledger.count()
        t0 = time.monotonic()
        out = fn()
        ledger.mark(name, start, ledger.count(), time.monotonic() - t0)
        return out

    try:
        arm.start()
        for automation in AUTOMATIONS:
            print(f"[setup_{automation}] issuing utterance to prime-agent ...")
            out = _phase(
                f"setup_{automation}",
                lambda a=automation: arm.message(build_utterance(a, fixture.base_url)),
            )
            declared = _declared_for(arm, automation)
            results[f"setup_{automation}"] = {
                "exit_code": out.get("exit_code"),
                "declared": declared,
            }
            print(
                f"[setup_{automation}] exit={out.get('exit_code')} declared={declared}",
            )
        results["profile_after_setup"] = arm.snapshot()
        print(f"[setup] persisted: {results['profile_after_setup']}")

        def fire(automation: str, round_no: int, threshold: int) -> None:
            cursor_before, released_now, batches_before = prepare_fire(
                fixture,
                automation,
            )
            label = f"round{round_no}_{automation}"
            print(f"[fire_{label}] pending {cursor_before + 1}..{released_now}")
            outcome = _phase(f"fire_{label}", lambda: _fire_named(arm, automation))
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

        artifacts_before = _artifact_shas(arm.workspace)
        print("[policy_change] issuing update to prime-agent ...")
        out = _phase("policy_change", lambda: arm.message(POLICY_UPDATE_MESSAGE))
        artifacts_after = _artifact_shas(arm.workspace)
        changed = sorted(
            key
            for key in set(artifacts_before) | set(artifacts_after)
            if artifacts_before.get(key) != artifacts_after.get(key)
        )
        results["policy_change"] = {
            "exit_code": out.get("exit_code"),
            "artifacts_changed": changed,
            "artifacts_total": len(artifacts_after),
        }
        print(
            f"[policy_change] exit={out.get('exit_code')}; artifacts touched: {changed}",
        )

        for _ in range(POST_CHANGE_ROUNDS):
            round_no += 1
            release_round(fixture)
            for automation in AUTOMATIONS:
                fire(automation, round_no, UPDATED_THRESHOLD)

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
        f"# policy_propagation (prime-agent arm) — {results['run_id']}",
        "",
        f"- model: `{results['model']}` via recording proxy -> OpenRouter",
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
