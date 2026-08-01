"""Recurring weekly report benchmark: hermes-agent comparison arm.

Identical protocol to the unify driver (harness.py), applied to hermes-agent:

  - The literally identical natural-language utterance is given to the hermes
    agent as one headless chat message (``cli.py -q ...``). No manual cron
    setup, no skill authoring — the agent self-organizes, exactly as the
    unify actor did.
  - Whatever recurring automation the agent created is then fired N times
    via hermes's own manual trigger (``hermes cron run <id>``), which
    executes the job in-process exactly like a scheduler tick would.
  - The same seeded fixture serves the data and receives the reports, and
    the same ground-truth scorer grades every delivered report.

Metering is neutral: hermes's OpenAI-compatible ``base_url`` points at a
local recording proxy (openrouter_proxy.py) that forwards to OpenRouter
unchanged and records provider-reported usage per call — the same source of
truth the unify arm's in-process hook read. Model is pinned to the same
``openai/gpt-5.6-sol`` via OpenRouter.

Isolation: a throwaway ``HERMES_HOME`` under the results directory, so no
real hermes profile is touched; the agent's shell cwd is a scratch
workspace.

Launch via run_hermes.sh.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPERIMENT_DIR = Path(__file__).resolve().parent

from colleague.tracks.standing.recurring_report.fixture import (  # noqa: E402
    DEFAULT_PORT,
    DEFAULT_SEED,
    FixtureServer,
    expected_report,
    score_report,
)
from colleague.tracks.standing.recurring_report.harness import (
    UTTERANCE_TEMPLATE,
)  # noqa: E402
from colleague.arms.proxy import (  # noqa: E402
    RecordingProxy,
)

from colleague.harness.ledger import PhaseLedger  # noqa: F401

HERMES_REPO = Path(
    os.environ.get("RWR_HERMES_REPO", str(Path.home() / "hermes-agent")),
)
BENCH_MODEL = os.environ.get("RWR_MODEL", "openai/gpt-5.6-sol")

# base_url deliberately lives in OPENROUTER_BASE_URL (set per subprocess):
# hermes only trusts config-file base_url for auto/custom providers, while
# the env var is its first-class "OpenRouter mirror/proxy" override that
# keeps OPENROUTER_API_KEY selection intact (hermes_cli/runtime_provider.py).
CONFIG_TEMPLATE = """\
model:
  default: "{model}"
  provider: "openrouter"
"""


def _hermes_env(
    hermes_home: Path,
    workdir: Path,
    proxy_base_url: str,
) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "HERMES_HOME": str(hermes_home),
        "OPENROUTER_API_KEY": os.environ["OPENROUTER_API_KEY"],
        "OPENROUTER_BASE_URL": proxy_base_url,
        "TERMINAL_CWD": str(workdir),
        "PYTHONUNBUFFERED": "1",
        "TERM": "dumb",
        "NO_COLOR": "1",
    }
    return env


def _run_hermes(
    args: list[str],
    *,
    hermes_home: Path,
    workdir: Path,
    proxy_base_url: str,
    log_path: Path,
    timeout_s: float,
) -> tuple[int, str]:
    """Run a hermes CLI invocation headless; returns (returncode, tail)."""
    cmd = [str(HERMES_REPO / ".venv" / "bin" / "hermes"), *args]
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"\n===== {datetime.now(timezone.utc).isoformat()} {args!r}\n")
        log.flush()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(HERMES_REPO),
                env=_hermes_env(hermes_home, workdir, proxy_base_url),
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                timeout=timeout_s,
            )
            code = proc.returncode
        except subprocess.TimeoutExpired:
            log.write(f"\n===== TIMEOUT after {timeout_s}s\n")
            code = -1
    tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
    return code, tail


def _load_cron_jobs(hermes_home: Path) -> list[dict[str, Any]]:
    jobs_file = hermes_home / "cron" / "jobs.json"
    if not jobs_file.exists():
        return []
    data = json.loads(jobs_file.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        jobs = data.get("jobs")
        return jobs if isinstance(jobs, list) else []
    return data if isinstance(data, list) else []


def defuse_hermes_artifacts(hermes_home: Path) -> list[str]:
    """Neutralize live machinery the hermes agent may have left behind.

    The agent can legitimately create recurring cron jobs, spawn a gateway
    process to tick them, and (observed in the drift_recovery operator-fix
    session) even install a persistent launchd service — all pointed at the
    throwaway HERMES_HOME. Results directories must be inert artifacts, so
    after a run: disable every cron job in the profile, kill any gateway
    process whose environment binds this home, and remove launchd agents
    that reference it. Returns a log of actions taken.
    """
    import plistlib
    import signal
    import subprocess

    actions: list[str] = []
    jobs_file = hermes_home / "cron" / "jobs.json"
    if jobs_file.exists():
        data = json.loads(jobs_file.read_text(encoding="utf-8"))
        jobs = data.get("jobs") if isinstance(data, dict) else data
        for job in jobs or []:
            if job.get("enabled"):
                job["enabled"] = False
                job["state"] = "paused"
                job["paused_reason"] = "benchmark artifact - defused post-run"
                actions.append(f"disabled cron job {job.get('id')}")
        jobs_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    home_str = str(hermes_home)
    try:
        pids = subprocess.run(
            ["pgrep", "-f", "hermes_cli.main gateway"],
            capture_output=True,
            text=True,
        ).stdout.split()
    except Exception:
        pids = []
    for pid in pids:
        try:
            env_dump = subprocess.run(
                ["ps", "eww", pid],
                capture_output=True,
                text=True,
            ).stdout
            if home_str in env_dump:
                os.kill(int(pid), signal.SIGTERM)
                actions.append(f"killed gateway pid {pid}")
        except Exception:
            continue

    launch_agents = Path.home() / "Library" / "LaunchAgents"
    if launch_agents.is_dir():
        for plist_path in launch_agents.glob("*hermes*.plist"):
            try:
                if home_str not in plist_path.read_text(errors="replace"):
                    continue
                label = plistlib.loads(plist_path.read_bytes()).get("Label")
                if label:
                    subprocess.run(
                        ["launchctl", "bootout", f"gui/{os.getuid()}/{label}"],
                        capture_output=True,
                    )
                plist_path.unlink()
                actions.append(f"removed launch agent {plist_path.name}")
            except Exception:
                continue
    return actions


def _snapshot_profile_artifacts(hermes_home: Path) -> dict[str, Any]:
    """Record what the agent persisted: cron jobs, skills, scripts."""
    artifacts: dict[str, Any] = {"cron_jobs": _load_cron_jobs(hermes_home)}
    skills_dir = hermes_home / "skills"
    artifacts["skills"] = (
        sorted(
            str(p.relative_to(skills_dir)) for p in skills_dir.rglob("*") if p.is_file()
        )
        if skills_dir.exists()
        else []
    )
    scripts_dir = hermes_home / "scripts"
    artifacts["scripts"] = (
        sorted(
            str(p.relative_to(scripts_dir))
            for p in scripts_dir.rglob("*")
            if p.is_file()
        )
        if scripts_dir.exists()
        else []
    )
    return artifacts
