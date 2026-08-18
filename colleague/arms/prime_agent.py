"""prime-agent toolkit: the JSONL-RPC transport, shared by the conversational
arm and the `standing` fire-series arm.

prime-agent's RPC mode (`--mode rpc`, `packages/coding-agent/docs/rpc.md`)
is its documented headless integration surface: JSON commands on stdin, one
per line; ``response`` frames echo the command's ``id``; agent events stream
on stdout with no id. It carries what print mode does not — the steering
and follow-up lanes of `core/session-action-store.ts` — and one process
holds one session, so a persistent IPython kernel and any skills the agent
writes survive between turns.

Steering, as observed on the wire (2026-08-18, `849c921`): a ``steer``
accepted mid-run is queued on the steering lane
(``session_action_update.actions.steering``); at the next boundary the
runtime ends the current agent loop (``agent_end``) and pumps the steer as
the next run (``session_action_update.actions.active.label`` = the steer
text, then ``agent_start``) in the same session with the same context. So a
logical turn can span several agent runs and ``agent_end`` alone does not
close it; :class:`PrimeAgentRpc` attributes runs to turns by the pump's
``active.label`` and closes a turn only after a short grace with nothing of
its own still queued.

RPC clients are daemon clients (`docs/daemon.md`: print, JSON and RPC are
"client-owned workers" of a detached supervisor). The default supervisor is
one per user under the system temp dir, shared across runs and left
running; :class:`PrimeAgentRpc` pins ``--daemon-socket`` to a per-session
socket and shuts that supervisor down on close.

Metering: a custom provider (`models.json` in a throwaway agent dir) whose
base URL is the recording proxy, exactly as the print-mode arm does.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

PRIME_AGENT_REPO = Path(
    os.environ.get("PRIME_AGENT_REPO", str(Path.home() / "prime-agent")),
)
BENCH_MODEL = os.environ.get("PRIME_AGENT_MODEL", "openai/gpt-5.6-sol")
PROVIDER = "openrouter-metered"

#: Cold start pays the daemon supervisor and worker spawn before the first
#: response; the first ``get_state`` is the readiness probe.
READY_TIMEOUT_S = 180.0
RPC_TIMEOUT_S = 120.0
#: After ``agent_end`` a steer of the same turn may still be pumped as the
#: next run; wait this long for its ``agent_start`` before closing the turn.
TAIL_GRACE_S = 2.5


def cli_path() -> Path:
    return PRIME_AGENT_REPO / "packages" / "coding-agent" / "dist" / "bundle" / "cli.js"


def require_prime_agent() -> None:
    if not cli_path().exists():
        raise SystemExit(
            f"prime-agent is not built at {cli_path()} — run `npm ci && npm run build` "
            f"in {PRIME_AGENT_REPO} (or set PRIME_AGENT_REPO)",
        )


def write_models_json(agent_dir: Path, *, proxy_base_url: str, model: str) -> Path:
    """A custom provider that speaks OpenAI completions through the proxy.

    The proxy forwards to OpenRouter unchanged and records usage per call;
    the arm never sees the real endpoint, so the token column is exact.
    """
    agent_dir.mkdir(parents=True, exist_ok=True)
    path = agent_dir / "models.json"
    path.write_text(
        json.dumps(
            {
                "providers": {
                    PROVIDER: {
                        "baseUrl": proxy_base_url,
                        "api": "openai-completions",
                        "apiKey": os.environ["OPENROUTER_API_KEY"],
                        "models": [{"id": model, "reasoning": True}],
                    },
                },
            },
            indent=2,
        ),
    )
    return path


def prime_agent_env(agent_dir: Path, session_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PRIME_AGENT_CODING_AGENT_DIR"] = str(agent_dir)
    env["PRIME_AGENT_SESSION_DIR"] = str(session_dir)
    env["NO_COLOR"] = "1"
    env["CI"] = "1"
    return env


def install_cli_shim(bin_dir: Path) -> Path:
    """Put a real `prime-agent` (and `pi`) on PATH for the agent's own use.

    The harness runs the CLI from a source checkout via `node cli.js`, so
    without this the agent's own binary is absent from its shell — the same
    gap the OpenCode toolkit closes. A normal install has it on PATH, and an
    agent that wants its own scheduler (`prime-agent schedule add …`) needs
    to be able to find it. The shim inherits the caller's isolated env.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in ("prime-agent", "pi"):
        shim = bin_dir / name
        shim.write_text(
            "#!/usr/bin/env bash\n" f'exec node "{cli_path()}" "$@"\n',
            encoding="utf-8",
        )
        shim.chmod(0o755)
    return bin_dir


class RpcError(RuntimeError):
    """An RPC command failed, timed out, or the process is gone."""


class _Pending:
    __slots__ = ("event", "response")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.response: dict[str, Any] | None = None


class Turn:
    """One prompt of mine, and every agent run prime-agent spends on it."""

    __slots__ = (
        "prompt",
        "steers",
        "done",
        "text",
        "error",
        "messages",
        "started",
        "ended_at",
        "runs",
        "grace_until",
    )

    def __init__(self, prompt: str) -> None:
        self.prompt = prompt
        self.steers: list[str] = []
        self.done = threading.Event()
        self.text = ""
        self.error = ""
        self.messages: list[Any] = []
        self.started = threading.Event()
        self.ended_at: float | None = None
        self.runs = 0
        self.grace_until: float | None = None


def _same_text(label: str, text: str) -> bool:
    """Action labels are the message text, possibly shortened for display."""
    a, b = label.strip(), text.strip()
    if not a or not b:
        return False
    return a == b or a.startswith(b) or b.startswith(a.rstrip("…").rstrip("."))


def message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(b.get("text") or "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
    return ""


def last_assistant_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "assistant":
            text = message_text(message)
            if text:
                return text
    return ""


class PrimeAgentRpc:
    """One long-lived ``--mode rpc`` process holding one session."""

    def __init__(
        self,
        *,
        agent_dir: Path,
        session_dir: Path,
        workspace: Path,
        proxy_base_url: str,
        stderr_log: Path,
        protocol_log: Path,
        model: str = BENCH_MODEL,
        load_resources: bool = True,
        put_cli_on_path: bool = True,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        """``load_resources`` keeps the product's skills, extensions, prompt
        templates and context files enabled — nothing is preloaded in a
        throwaway agent dir, but the agent may write them and have them
        picked up, which is its distillation mechanism. ``False`` passes the
        ``--no-*`` flags the print-mode arm uses."""
        self.agent_dir = agent_dir
        self.session_dir = session_dir
        self.workspace = workspace
        self.proxy_base_url = proxy_base_url
        self.stderr_log_path = stderr_log
        self.protocol_log = protocol_log
        self.model = model
        self.load_resources = load_resources
        self.put_cli_on_path = put_cli_on_path
        self.extra_env = dict(extra_env or {})
        self._proc: subprocess.Popen | None = None
        self._stderr_log = None
        self._reader: threading.Thread | None = None
        self._alive = False
        self._next_id = 0
        self._id_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        self._pending_lock = threading.Lock()
        self._turns: list[Turn] = []
        self._turn_lock = threading.Lock()
        self.streaming = False
        self._current: Turn | None = None
        self._last_active_label: str | None = None
        self.queued_steering: list[str] = []
        self.queued_followups: list[str] = []
        self.action_updates: list[dict[str, Any]] = []
        self.ui_events: list[dict[str, Any]] = []
        self._log_lock = threading.Lock()
        self._daemon_socket: Path | None = None
        self.session_file = ""
        self.session_id = ""

    # ── lifecycle ────────────────────────────────────────────────────

    def env(self) -> dict[str, str]:
        env = prime_agent_env(self.agent_dir, self.session_dir)
        if self.put_cli_on_path:
            bin_dir = install_cli_shim(self.agent_dir / "bin")
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
        env.update(self.extra_env)
        return env

    def start(self) -> "PrimeAgentRpc":
        require_prime_agent()
        for d in (self.agent_dir, self.session_dir, self.workspace):
            d.mkdir(parents=True, exist_ok=True)
        write_models_json(
            self.agent_dir,
            proxy_base_url=self.proxy_base_url,
            model=self.model,
        )
        # Unix socket paths are capped near 100 bytes on macOS, so the
        # per-session daemon socket lives under the temp dir, not the run dir.
        sock_dir = Path(tempfile.gettempdir()) / f"prime-agent-{os.getuid()}-colleague"
        sock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._daemon_socket = sock_dir / f"{secrets.token_hex(4)}.sock"

        cmd = [
            "node",
            str(cli_path()),
            "--mode",
            "rpc",
            "--provider",
            PROVIDER,
            "--model",
            self.model,
            "--session-dir",
            str(self.session_dir),
            "--cwd",
            str(self.workspace),
            "--daemon-socket",
            str(self._daemon_socket),
            "--offline",
        ]
        if not self.load_resources:
            cmd += [
                "--no-extensions",
                "--no-skills",
                "--no-prompt-templates",
                "--no-context-files",
            ]
        self._stderr_log = open(self.stderr_log_path, "a", encoding="utf-8")
        self._proc = subprocess.Popen(
            cmd,
            cwd=str(self.workspace),
            env=self.env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr_log,
            text=True,
            bufsize=1,
        )
        self._alive = True
        self._reader = threading.Thread(
            target=self._read_loop,
            name="prime-agent-rpc-reader",
            daemon=True,
        )
        self._reader.start()
        deadline = time.monotonic() + READY_TIMEOUT_S
        last: Exception | None = None
        while time.monotonic() < deadline:
            try:
                state = self.rpc("get_state", {}, timeout=30.0)
                self.session_file = str(state.get("sessionFile") or "")
                self.session_id = str(state.get("sessionId") or "")
                return self
            except RpcError as exc:
                last = exc
                if not self._alive:
                    break
                time.sleep(1.0)
        self.close()
        raise RpcError(f"prime-agent rpc never answered get_state: {last}")

    def close(self) -> None:
        proc = self._proc
        if proc is not None:
            # stdin EOF is the documented end of an RPC client: the
            # client-owned worker is removed on normal completion.
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    proc.kill()
            self._proc = None
        self._shutdown_daemon()
        if self._stderr_log is not None:
            try:
                self._stderr_log.close()
            except Exception:  # noqa: BLE001
                pass
            self._stderr_log = None

    def _shutdown_daemon(self) -> None:
        """Stop the per-session supervisor this client spawned."""
        sock = self._daemon_socket
        if sock is None:
            return
        try:
            subprocess.run(
                [
                    "node",
                    str(cli_path()),
                    "shutdown",
                    "--force",
                    "--daemon-socket",
                    str(sock),
                ],
                cwd=str(PRIME_AGENT_REPO),
                env=self.env(),
                capture_output=True,
                text=True,
                timeout=60,
            )
        except Exception:  # noqa: BLE001 - best-effort teardown
            pass
        try:
            pids = subprocess.run(
                ["pgrep", "-f", str(sock)],
                capture_output=True,
                text=True,
            ).stdout.split()
            for pid in pids:
                try:
                    os.kill(int(pid), 15)
                except (ProcessLookupError, ValueError):
                    continue
        except Exception:  # noqa: BLE001
            pass
        for leftover in (sock, Path(str(sock) + ".lock")):
            try:
                if leftover.is_dir():
                    shutil.rmtree(leftover, ignore_errors=True)
                elif leftover.exists():
                    leftover.unlink()
            except OSError:
                pass

    @property
    def alive(self) -> bool:
        return self._alive

    # ── turns ────────────────────────────────────────────────────────

    @staticmethod
    def images(paths: list[str] | None) -> list[dict[str, Any]]:
        out = []
        for path in paths or []:
            p = Path(path)
            out.append(
                {
                    "type": "image",
                    "data": base64.b64encode(p.read_bytes()).decode(),
                    "mimeType": mimetypes.guess_type(p.name)[0] or "image/png",
                },
            )
        return out

    def submit(self, prompt: str, *, images: list[str] | None = None) -> Turn:
        """Send a prompt; returns before the turn ends."""
        turn = Turn(prompt)
        with self._turn_lock:
            busy = self.streaming or any(not t.done.is_set() for t in self._turns)
            self._turns.append(turn)
        params: dict[str, Any] = {"message": prompt}
        if images:
            params["images"] = self.images(images)
        if busy:
            # A second prompt while one streams must say how it queues; a
            # new request is a follow-up, not a correction.
            params["streamingBehavior"] = "followUp"
        try:
            self.rpc("prompt", params, timeout=RPC_TIMEOUT_S)
        except RpcError as exc:
            self.finish_turn(turn, error=f"prompt: {exc}")
        return turn

    def steer(self, message: str, *, target: Turn | None = None) -> None:
        """Queue on the steering lane, bound to the turn it corrects."""
        aimed = target or self._current
        if aimed is not None:
            aimed.steers.append(message)
        self.rpc("steer", {"message": message}, timeout=RPC_TIMEOUT_S)

    def abort(self) -> None:
        try:
            self.rpc("abort", {}, timeout=15.0)
        except Exception:  # noqa: BLE001 - stop is best-effort by contract
            pass

    def wait(self, turn: Turn, timeout: float) -> str:
        """Block until the turn is done; '' or 'timeout' / 'exited'."""
        deadline = time.monotonic() + timeout
        while not turn.done.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "timeout"
            if not self._alive:
                return "exited"
            turn.done.wait(timeout=min(0.5, remaining))
        return ""

    def finish_turn(self, turn: Turn, *, error: str = "") -> None:
        if error and not turn.error:
            turn.error = error
        turn.ended_at = time.monotonic()
        turn.grace_until = None
        turn.done.set()

    def open_turns(self) -> list[Turn]:
        with self._turn_lock:
            return [t for t in self._turns if not t.done.is_set()]

    def current_turn(self) -> Turn | None:
        """The turn whose agent run is streaming, if any."""
        return self._current

    # ── wire protocol ────────────────────────────────────────────────

    def rpc(
        self,
        command: str,
        params: dict[str, Any],
        timeout: float = RPC_TIMEOUT_S,
    ) -> dict[str, Any]:
        if self._proc is None or not self._alive:
            raise RpcError(f"{command}: rpc process is not running")
        with self._id_lock:
            self._next_id += 1
            rid = f"c{self._next_id}"
        pending = _Pending()
        with self._pending_lock:
            self._pending[rid] = pending
        frame = {"id": rid, "type": command, **params}
        try:
            self._write(frame)
            if not pending.event.wait(timeout):
                raise RpcError(f"{command} timed out after {timeout}s")
        finally:
            with self._pending_lock:
                self._pending.pop(rid, None)
        resp = pending.response or {}
        if not resp.get("success"):
            raise RpcError(f"{command} failed: {resp.get('error')}")
        data = resp.get("data")
        return data if isinstance(data, dict) else {}

    def _write(self, frame: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise RpcError("rpc stdin is closed")
        line = json.dumps(frame, ensure_ascii=False)
        try:
            with self._write_lock:
                proc.stdin.write(line + "\n")
                proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as exc:
            raise RpcError(f"rpc write failed: {exc}") from exc
        self._log("send", frame)

    def _read_loop(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        # Split on LF only (docs/rpc.md: generic line readers that also split
        # on U+2028/2029 are not protocol-compliant); Python's text iterator
        # does not split on those, so it is fine here.
        for raw in proc.stdout:
            line = raw.rstrip("\n").rstrip("\r")
            if not line:
                continue
            try:
                frame = json.loads(line)
            except json.JSONDecodeError:
                self._log("recv_raw", {"line": line[:2000]})
                continue
            if not isinstance(frame, dict):
                continue
            self._log("recv", frame)
            if frame.get("type") == "response":
                with self._pending_lock:
                    pending = self._pending.get(str(frame.get("id")))
                if pending is not None:
                    pending.response = frame
                    pending.event.set()
                continue
            try:
                self._on_event(frame)
            except Exception:  # noqa: BLE001 - reader must survive
                pass
        self._alive = False
        with self._pending_lock:
            for pending in self._pending.values():
                pending.response = {"success": False, "error": "rpc process exited"}
                pending.event.set()
            self._pending.clear()
        for turn in self.open_turns():
            self.finish_turn(turn, error="rpc process exited mid-turn")

    # ── events ───────────────────────────────────────────────────────

    def _on_event(self, frame: dict[str, Any]) -> None:
        etype = str(frame.get("type") or "")
        if etype == "agent_start":
            self.streaming = True
            turn = self._attribute_run()
            self._current = turn
            if turn is not None:
                turn.started.set()
                turn.runs += 1
                turn.grace_until = None
        elif etype == "agent_end":
            self.streaming = False
            turn = self._current
            self._current = None
            if turn is not None:
                for msg in frame.get("messages") or []:
                    turn.messages.append(msg)
                turn.text = (
                    last_assistant_text(frame.get("messages") or []) or turn.text
                )
                # A steer of this turn that is still queued (or about to be
                # pumped) continues it in another run; give that a moment.
                turn.ended_at = time.monotonic()
                turn.grace_until = time.monotonic() + TAIL_GRACE_S
                threading.Thread(
                    target=self._finish_after_grace,
                    args=(turn,),
                    daemon=True,
                ).start()
        elif etype == "message_end":
            message = frame.get("message") or {}
            if isinstance(message, dict) and message.get("role") == "assistant":
                turn = self._current
                text = message_text(message)
                if turn is not None and text:
                    turn.text = text
        elif etype == "session_action_update":
            actions = frame.get("actions") or {}
            self.action_updates.append(actions)
            self.queued_steering = [str(x) for x in (actions.get("steering") or [])]
            self.queued_followups = [str(x) for x in (actions.get("followUps") or [])]
            active = actions.get("active")
            if isinstance(active, dict) and active.get("label"):
                self._last_active_label = str(active.get("label"))
        elif etype == "extension_ui_request":
            # Dialogs are dismissed so the agent can never hang on one.
            method = str(frame.get("method") or "")
            self.ui_events.append({"method": method, "id": frame.get("id")})
            if method in ("select", "confirm", "input", "editor"):
                try:
                    self._write(
                        {
                            "type": "extension_ui_response",
                            "id": frame.get("id"),
                            "cancelled": True,
                        },
                    )
                except RpcError:
                    pass
        elif etype == "auto_retry_end" and frame.get("success") is False:
            turn = self._current
            if turn is not None:
                turn.error = str(frame.get("finalError") or "model call failed")

    def _attribute_run(self) -> Turn | None:
        """Which of my turns a fresh agent run belongs to.

        The pump announces what it is about to run as ``active.label`` — the
        exact steer or prompt text — so a run that starts under a steer's
        label continues the turn that steer was aimed at; one under a queued
        prompt's label is that prompt's turn; the first run of a prompt sent
        to an idle agent carries no label and is the oldest turn that has
        not started.
        """
        label = self._last_active_label
        self._last_active_label = None
        open_turns = self.open_turns()
        if label:
            for t in open_turns:
                if any(_same_text(label, st) for st in t.steers):
                    return t
            for t in open_turns:
                if _same_text(label, t.prompt):
                    return t
        for t in open_turns:
            if not t.started.is_set():
                return t
        return open_turns[0] if open_turns else None

    def _finish_after_grace(self, turn: Turn) -> None:
        while True:
            until = turn.grace_until
            if until is None:
                return  # a continuation run picked the turn back up
            now = time.monotonic()
            if now < until:
                time.sleep(min(0.25, until - now))
                continue
            # Still queued for this turn: keep waiting, but not forever.
            if (
                any(
                    any(_same_text(q, st) for st in turn.steers)
                    for q in self.queued_steering
                )
                and now < (turn.ended_at or now) + 120
            ):
                turn.grace_until = now + TAIL_GRACE_S
                continue
            if self._current is turn:
                return
            self.finish_turn(turn)
            return

    # ── transcript ───────────────────────────────────────────────────

    def _log(self, direction: str, frame: dict[str, Any]) -> None:
        if direction == "send" and frame.get("images"):
            frame = {**frame, "images": f"<{len(frame['images'])} image(s)>"}
        entry = {"ts": time.time(), "dir": direction, "frame": frame}
        try:
            with self._log_lock, open(self.protocol_log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 - logging must never break a turn
            pass


# ── the standing track: how a firing reaches prime-agent ─────────────


def scheduled_jobs(session_dir: Path) -> list[dict[str, Any]]:
    """Jobs the agent registered with prime-agent's own scheduler.

    They live per session in ``session-artifacts/<session-id>/
    scheduled-jobs.json`` (`docs/daemon.md`, "Scheduling"), whether created
    through the CLI (`prime-agent schedule add`), the RPC `add_schedule`
    command or a heartbeat.
    """
    jobs: list[dict[str, Any]] = []
    for path in sorted(session_dir.rglob("scheduled-jobs.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for job in (data.get("jobs") if isinstance(data, dict) else None) or []:
            if isinstance(job, dict):
                jobs.append(job)
    return jobs


def scrub_archive(agent_dir: Path) -> list[str]:
    """Reduce the archived agent dir to evidence.

    `models.json` carries the OpenRouter key verbatim (prime-agent's
    provider config has no env-reference form), so the key is replaced
    before a results directory can be committed; the CLI shim, daemon
    descriptors, logs and caches are machine state with no evidentiary value.
    """
    actions: list[str] = []
    models = agent_dir / "models.json"
    if models.exists():
        try:
            data = json.loads(models.read_text(encoding="utf-8"))
            for provider in (data.get("providers") or {}).values():
                if isinstance(provider, dict) and "apiKey" in provider:
                    provider["apiKey"] = "<redacted: OPENROUTER_API_KEY>"
            models.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            actions.append("redacted models.json apiKey")
        except (OSError, ValueError):
            models.unlink()
            actions.append("removed unreadable models.json")
    for name in ("bin", "daemon", "logs", "cache", "tmp"):
        target = agent_dir / name
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            actions.append(f"removed {name}/")
    return actions


def snapshot(agent_dir: Path, session_dir: Path, workspace: Path) -> dict[str, Any]:
    """What the agent persisted: skills, extensions, memory, jobs, files."""
    from colleague.arms.opencode import discover_scripts, workspace_files

    def listing(root: Path) -> list[str]:
        if not root.exists():
            return []
        return sorted(
            str(p.relative_to(root))
            for p in root.rglob("*")
            if p.is_file() and "node_modules" not in p.parts and p.name != "models.json"
        )

    return {
        "agent_dir_files": [
            f
            for f in listing(agent_dir)
            if not f.startswith(("bin/", "daemon", "logs/"))
        ],
        "workspace_files": workspace_files(workspace),
        "scripts": [p.name for p in discover_scripts(workspace)],
        "scheduled_jobs": [
            {k: job.get(k) for k in ("id", "status", "schedule", "prompt", "label")}
            for job in scheduled_jobs(session_dir)
        ],
    }
