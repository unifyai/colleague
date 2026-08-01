"""Policy propagation benchmark: OpenClaw arm.

Identical protocol to the unify and hermes arms: three separate automation
requests over one inquiry stream, PRE_CHANGE_ROUNDS rounds of fires, one
natural-language policy update, POST_CHANGE_ROUNDS more rounds. Reuses the
exp-1 OpenClaw machinery (throwaway ``OPENCLAW_STATE_DIR``, managed
Gateway, recording proxy, ``openclaw cron run`` fires, defusing).

Change attribution: cron-job payloads and workspace files are hashed
before and after the policy-change session, so the results record exactly
which artifacts the agent touched to propagate the new threshold.

Launch via run_openclaw.sh.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPERIMENT_DIR = Path(__file__).resolve().parent

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
from colleague.harness.ledger import PhaseLedger  # noqa: E402
from colleague.arms.openclaw import (  # noqa: E402
    BENCH_MODEL,
    GatewayProcess,
    OPENCLAW_REPO,
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

_VOLATILE_JOB_KEYS = {"state", "updatedAtMs", "nextRunAtMs", "lastRunAtMs"}


def _artifact_shas(
    state_dir: Path,
    workspace: Path,
    gateway_port: int,
    log_path: Path,
) -> dict[str, str]:
    """Stable content hashes for every mutable artifact: cron payloads and
    workspace files, keyed for before/after change attribution."""
    out: dict[str, str] = {}
    for job in cron_jobs(state_dir, gateway_port, log_path):
        stable = {k: v for k, v in job.items() if k not in _VOLATILE_JOB_KEYS}
        digest = hashlib.sha256(
            json.dumps(stable, sort_keys=True, default=str).encode(),
        ).hexdigest()[:12]
        out[f"cron:{job.get('id')}"] = digest
    if workspace.exists():
        for path in sorted(workspace.rglob("*")):
            if path.is_file() and ".git" not in path.parts:
                out[f"ws:{path.relative_to(workspace)}"] = hashlib.sha256(
                    path.read_bytes(),
                ).hexdigest()[:12]
    return out


def main() -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY is required (use run_openclaw.sh)")
    if not (OPENCLAW_REPO / "dist").is_dir():
        raise SystemExit(
            f"OpenClaw build output missing — run `pnpm install && pnpm build` "
            f"in {OPENCLAW_REPO}",
        )

    seed = int(os.environ.get("PP_SEED", DEFAULT_SEED))
    fixture_port = int(os.environ.get("PP_PORT", DEFAULT_PORT))
    proxy_port = int(os.environ.get("PP_PROXY_PORT", "8161"))
    gateway_port = int(os.environ.get("OC_GATEWAY_PORT", "18938"))
    phase_timeout_s = float(os.environ.get("PP_PHASE_TIMEOUT_S", "1800"))
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
    fixture = PolicyFixtureServer(seed=seed, port=fixture_port).start()
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

    results: dict[str, Any] = {
        "experiment": "policy_propagation",
        "system": "openclaw",
        "run_id": run_id,
        "openclaw_repo": str(OPENCLAW_REPO),
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
        job_ids: dict[str, str] = {}
        seen: set[str] = set()
        for automation in AUTOMATIONS:
            print(f"[setup_{automation}] issuing utterance to openclaw ...")
            start = ledger.count()
            t0 = time.monotonic()
            code, _ = run_openclaw(
                [
                    "agent",
                    "--session-id",
                    "benchmark-setup",
                    "-m",
                    build_utterance(automation, fixture.base_url),
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
                f"setup_{automation}",
                start,
                ledger.count(),
                time.monotonic() - t0,
            )
            results[f"setup_{automation}"] = {"exit_code": code}
            jobs = cron_jobs(state_dir, gateway_port, log_path)
            new_ids = sorted({str(j.get("id")) for j in jobs} - seen)
            seen.update(new_ids)
            if code != 0 or len(new_ids) != 1:
                print(f"[abort] setup_{automation}: exit={code}, new jobs={new_ids}")
                return 1
            job_ids[automation] = new_ids[0]
            print(f"[setup_{automation}] cron job {new_ids[0]}")
        results["job_ids"] = job_ids
        results["profile_after_setup"] = snapshot_artifacts(
            state_dir,
            workspace,
            gateway_port,
            log_path,
        )

        def fire(automation: str, round_no: int, threshold: int) -> None:
            cursor_before, released_now, batches_before = prepare_fire(
                fixture,
                automation,
            )
            label = f"round{round_no}_{automation}"
            print(f"[fire_{label}] pending {cursor_before + 1}..{released_now}")
            start = ledger.count()
            t0 = time.monotonic()
            outcome = cron_fire(
                job_ids[automation],
                state_dir=state_dir,
                gateway_port=gateway_port,
                log_path=log_path,
                timeout_s=phase_timeout_s,
            )
            ledger.mark(f"fire_{label}", start, ledger.count(), time.monotonic() - t0)
            row = {
                "round": round_no,
                "automation": automation,
                "threshold": threshold,
                "fire_status": outcome.get("status"),
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
                f"[fire_{label}] status={outcome.get('status')} "
                f"delivered={row['batches_delivered']} correct={row['correct']} "
                f"accuracy={row['accuracy']}",
            )

        round_no = 0
        for _ in range(PRE_CHANGE_ROUNDS):
            round_no += 1
            release_round(fixture)
            for automation in AUTOMATIONS:
                fire(automation, round_no, INITIAL_THRESHOLD)

        artifacts_before = _artifact_shas(
            state_dir,
            workspace,
            gateway_port,
            log_path,
        )
        print("[policy_change] issuing update to openclaw ...")
        start = ledger.count()
        t0 = time.monotonic()
        code, _ = run_openclaw(
            [
                "agent",
                "--session-id",
                "benchmark-setup",
                "-m",
                POLICY_UPDATE_MESSAGE,
                "--json",
                "--timeout",
                str(int(phase_timeout_s)),
            ],
            state_dir=state_dir,
            gateway_port=gateway_port,
            log_path=log_path,
            timeout_s=phase_timeout_s + 60,
        )
        ledger.mark("policy_change", start, ledger.count(), time.monotonic() - t0)
        artifacts_after = _artifact_shas(
            state_dir,
            workspace,
            gateway_port,
            log_path,
        )
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
        f"# policy_propagation (openclaw arm) — {results['run_id']}",
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
        "| round | automation | threshold | delivered | contract | accuracy |",
        "|---|---|---|---|---|---|",
    ]
    for r in results.get("fires", []):
        lines.append(
            f"| {r['round']} | {r['automation']} | ${r['threshold']} | "
            f"{r['batches_delivered']} | {r['correct']} | {r['accuracy']} |",
        )
    summary = "\n".join(lines) + "\n"
    (results_dir / "summary.md").write_text(summary, encoding="utf-8")
    fixture.stop()
    proxy.stop()
    print(f"\n{summary}")
    print(f"[done] results in {results_dir}")


if __name__ == "__main__":
    sys.exit(main())
