"""Policy propagation benchmark: hermes-agent arm.

Identical protocol to the unify arm: three chat setups (each utterance
states the escalation policy verbatim), two rounds under the initial
policy, one chat policy-update message, three rounds under the updated
policy. Cron job prompts/scripts are snapshotted before and after the
update so the results record exactly which artifacts the agent found and
edited — a missed copy keeps enforcing the stale threshold and shows up as
wrong output on that automation's post-change fires.

Launch via run_hermes.sh.
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


def _job_artifact_shas(hermes_home: Path) -> dict[str, dict[str, str]]:
    """job_id -> {prompt_sha, script_sha} snapshots for change attribution."""
    out: dict[str, dict[str, str]] = {}
    for job in _load_cron_jobs(hermes_home):
        job_id = str(job.get("id"))
        prompt = str(job.get("prompt") or "")
        entry = {"prompt_sha": hashlib.sha256(prompt.encode()).hexdigest()[:12]}
        script = job.get("script")
        if script:
            script_path = hermes_home / "scripts" / str(script)
            if script_path.exists():
                entry["script_sha"] = hashlib.sha256(
                    script_path.read_bytes(),
                ).hexdigest()[:12]
        out[job_id] = entry
    return out


def main() -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY is required (use run_hermes.sh)")
    if not (HERMES_REPO / ".venv" / "bin" / "hermes").exists():
        raise SystemExit(f"hermes binary missing — run `uv sync` in {HERMES_REPO}")

    seed = int(os.environ.get("PP_SEED", DEFAULT_SEED))
    fixture_port = int(os.environ.get("PP_PORT", DEFAULT_PORT))
    proxy_port = int(os.environ.get("PP_PROXY_PORT", "8134"))
    phase_timeout_s = float(os.environ.get("PP_PHASE_TIMEOUT_S", "1800"))
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
    fixture = PolicyFixtureServer(seed=seed, port=fixture_port).start()
    print(f"[fixture] {fixture.base_url} (seed={seed})")
    print(f"[proxy] {proxy.base_url} -> openrouter.ai")

    (hermes_home / "config.yaml").write_text(
        CONFIG_TEMPLATE.format(model=BENCH_MODEL),
        encoding="utf-8",
    )
    ledger = PhaseLedger(results_dir / "proxy_ledger.jsonl")

    results: dict[str, Any] = {
        "experiment": "policy_propagation",
        "system": "hermes-agent",
        "run_id": run_id,
        "hermes_repo": str(HERMES_REPO),
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

    job_ids: dict[str, str] = {}
    seen: set[str] = set()
    for automation in AUTOMATIONS:
        print(f"[setup_{automation}] issuing utterance to hermes ...")
        start = ledger.count()
        t0 = time.monotonic()
        code, tail = _run_hermes(
            ["chat", "-q", build_utterance(automation, fixture.base_url)],
            hermes_home=hermes_home,
            workdir=workdir,
            proxy_base_url=proxy.base_url,
            log_path=log_path,
            timeout_s=phase_timeout_s,
        )
        ledger.mark(f"setup_{automation}", start, ledger.count(), time.monotonic() - t0)
        results[f"setup_{automation}"] = {"exit_code": code}
        jobs = _load_cron_jobs(hermes_home)
        new_ids = sorted({str(j.get("id")) for j in jobs} - seen)
        seen.update(new_ids)
        if code != 0 or len(new_ids) != 1:
            results["defuse_actions"] = defuse_hermes_artifacts(hermes_home)
            _finalize(results, ledger, results_dir, fixture, proxy)
            print(f"[abort] setup_{automation}: exit={code}, new jobs={new_ids}")
            return 1
        job_ids[automation] = new_ids[0]
        print(f"[setup_{automation}] cron job {new_ids[0]}")
    results["job_ids"] = job_ids
    results["profile_after_setup"] = _snapshot_profile_artifacts(hermes_home)

    def fire(automation: str, round_no: int, threshold: int) -> None:
        cursor_before, released_now, batches_before = prepare_fire(
            fixture,
            automation,
        )
        label = f"round{round_no}_{automation}"
        print(f"[fire_{label}] pending {cursor_before + 1}..{released_now}")
        start = ledger.count()
        t0 = time.monotonic()
        code, _ = _run_hermes(
            ["cron", "run", job_ids[automation]],
            hermes_home=hermes_home,
            workdir=workdir,
            proxy_base_url=proxy.base_url,
            log_path=log_path,
            timeout_s=phase_timeout_s,
        )
        ledger.mark(f"fire_{label}", start, ledger.count(), time.monotonic() - t0)
        row = {
            "round": round_no,
            "automation": automation,
            "threshold": threshold,
            "exit_code": code,
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
            f"[fire_{label}] exit={code} delivered={row['batches_delivered']} "
            f"correct={row['correct']} accuracy={row['accuracy']}",
        )

    round_no = 0
    for _ in range(PRE_CHANGE_ROUNDS):
        round_no += 1
        release_round(fixture)
        for automation in AUTOMATIONS:
            fire(automation, round_no, INITIAL_THRESHOLD)

    artifacts_before = _job_artifact_shas(hermes_home)
    print("[policy_change] issuing update to hermes ...")
    start = ledger.count()
    t0 = time.monotonic()
    code, tail = _run_hermes(
        ["chat", "-q", POLICY_UPDATE_MESSAGE],
        hermes_home=hermes_home,
        workdir=workdir,
        proxy_base_url=proxy.base_url,
        log_path=log_path,
        timeout_s=phase_timeout_s,
    )
    ledger.mark("policy_change", start, ledger.count(), time.monotonic() - t0)
    artifacts_after = _job_artifact_shas(hermes_home)
    changed = {
        job_id: {"before": artifacts_before.get(job_id), "after": snap}
        for job_id, snap in artifacts_after.items()
        if artifacts_before.get(job_id) != snap
    }
    results["policy_change"] = {
        "exit_code": code,
        "artifacts_changed": changed,
        "jobs_total": len(artifacts_after),
    }
    print(f"[policy_change] exit={code}; jobs touched: {sorted(changed)}")

    for _ in range(POST_CHANGE_ROUNDS):
        round_no += 1
        release_round(fixture)
        for automation in AUTOMATIONS:
            fire(automation, round_no, UPDATED_THRESHOLD)

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
        f"# policy_propagation (hermes-agent arm) — {results['run_id']}",
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
