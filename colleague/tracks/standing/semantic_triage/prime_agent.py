"""Semantic triage benchmark: prime-agent arm.

Identical utterance and fire protocol as the other arms, on the shared
prime-agent arm of the fire-series engine (`PrimeAgentArm` in
``colleague/tracks/standing/series/cli_arms.py``): one resident RPC session
across setup and every fire, the recording proxy in front of the model, and
the firing rule stated in that class's docstring — a prime-agent scheduled
job's own prompt if the agent registered one, else the agent's crontab
declaration, else its single script, else the neutral wake prompt into the
saved session. Which rule fired is recorded per fire as ``fire_mode``.

No drift, no operator intervention: the measurement is the steady-state
per-fire cost and accuracy of whatever the agent persisted for recurring
work with a judgment substep.

Launch via run_prime_agent.sh.
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

from colleague.arms.proxy import RecordingProxy  # noqa: E402
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
from colleague.tracks.standing.series.cli_arms import PrimeAgentArm  # noqa: E402


def main() -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY is required (use run_prime_agent.sh)")
    seed = int(os.environ.get("ST_SEED", DEFAULT_SEED))
    fixture_port = int(os.environ.get("ST_PORT", DEFAULT_PORT))
    proxy_port = int(os.environ.get("ST_PROXY_PORT", "8182"))
    n_fires = int(os.environ.get("ST_FIRES", N_FIRES))
    phase_timeout_s = float(os.environ.get("ST_PHASE_TIMEOUT_S", "1800"))
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + "-prime-agent"

    results_dir = EXPERIMENT_DIR / "results" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    proxy = RecordingProxy(
        port=proxy_port,
        ledger_path=results_dir / "proxy_ledger.jsonl",
    ).start()
    fixture = TriageFixtureServer(seed=seed, port=fixture_port).start()
    print(f"[fixture] {fixture.base_url} (seed={seed})")
    print(f"[proxy] {proxy.base_url} -> openrouter.ai")
    ledger = PhaseLedger(results_dir / "proxy_ledger.jsonl")
    arm = PrimeAgentArm(
        results_dir=results_dir,
        proxy_base_url=proxy.base_url,
        timeout_s=phase_timeout_s,
    )

    utterance = UTTERANCE_TEMPLATE.format(base_url=fixture.base_url)
    results: dict[str, Any] = {
        "experiment": "semantic_triage",
        "system": "prime-agent",
        "run_id": run_id,
        **arm.describe(),
        "seed": seed,
        "n_fires": n_fires,
        "utterance": utterance,
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
        print("[setup] issuing utterance to prime-agent ...")
        results["setup"] = _phase("setup", lambda: arm.setup(utterance))
        results["profile_after_setup"] = arm.snapshot()
        print(
            f"[setup] exit={results['setup'].get('exit_code')} persisted={results['profile_after_setup']}",
        )

        for i in range(1, n_fires + 1):
            cursor_before, released_now, batches_before = prepare_fire(fixture)
            print(f"[fire_{i}] pending seqs {cursor_before + 1}..{released_now}")
            fire = _phase(f"fire_{i}", arm.fire)
            row = {
                "fire": i,
                "fire_mode": fire["fire_mode"],
                "exit_code": fire.get("exit_code"),
                "agent_runs": fire.get("agent_runs"),
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
        f"# semantic_triage (prime-agent arm) — {results['run_id']}",
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
