"""Recurring weekly report benchmark: OpenClaw comparison arm.

Identical protocol to the unify and hermes drivers, applied to OpenClaw:

  - The literally identical natural-language utterance is delivered as one
    headless agent turn (``openclaw agent -m ...``). No manual cron setup —
    the agent self-organizes with its own cron tool.
  - Whatever recurring automation the agent created is then fired N times
    via OpenClaw's own manual trigger (``openclaw cron run <id>``), executed
    by the same Gateway scheduler a production deployment would use.
  - The same seeded fixture serves the data and receives the reports, and
    the same ground-truth scorer grades every delivered report.

Metering is neutral: the OpenRouter provider's ``baseUrl`` is repointed at
the local recording proxy (openrouter_proxy.py), which forwards to
OpenRouter unchanged and records provider-reported usage per call. Model is
pinned to the same ``openai/gpt-5.6-sol``.

Isolation: a throwaway ``OPENCLAW_STATE_DIR`` under the results directory
(config, cron store, sessions, workspace all live inside it), a dedicated
Gateway port, and no channels configured — the real ``~/.openclaw`` profile
is never read or written. The Gateway runs as a managed child process for
exactly the duration of the run; ``defuse_openclaw_artifacts`` disables
every cron job, stops the Gateway, and sweeps for any daemon artifacts
before the results directory is committed.

This module doubles as the shared OpenClaw toolkit for the other
experiments' drivers (config template, gateway lifecycle, CLI helpers).

Launch via run_openclaw.sh.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPERIMENT_DIR = Path(__file__).resolve().parent

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

OPENCLAW_REPO = Path(
    os.environ.get("OC_REPO", str(Path.home() / "openclaw")),
)
BENCH_MODEL = os.environ.get("OC_MODEL", "openai/gpt-5.6-sol")

CONFIG_TEMPLATE = {
    "gateway": {"mode": "local"},
    "agents": {
        "defaults": {
            "model": {"primary": "openrouter/{model}"},
            "workspace": "{workspace}",
        },
    },
    "models": {
        "mode": "merge",
        "providers": {
            "openrouter": {
                "baseUrl": "{proxy_base_url}",
                "apiKey": "${OPENROUTER_API_KEY}",
                "api": "openai-completions",
                "models": [{"id": "{model}", "name": "{model}"}],
            },
        },
    },
}


def write_openclaw_config(
    state_dir: Path,
    *,
    proxy_base_url: str,
    workspace: Path,
    model: str = BENCH_MODEL,
    gateway_auth_token: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Write the benchmark's OpenClaw config into a throwaway state dir.

    ``gateway_auth_token`` pins the Gateway's shared token so an operator
    client written by the harness can authenticate over the WebSocket
    protocol; the CLI arm leaves it unset and lets the Gateway mint its own.
    Either way `scrub_state_archive` strips ``gateway.auth`` before the state
    dir is archived.

    ``extra`` deep-merges additional product configuration on top of the
    shared template. The voice arm uses it to enable the voice-call plugin
    for a voice run only, so text-track runs keep exactly the tool surface
    the published results used.
    """
    config = json.loads(
        json.dumps(CONFIG_TEMPLATE)
        .replace("{model}", model)
        .replace("{workspace}", str(workspace))
        .replace("{proxy_base_url}", proxy_base_url),
    )
    if gateway_auth_token:
        config["gateway"]["auth"] = {"mode": "token", "token": gateway_auth_token}
    if extra:
        config = _deep_merge(config, extra)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "openclaw.json").write_text(
        json.dumps(config, indent=2),
        encoding="utf-8",
    )


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def openclaw_env(state_dir: Path, gateway_port: int) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "OPENCLAW_STATE_DIR": str(state_dir),
        "OPENCLAW_GATEWAY_PORT": str(gateway_port),
        "OPENROUTER_API_KEY": os.environ["OPENROUTER_API_KEY"],
        "NO_COLOR": "1",
        "TERM": "dumb",
    }
    # The voice arm's own STT (real Deepgram, the caller's ears) reads this
    # from config via ${DEEPGRAM_API_KEY}; pass it through when present. It is
    # inert for every non-voice run — an extra unread variable.
    for passthrough in ("DEEPGRAM_API_KEY",):
        value = os.environ.get(passthrough)
        if value:
            env[passthrough] = value
    return env


def run_openclaw(
    args: list[str],
    *,
    state_dir: Path,
    gateway_port: int,
    log_path: Path,
    timeout_s: float,
) -> tuple[int, str]:
    """Run one OpenClaw CLI invocation headless; returns (code, stdout)."""
    cmd = ["node", str(OPENCLAW_REPO / "openclaw.mjs"), *args]
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"\n===== {datetime.now(timezone.utc).isoformat()} {args!r}\n")
        log.flush()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(OPENCLAW_REPO),
                env=openclaw_env(state_dir, gateway_port),
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout_s,
            )
            code, out = proc.returncode, proc.stdout
            log.write(proc.stdout)
            log.write(proc.stderr)
        except subprocess.TimeoutExpired as exc:
            log.write(f"\n===== TIMEOUT after {timeout_s}s\n")
            code, out = -1, (exc.stdout or b"").decode("utf-8", errors="replace")
    return code, out


def extract_json(text: str) -> Any:
    """Parse the top-level JSON document in CLI output.

    CLI output may carry a warning preamble before the JSON, so scan for
    every candidate start and keep the parse that consumes the most text —
    the document itself, never a nested fragment.
    """
    decoder = json.JSONDecoder()
    best = None
    best_span = 0
    for idx, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            parsed, end = decoder.raw_decode(text[idx:])
        except ValueError:
            continue
        if end > best_span:
            best, best_span = parsed, end
    return best


class GatewayProcess:
    """The OpenClaw Gateway as a managed child for exactly one benchmark run."""

    def __init__(
        self,
        *,
        state_dir: Path,
        gateway_port: int,
        log_path: Path,
    ) -> None:
        self.state_dir = state_dir
        self.gateway_port = gateway_port
        self.log_path = log_path
        self._proc: subprocess.Popen[bytes] | None = None

    def start(self, *, ready_timeout_s: float = 90.0) -> "GatewayProcess":
        # A previous benchmark run's detached gateway may still hold the
        # dedicated port (the launcher respawns the real server, so a killed
        # launcher does not imply a dead gateway). The port is benchmark-only;
        # clear it before booting.
        try:
            stale = subprocess.run(
                ["lsof", "-tiTCP:%d" % self.gateway_port, "-sTCP:LISTEN"],
                capture_output=True,
                text=True,
            ).stdout.split()
        except Exception:
            stale = []
        for pid in stale:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                continue
        if stale:
            time.sleep(3)

        log = open(self.log_path, "a", encoding="utf-8")
        # `gateway run` is a launcher: it respawns the real server as a
        # detached `openclaw-gateway` process and may itself exit 0, so
        # readiness and teardown key off the RPC probe and the port owner,
        # never the launcher's lifetime.
        self._proc = subprocess.Popen(
            ["node", str(OPENCLAW_REPO / "openclaw.mjs"), "gateway", "run"],
            cwd=str(OPENCLAW_REPO),
            env=openclaw_env(self.state_dir, self.gateway_port),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + ready_timeout_s
        while time.monotonic() < deadline:
            code, _ = run_openclaw(
                ["cron", "status", "--json"],
                state_dir=self.state_dir,
                gateway_port=self.gateway_port,
                log_path=self.log_path.with_suffix(".probe.log"),
                timeout_s=15,
            )
            if code == 0:
                return self
            time.sleep(2)
        raise RuntimeError(
            f"gateway did not become ready in time — see {self.log_path}",
        )

    def _server_pids(self) -> list[int]:
        """Pids of gateway server processes bound to this state dir."""
        try:
            pids = subprocess.run(
                ["pgrep", "-f", "openclaw"],
                capture_output=True,
                text=True,
            ).stdout.split()
        except Exception:
            return []
        matched = []
        for pid in pids:
            try:
                env_dump = subprocess.run(
                    ["ps", "eww", pid],
                    capture_output=True,
                    text=True,
                ).stdout
                if str(self.state_dir) in env_dump and "gateway" in env_dump:
                    matched.append(int(pid))
            except Exception:
                continue
        return matched

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.send_signal(signal.SIGTERM)
            try:
                self._proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            pids = self._server_pids()
            if not pids:
                return
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    continue
            time.sleep(2)
        for pid in self._server_pids():
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                continue


def cron_jobs(
    state_dir: Path,
    gateway_port: int,
    log_path: Path,
) -> list[dict[str, Any]]:
    code, out = run_openclaw(
        ["cron", "list", "--all", "--json"],
        state_dir=state_dir,
        gateway_port=gateway_port,
        log_path=log_path,
        timeout_s=60,
    )
    if code != 0:
        return []
    data = extract_json(out)
    if isinstance(data, dict):
        jobs = data.get("jobs")
        return jobs if isinstance(jobs, list) else []
    return data if isinstance(data, list) else []


def _cron_run_entries(
    job_id: str,
    *,
    state_dir: Path,
    gateway_port: int,
    log_path: Path,
    limit: int = 10,
) -> list[dict[str, Any]]:
    code, out = run_openclaw(
        ["cron", "runs", "--id", job_id, "--limit", str(limit)],
        state_dir=state_dir,
        gateway_port=gateway_port,
        log_path=log_path,
        timeout_s=60,
    )
    if code != 0:
        return []
    data = extract_json(out)
    entries = data.get("entries") if isinstance(data, dict) else None
    return entries if isinstance(entries, list) else []


def cron_fire(
    job_id: str,
    *,
    state_dir: Path,
    gateway_port: int,
    log_path: Path,
    timeout_s: float,
) -> dict[str, Any]:
    """Force-run a cron job and wait for its run-history entry.

    The manual trigger is asynchronous (the CLI acks the enqueue and the
    Gateway scheduler executes the run), so completion is detected from the
    job's run history: the first entry whose ``runAtMs`` is at or after the
    trigger, in a terminal state.
    """
    fire_at_ms = time.time() * 1000 - 2000
    code, out = run_openclaw(
        ["cron", "run", job_id],
        state_dir=state_dir,
        gateway_port=gateway_port,
        log_path=log_path,
        timeout_s=120,
    )
    if code != 0:
        return {"exit_code": code, "status": f"enqueue-error(exit={code})"}

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for entry in _cron_run_entries(
            job_id,
            state_dir=state_dir,
            gateway_port=gateway_port,
            log_path=log_path,
        ):
            if not isinstance(entry, dict):
                continue
            if float(entry.get("runAtMs") or 0) < fire_at_ms:
                continue
            status = str(entry.get("status") or "").lower()
            if status and status not in ("running", "pending", "queued"):
                return {"exit_code": code, "status": status, "entry": entry}
        time.sleep(3)
    return {"exit_code": code, "status": "timeout"}


def snapshot_artifacts(
    state_dir: Path,
    workspace: Path,
    gateway_port: int,
    log_path: Path,
) -> dict[str, Any]:
    """Record what the agent persisted: cron jobs plus workspace files."""
    artifacts: dict[str, Any] = {
        "cron_jobs": cron_jobs(state_dir, gateway_port, log_path),
    }
    artifacts["workspace_files"] = (
        sorted(
            str(p.relative_to(workspace))
            for p in workspace.rglob("*")
            if p.is_file() and ".git" not in p.parts
        )
        if workspace.exists()
        else []
    )
    skills_dir = state_dir / "skills"
    artifacts["skills"] = (
        sorted(
            str(p.relative_to(skills_dir)) for p in skills_dir.rglob("*") if p.is_file()
        )
        if skills_dir.exists()
        else []
    )
    return artifacts


def scrub_state_archive(state_dir: Path) -> None:
    """Reduce the archived state dir to benchmark artifacts.

    Keeps the cron store, the agent session transcripts, and a
    credential-stripped copy of the config; drops machine state that has no
    evidentiary value and must not be committed (device identity keys, the
    generated gateway auth token, sqlite task queues, caches, backups).
    """
    import shutil

    if not state_dir.exists():
        return
    for name in (
        "identity",
        "devices",
        "tasks",
        "canvas",
        "logs",
        "tmp",
        "media",
        "update-check.json",
    ):
        target = state_dir / name
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink()
    # The Gateway keeps its own copies of the config; they carry the auth
    # token verbatim and add nothing the scrubbed openclaw.json does not.
    for backup in [
        *state_dir.glob("openclaw.json.bak*"),
        *state_dir.glob("openclaw.json.last-good*"),
    ]:
        backup.unlink()
    # The agent may `git init` its workspace; an embedded repo cannot be
    # committed into the results archive, and its history adds nothing.
    workspace_git = state_dir.parent / "workspace" / ".git"
    if workspace_git.is_dir():
        shutil.rmtree(workspace_git, ignore_errors=True)
    config_path = state_dir / "openclaw.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            (config.get("gateway") or {}).pop("auth", None)
            config_path.write_text(
                json.dumps(config, indent=2) + "\n",
                encoding="utf-8",
            )
        except (ValueError, OSError):
            config_path.unlink()


def defuse_openclaw_artifacts(
    state_dir: Path,
    gateway: GatewayProcess | None,
    gateway_port: int,
    log_path: Path,
) -> list[str]:
    """Neutralize live machinery before the results directory is archived.

    Disable every cron job while the Gateway is still up, stop the managed
    Gateway, kill any stray OpenClaw process whose environment binds this
    state dir, and remove launchd agents referencing it (none are expected —
    the driver never runs the daemon installer — but the hermes arm taught
    us to sweep rather than assume).
    """
    import plistlib

    actions: list[str] = []
    for job in cron_jobs(state_dir, gateway_port, log_path):
        job_id = str(job.get("id"))
        if not job_id:
            continue
        code, _ = run_openclaw(
            ["cron", "disable", job_id],
            state_dir=state_dir,
            gateway_port=gateway_port,
            log_path=log_path,
            timeout_s=60,
        )
        actions.append(f"disabled cron job {job_id} (exit {code})")

    if gateway is not None:
        gateway.stop()
        actions.append("stopped managed gateway")

    home_str = str(state_dir)
    try:
        pids = subprocess.run(
            ["pgrep", "-f", "openclaw"],
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
                actions.append(f"killed stray openclaw pid {pid}")
        except Exception:
            continue

    launch_agents = Path.home() / "Library" / "LaunchAgents"
    if launch_agents.is_dir():
        for plist_path in launch_agents.glob("*openclaw*.plist"):
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

    scrub_state_archive(state_dir)
    actions.append("scrubbed state archive")
    return actions
