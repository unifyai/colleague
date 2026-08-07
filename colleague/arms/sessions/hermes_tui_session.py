"""hermes-agent's TUI gateway as a conversational session.

The `hermes` arm drives `hermes chat -Q -q`, a one-shot headless turn with no
way to reach work that has already started. That is real, but it is not the
whole product: hermes documents the TUI gateway JSON-RPC protocol
(`python -m tui_gateway.entry`, website/docs/developer-guide/
programmatic-integration.md) as a public integration surface, and it is the
protocol hermes's own Ink TUI and desktop app speak. This arm speaks it too,
so the faithful capabilities become measurable:

    prompt.submit     returns at ``{"status": "streaming"}``; the final text
                      arrives as a ``message.complete`` event
    session.steer     injects into the running tool batch (AIAgent.steer) —
                      a live interjection, no restart
    session.redirect  replaces the in-flight model call when steer is refused
    clarify.request   a real blocking question channel (tools/clarify);
                      answered via ``clarify.respond {request_id, answer}``
    session.resume    continues the same SQLite session rows the CLI writes

Wire format: newline-delimited JSON-RPC 2.0 on stdin/stdout. Responses carry
the request ``id``; events arrive as notifications
``{"method": "event", "params": {"type", "session_id", "payload"}}``. A
daemon reader thread routes responses to per-request waiters and events to
the session's turn tracker, so a blocking prompt (clarify/approval/sudo) can
be answered while a turn is still streaming.

Approvals are configured off at the source (``approvals.mode: "off"`` in the
throwaway profile's config.yaml — hermes's own yolo mode) because a benchmark
harness auto-approving everything is the same policy with an extra round
trip. The handlers for ``approval.request`` (approve once) and
``sudo.request``/``secret.request`` (decline) stay wired as a backstop so the
agent can never hang on a prompt this adapter did not anticipate.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from typing import Any

from colleague.arms.hermes import (
    BENCH_MODEL,
    CONFIG_TEMPLATE,
    HERMES_REPO,
    _hermes_env,
    defuse_hermes_artifacts,
)
from colleague.arms.sessions import register
from colleague.arms.sessions.cli_base import CliSession
from colleague.harness.capability import PROFILES
from colleague.harness.session import Reply, RunHandle, compose

#: Cold gateway start pays Python + hermes imports before ``gateway.ready``.
_READY_TIMEOUT_S = 120.0

#: Control-plane RPCs (create/steer/close) answer from memory; anything this
#: slow means the gateway is wedged, and waiting longer will not unwedge it.
_RPC_TIMEOUT_S = 60.0

#: A bare ``error`` event is usually followed by a terminal ``message.complete``
#: frame (status="error"); some paths (turn cancelled before the agent was
#: ready) emit only the event. Give the terminal frame a moment, then fail.
_ERROR_GRACE_S = 10.0

#: YAML 1.1 parses bare ``off`` as False; hermes normalizes that too
#: (tools/approval.py _normalize_approval_mode), but the quoted form states
#: the intent. Appended to the same CONFIG_TEMPLATE the CLI arm writes.
_APPROVALS_OFF = 'approvals:\n  mode: "off"\n'


class GatewayError(RuntimeError):
    """An RPC failed: error response, timeout, or the gateway died."""


class _Pending:
    """One in-flight request: the waiter parks here until the reader thread
    delivers the response frame."""

    __slots__ = ("event", "response")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.response: dict[str, Any] | None = None


class _Turn:
    """One submitted prompt, resolved by its ``message.complete`` event."""

    __slots__ = ("done", "payload", "error", "error_at", "submit_status")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.payload: dict[str, Any] | None = None
        self.error: str | None = None
        self.error_at: float | None = None
        self.submit_status: str = ""


class _TuiRunHandle(RunHandle):
    """A turn that is streaming inside the gateway process."""

    def __init__(self, session: "HermesTuiSession", turn: _Turn) -> None:
        self._session = session
        self._turn = turn

    def wait(self, timeout: float = 900.0) -> Reply:
        return self._session._wait_turn(self._turn, timeout)

    def interject(self, text: str, *, sender: str | None = None) -> dict[str, Any]:
        return self._session.interject(text, sender=sender)

    def stop(self) -> None:
        self._session._interrupt()

    @property
    def done(self) -> bool:
        return self._turn.done.is_set()


class HermesTuiSession(CliSession):
    arm = "hermes-tui"
    profile = PROFILES["hermes-tui"]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._proc: subprocess.Popen | None = None
        self._stderr_log = None
        self._reader: threading.Thread | None = None
        self._ready = threading.Event()
        self._alive = False
        self._session_id = ""
        self._stored_session_id = ""
        self._next_id = 0
        self._id_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._pending_lock = threading.Lock()
        self._turns: list[_Turn] = []
        self._turn_lock = threading.Lock()
        self._responder = None
        self._clarifications: list[dict[str, Any]] = []
        self._prompt_events: list[dict[str, Any]] = []
        self.protocol_log = self.results_dir / "hermes_tui_protocol.jsonl"
        self._log_lock = threading.Lock()

    # ── lifecycle ────────────────────────────────────────────────────

    def setup(self) -> None:
        python = HERMES_REPO / ".venv" / "bin" / "python"
        if not python.exists():
            raise SystemExit(f"hermes venv missing — run `uv sync` in {HERMES_REPO}")
        if not (HERMES_REPO / "tui_gateway" / "entry.py").exists():
            raise SystemExit(f"tui_gateway package missing under {HERMES_REPO}")
        self.home = self.results_dir / "hermes_home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.workdir = self.results_dir / "workspace"
        self.workdir.mkdir(parents=True, exist_ok=True)
        (self.home / "config.yaml").write_text(
            CONFIG_TEMPLATE.format(model=BENCH_MODEL) + _APPROVALS_OFF,
            encoding="utf-8",
        )

        # The production TUI spawns the gateway exactly this way
        # (ui-tui/src/gatewayClient.ts startSpawnedGateway): repo on
        # PYTHONPATH, HERMES_PYTHON_SRC_ROOT for the import guard, cwd at the
        # repo root. The isolation envelope is the same one the CLI arm uses.
        env = _hermes_env(self.home, self.workdir, self.proxy_base_url)
        env["PYTHONPATH"] = str(HERMES_REPO)
        env["HERMES_PYTHON_SRC_ROOT"] = str(HERMES_REPO)
        if cert := os.environ.get("SSL_CERT_FILE"):
            env["SSL_CERT_FILE"] = cert

        self._stderr_log = open(self.log_path, "a", encoding="utf-8")
        self._proc = subprocess.Popen(
            [str(python), "-m", "tui_gateway.entry"],
            cwd=str(HERMES_REPO),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr_log,
            text=True,
            bufsize=1,
        )
        self._alive = True
        self._reader = threading.Thread(
            target=self._read_loop,
            name="hermes-tui-reader",
            daemon=True,
        )
        self._reader.start()

        if not self._ready.wait(_READY_TIMEOUT_S):
            self.close()
            raise GatewayError(
                f"gateway.ready never arrived within {_READY_TIMEOUT_S}s "
                f"(see {self.log_path})"
            )
        created = self._rpc(
            "session.create",
            {"cols": 120, "cwd": str(self.workdir)},
        )
        self._session_id = str(created.get("session_id") or "")
        self._stored_session_id = str(created.get("stored_session_id") or "")
        if not self._session_id:
            raise GatewayError(f"session.create returned no session_id: {created}")

    def close(self) -> None:
        proc = self._proc
        if proc is not None:
            if proc.poll() is None and self._session_id:
                try:
                    self._rpc(
                        "session.close",
                        {"session_id": self._session_id},
                        timeout=10.0,
                    )
                except Exception:  # noqa: BLE001 - teardown is best-effort
                    pass
            # There is no shutdown RPC in the protocol; the gateway's main
            # loop exits on stdin EOF and runs its own orderly shutdown
            # (entry.py), so closing stdin IS the graceful path.
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:  # noqa: BLE001
                    proc.kill()
            self._proc = None
        if self._stderr_log is not None:
            try:
                self._stderr_log.close()
            except Exception:  # noqa: BLE001
                pass
            self._stderr_log = None
        try:
            defuse_hermes_artifacts(self.home)
        except Exception:  # noqa: BLE001 - teardown is best-effort
            pass
        super().close()

    # ── the session interface ────────────────────────────────────────

    def begin(
        self,
        text: str,
        *,
        persist: bool = False,
        context: str | None = None,
        sender: str | None = None,
    ) -> RunHandle:
        # The gateway persists every session to SQLite regardless of
        # `persist`; `resume()` continues the same stored session.
        del persist
        prompt = compose(context, text if sender is None else f"[{sender}] {text}")
        return self._submit(prompt)

    def interject(self, text: str, *, sender: str | None = None) -> dict[str, Any]:
        """Reach the running turn through hermes's own steering channel.

        `session.steer` mirrors AIAgent.steer: the text lands on the next tool
        batch's last result, no interrupt, no restart. When steer is refused
        (no batch to land on), `session.redirect` replaces the in-flight model
        call while preserving valid work; with no active turn either RPC
        reports it, and the returned dict records what actually happened
        instead of pretending delivery.
        """
        message = text if sender is None else f"[{sender}] {text}"
        record: dict[str, Any] = {
            "delivered": False,
            "mode": "live_interject",
            "text": message,
        }
        try:
            result = self._rpc(
                "session.steer",
                {"session_id": self._session_id, "text": message},
            )
            record["steer"] = result.get("status")
            if result.get("status") == "queued":
                record["delivered"] = True
                record["method"] = "session.steer"
                return record
        except GatewayError as exc:
            record["steer_error"] = str(exc)
        try:
            result = self._rpc(
                "session.redirect",
                {"session_id": self._session_id, "text": message},
            )
            record["redirect"] = result.get("status")
            if result.get("status") in ("redirected", "queued"):
                record["delivered"] = True
                record["method"] = "session.redirect"
                return record
        except GatewayError as exc:
            record["redirect_error"] = str(exc)
        record["mode"] = "none"
        return record

    def resume(self, text: str, *, sender: str | None = None) -> Reply:
        """Continue the stored session through the gateway's own resume."""
        target = self._stored_session_id
        if target:
            try:
                resumed = self._rpc(
                    "session.resume",
                    {"session_id": target, "cols": 120},
                )
                self._session_id = str(resumed.get("session_id") or self._session_id)
                self._stored_session_id = str(resumed.get("session_key") or target)
            except GatewayError as exc:
                # A failed resume falls through to a turn on the live session
                # — the protocol log shows the attempt and the failure.
                self._prompt_events.append(
                    {"kind": "resume_error", "target": target, "error": str(exc)},
                )
        prompt = text if sender is None else f"[{sender}] {text}"
        return self._submit(prompt).wait(timeout=self.timeout_s)

    def on_clarification(self, responder) -> None:
        self._responder = responder

    def clarifications(self) -> list[dict[str, Any]]:
        return list(self._clarifications)

    def artifacts(self) -> dict[str, Any]:
        return {
            **super().artifacts(),
            "hermes_home": str(self.home),
            "protocol_log": str(self.protocol_log),
            "session_id": self._session_id,
            "stored_session_id": self._stored_session_id,
            "prompt_events": list(self._prompt_events),
        }

    # ── turns ────────────────────────────────────────────────────────

    def _submit(self, prompt: str) -> _TuiRunHandle:
        turn = _Turn()
        with self._turn_lock:
            # A second begin() while one is streaming is an explicit
            # follow-up, not a correction: `queued: true` pins queue
            # semantics so the busy-input mode can never redirect the live
            # turn with next-turn text (server._handle_busy_submit).
            busy = any(not t.done.is_set() for t in self._turns)
            self._turns.append(turn)
        params: dict[str, Any] = {"session_id": self._session_id, "text": prompt}
        if busy:
            params["queued"] = True
        try:
            result = self._rpc("prompt.submit", params)
            turn.submit_status = str(result.get("status") or "")
        except GatewayError as exc:
            self._finish_turn(
                turn,
                {"text": "", "status": "error", "error": f"prompt.submit: {exc}"},
            )
        return _TuiRunHandle(self, turn)

    def _wait_turn(self, turn: _Turn, timeout: float) -> Reply:
        deadline = time.monotonic() + timeout
        while not turn.done.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return Reply(text="", ok=False, error=f"timed out after {timeout}s")
            if (
                turn.error_at is not None
                and time.monotonic() - turn.error_at > _ERROR_GRACE_S
            ):
                return Reply(
                    text="",
                    ok=False,
                    error=turn.error or "gateway error event",
                )
            if not self._alive:
                return Reply(text="", ok=False, error="gateway process exited")
            turn.done.wait(timeout=min(0.5, remaining))
        payload = turn.payload or {}
        status = str(payload.get("status") or "complete")
        text = str(payload.get("text") or "")
        meta: dict[str, Any] = {"status": status}
        if turn.submit_status:
            meta["submit_status"] = turn.submit_status
        if payload.get("usage"):
            meta["usage"] = payload["usage"]
        return Reply(
            text=text,
            ok=status != "error",
            error=str(payload.get("error") or "") if status == "error" else "",
            raw=payload,
            meta=meta,
        )

    def _finish_turn(self, turn: _Turn, payload: dict[str, Any]) -> None:
        turn.payload = payload
        turn.done.set()
        with self._turn_lock:
            while self._turns and self._turns[0].done.is_set():
                self._turns.pop(0)

    def _oldest_open_turn(self) -> _Turn | None:
        with self._turn_lock:
            for t in self._turns:
                if not t.done.is_set():
                    return t
        return None

    def _interrupt(self) -> None:
        try:
            self._rpc(
                "session.interrupt",
                {"session_id": self._session_id},
                timeout=10.0,
            )
        except Exception:  # noqa: BLE001 - stop is best-effort by contract
            pass

    # ── wire protocol ────────────────────────────────────────────────

    def _rpc(
        self,
        rpc_method: str,
        params: dict[str, Any],
        timeout: float = _RPC_TIMEOUT_S,
    ) -> dict[str, Any]:
        if self._proc is None or not self._alive:
            raise GatewayError(f"{rpc_method}: gateway is not running")
        with self._id_lock:
            self._next_id += 1
            rid = self._next_id
        pending = _Pending()
        with self._pending_lock:
            self._pending[rid] = pending
        frame = {"jsonrpc": "2.0", "id": rid, "method": rpc_method, "params": params}
        try:
            self._write(frame)
            if not pending.event.wait(timeout):
                raise GatewayError(f"{rpc_method} timed out after {timeout}s")
        finally:
            with self._pending_lock:
                self._pending.pop(rid, None)
        resp = pending.response or {}
        if resp.get("error"):
            err = resp["error"]
            raise GatewayError(
                f"{rpc_method} failed: code {err.get('code')} {err.get('message')}"
            )
        result = resp.get("result")
        return result if isinstance(result, dict) else {}

    def _write(self, frame: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise GatewayError("gateway stdin is closed")
        line = json.dumps(frame, ensure_ascii=False)
        try:
            with self._write_lock:
                proc.stdin.write(line + "\n")
                proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as exc:
            raise GatewayError(f"gateway write failed: {exc}") from exc
        self._log("send", frame)

    def _read_loop(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        for raw in proc.stdout:
            line = raw.strip()
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
            if frame.get("method") == "event":
                try:
                    self._on_event(frame.get("params") or {})
                except Exception:  # noqa: BLE001 - reader must survive
                    pass
            elif "id" in frame:
                with self._pending_lock:
                    pending = self._pending.get(frame["id"])
                if pending is not None:
                    pending.response = frame
                    pending.event.set()
        # EOF: the gateway is gone. Fail everything still waiting on it.
        self._alive = False
        with self._pending_lock:
            for pending in self._pending.values():
                pending.response = {"error": {"code": -1, "message": "gateway exited"}}
                pending.event.set()
            self._pending.clear()
        with self._turn_lock:
            open_turns = [t for t in self._turns if not t.done.is_set()]
        for turn in open_turns:
            self._finish_turn(
                turn,
                {"text": "", "status": "error", "error": "gateway exited mid-turn"},
            )

    # ── events ───────────────────────────────────────────────────────

    def _on_event(self, params: dict[str, Any]) -> None:
        etype = str(params.get("type") or "")
        sid = str(params.get("session_id") or "")
        payload = params.get("payload") or {}
        if etype == "gateway.ready":
            self._ready.set()
            return
        # Subagent watch mirrors emit message.complete under their own child
        # session ids; only our session's events resolve our turns.
        if sid and self._session_id and sid != self._session_id:
            return
        if etype == "message.complete":
            turn = self._oldest_open_turn()
            if turn is not None:
                self._finish_turn(turn, dict(payload))
        elif etype == "error":
            turn = self._oldest_open_turn()
            if turn is not None and turn.error_at is None:
                turn.error = str(payload.get("message") or "gateway error")
                turn.error_at = time.monotonic()
        elif etype == "clarify.request":
            self._spawn(self._answer_clarify, payload)
        elif etype == "approval.request":
            self._spawn(self._answer_approval, payload)
        elif etype in ("sudo.request", "secret.request", "terminal.read.request"):
            self._spawn(self._decline_prompt, etype, payload)

    def _spawn(self, fn, *args: Any) -> None:
        """Blocking prompts must not block the reader thread that would carry
        their own response frames, so each answer runs on its own thread."""
        threading.Thread(target=fn, args=args, daemon=True).start()

    def _answer_clarify(self, payload: dict[str, Any]) -> None:
        question = str(payload.get("question") or "")
        choices = [str(c) for c in (payload.get("choices") or [])]
        request_id = str(payload.get("request_id") or "")
        asked = (
            question
            if not choices
            else (question + "\nOptions: " + " | ".join(choices))
        )
        responder = self._responder
        answer = responder(asked) if responder is not None else "No answer available."
        self._clarifications.append(
            {
                "question": question,
                "choices": choices,
                "answer": answer,
                "request_id": request_id,
            },
        )
        try:
            self._rpc(
                "clarify.respond",
                {"request_id": request_id, "answer": answer},
            )
        except GatewayError:
            pass  # expired server-side; the tool already returned empty

    def _answer_approval(self, payload: dict[str, Any]) -> None:
        """Backstop: approvals are configured off in config.yaml, but if one
        fires anyway, approve this action only. approval.respond resolves by
        session, not request_id (tools/approval resolve_gateway_approval)."""
        record = {"kind": "approval", "payload": dict(payload), "choice": "once"}
        try:
            self._rpc(
                "approval.respond",
                {"session_id": self._session_id, "choice": "once"},
            )
        except GatewayError as exc:
            record["error"] = str(exc)
        self._prompt_events.append(record)

    def _decline_prompt(self, etype: str, payload: dict[str, Any]) -> None:
        """sudo wants a real password and secrets want real credentials; a
        benchmark has neither, and an empty answer is each bridge's documented
        skip path (tools resolve it as declined, the agent moves on)."""
        request_id = str(payload.get("request_id") or "")
        respond_method, key = {
            "sudo.request": ("sudo.respond", "password"),
            "secret.request": ("secret.respond", "value"),
            "terminal.read.request": ("terminal.read.respond", "text"),
        }[etype]
        record = {"kind": etype, "request_id": request_id, "answer": ""}
        try:
            self._rpc(respond_method, {"request_id": request_id, key: ""})
        except GatewayError as exc:
            record["error"] = str(exc)
        self._prompt_events.append(record)

    # ── transcript ───────────────────────────────────────────────────

    def _log(self, direction: str, frame: dict[str, Any]) -> None:
        entry = {"ts": time.time(), "dir": direction, "frame": frame}
        try:
            with self._log_lock, open(self.protocol_log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 - logging must never break a turn
            pass


register("hermes-tui", HermesTuiSession)
