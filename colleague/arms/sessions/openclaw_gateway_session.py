"""OpenClaw's Gateway as a conversational session.

The `openclaw` arm drives `openclaw agent -m` — one headless turn per
process against a private Gateway. That surface has no way into a running
turn and nobody to answer a question, so it lands corrections as the next
turn and resolves UNSUPPORTED on clarification. OpenClaw at HEAD documents
both capabilities on its Gateway — the control plane every product client
speaks (`docs/gateway/protocol.md`) — and this arm drives that instead, the
way `hermes-tui` drives hermes's gateway rather than its one-shot CLI:

    chat.send            starts a turn on the session and acks
                         ``{runId, status: "started"}`` before any model
                         call; the reply is the ``chat`` event with
                         ``state: "final"`` for that runId
    chat.send + steer    ``queueMode: "steer"`` with the active run's
                         ``expectedRunId``: the product's default queue mode
                         (`docs/concepts/queue-steering.md`). The text is
                         drained into the active run at its next model or
                         tool-launch boundary — a running tool finishes,
                         the unstarted sequential tail is skipped with
                         synthetic results, and the steer is model-visible
                         before the next tool starts. Never a restart.
    question.requested   the blocking `ask_user` tool (`docs/tools/ask-user`)
                         surfaces as a Gateway event; the answer goes back
                         through ``question.resolve``, the same method the
                         Control UI and the channels use
    chat.abort           stops the active run
    the same sessionKey  continuity: OpenClaw persists every session, and a
                         later ``chat.send`` on the key is a warm turn

Wire format: JSON frames over a WebSocket, spoken from the standard library
by `colleague/arms/openclaw_gateway.py`. The state directory, workspace,
config template, managed Gateway process and post-run defuse are the CLI
arm's own (`colleague/arms/openclaw.py`); the only config difference is a
pinned ``gateway.auth.token`` so the operator client can authenticate.

What this surface does not carry, and the profile says so: a per-sender
identity the model can see. OpenClaw attributes senders inside *channel*
envelopes; on the Gateway's own chat surface "steering does not split
messages by sender" (queue-steering.md) and turn attribution is best-effort
(`docs/concepts/multi-user.md`). Senders therefore reach this arm as text,
``[name] message``, exactly as they reach `hermes-tui`.

Approvals: the run's exec approvals are whatever the CLI arm's identical
config yields; an ``exec.approval.requested`` event, should one fire, is
answered ``allow-once`` and recorded, so a turn can never hang on a prompt
this adapter did not anticipate.

Live outcomes recorded in NOTE.md beside this file's first runs.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from colleague.arms.openclaw import (
    BENCH_MODEL,
    OPENCLAW_REPO,
    GatewayProcess,
    defuse_openclaw_artifacts,
    scrub_state_archive,
    write_openclaw_config,
)
from colleague.arms.openclaw_gateway import GatewayClient, GatewayError, assistant_text
from colleague.arms.sessions import register
from colleague.arms.sessions.cli_base import CliSession
from colleague.harness.capability import PROFILES
from colleague.harness.session import Reply, RunHandle, Unsupported, compose

#: The session every turn lands on. A named session rather than the agent's
#: main one, mirroring the CLI arm's ``--session-id colleague``: the main
#: session is where OpenClaw's heartbeat would run, and a heartbeat turn in
#: the very session under test would be a confound. `ask_user` and steering
#: are available on any primary (non-subagent) session.
SESSION_KEY = "agent:main:colleague"

#: How long `interject` waits to see the steer's own terminal ``chat`` frame,
#: which is what confirms the text was drained into the active run.
_STEER_CONFIRM_S = 5.0

_TERMINAL = ("final", "aborted", "error")


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _Run:
    """One ``chat.send`` and the events that resolve it."""

    __slots__ = (
        "run_id",
        "text",
        "kind",
        "done",
        "ack",
        "state",
        "message",
        "delta",
        "error",
        "usage",
        "submitted_at",
        "ended_at",
    )

    def __init__(self, run_id: str, text: str, kind: str) -> None:
        self.run_id = run_id
        self.text = text
        self.kind = kind  # "turn" | "steer"
        self.done = threading.Event()
        self.ack = ""
        self.state = ""
        self.message: Any = None
        self.delta = ""
        self.error = ""
        self.usage: Any = None
        self.submitted_at = time.time()
        self.ended_at: float | None = None

    def reply_text(self) -> str:
        text = assistant_text(self.message)
        return text if text else self.delta.strip()


class _GatewayRunHandle(RunHandle):
    """A turn streaming inside the Gateway, plus everything steered into it."""

    def __init__(self, session: "OpenClawGatewaySession", run: _Run) -> None:
        self._session = session
        self._run = run
        self.followers: list[_Run] = []

    def wait(self, timeout: float = 900.0) -> Reply:
        return self._session._wait_handle(self, timeout)

    def interject(self, text: str, *, sender: str | None = None) -> dict[str, Any]:
        return self._session._interject(self, text, sender=sender)

    def stop(self) -> None:
        self._session._abort(self._run.run_id)

    @property
    def done(self) -> bool:
        return self._run.done.is_set() and all(f.done.is_set() for f in self.followers)


class OpenClawGatewaySession(CliSession):
    arm = "openclaw-gateway"
    profile = PROFILES["openclaw-gateway"]

    def __init__(
        self,
        *,
        gateway_port: int = 0,
        session_key: str = SESSION_KEY,
        **kw: Any,
    ) -> None:
        super().__init__(**kw)
        # A free port per session: `GatewayProcess.start` sweeps stale
        # listeners off its port, so two sessions on one fixed port would
        # kill each other's Gateway when tracks run in parallel locally.
        self.gateway_port = gateway_port or _free_port()
        self.session_key = session_key
        self._gateway: GatewayProcess | None = None
        self._client: GatewayClient | None = None
        self._token = secrets.token_hex(16)
        self._runs: dict[str, _Run] = {}
        self._runs_lock = threading.Lock()
        self._active: _Run | None = None
        self._handles: list[_GatewayRunHandle] = []
        self._responder = None
        self._clarifications: list[dict[str, Any]] = []
        self._questions_seen: set[str] = set()
        self._prompt_events: list[dict[str, Any]] = []
        self._steer_outcomes: list[dict[str, Any]] = []
        self.protocol_log = self.results_dir / "openclaw_gateway_protocol.jsonl"
        self._log_lock = threading.Lock()

    # ── lifecycle ────────────────────────────────────────────────────

    def setup(self) -> None:
        if not (OPENCLAW_REPO / "dist").is_dir():
            raise SystemExit(
                "OpenClaw build output missing — run `pnpm install && pnpm build` "
                f"in {OPENCLAW_REPO}",
            )
        self.state_dir = self.results_dir / "openclaw_state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.workspace = self.results_dir / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        write_openclaw_config(
            self.state_dir,
            proxy_base_url=self.proxy_base_url,
            workspace=self.workspace,
            model=BENCH_MODEL,
            gateway_auth_token=self._token,
        )
        self._gateway = GatewayProcess(
            state_dir=self.state_dir,
            gateway_port=self.gateway_port,
            log_path=self.results_dir / "gateway.log",
        )
        self._gateway.start()
        self._client = GatewayClient(
            f"ws://127.0.0.1:{self.gateway_port}",
            token=self._token,
            on_event=self._on_event,
            log=self._log,
        )
        self._client.connect()

    def close(self) -> None:
        client = self._client
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - teardown is best-effort
                pass
            self._client = None
        try:
            defuse_openclaw_artifacts(
                self.state_dir,
                self._gateway,
                self.gateway_port,
                self.results_dir / "gateway.log",
            )
            scrub_state_archive(self.state_dir)
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
        images: list[str] | None = None,
        attachments: list[str] | None = None,
    ) -> RunHandle:
        del persist  # OpenClaw persists every session; the key is the continuity
        # Documents go to the workspace, like every CLI arm: the Gateway's
        # chat attachments are an image envelope, and a 30-page PDF is a
        # file the product would save to disk anyway.
        text = self.take_attachments(text, attachments)
        prompt = compose(context, text if sender is None else f"[{sender}] {text}")
        attachments = self._attachments(images)
        run = self._submit(prompt, kind="turn", attachments=attachments)
        handle = _GatewayRunHandle(self, run)
        self._handles.append(handle)
        return handle

    def resume(
        self,
        text: str,
        *,
        sender: str | None = None,
        attachments: list[str] | None = None,
    ) -> Reply:
        """A later turn on the same persisted session — OpenClaw's own continuity."""
        return self.begin(text, sender=sender, attachments=attachments).wait(
            timeout=self.timeout_s,
        )

    def on_clarification(self, responder) -> None:
        self._responder = responder

    def clarifications(self) -> list[dict[str, Any]]:
        return list(self._clarifications)

    def artifacts(self) -> dict[str, Any]:
        return {
            **super().artifacts(),
            "state_dir": str(self.state_dir),
            "protocol_log": str(self.protocol_log),
            "session_key": self.session_key,
            "steer_outcomes": list(self._steer_outcomes),
            "prompt_events": list(self._prompt_events),
        }

    # ── turns ────────────────────────────────────────────────────────

    def _attachments(self, images: list[str] | None) -> list[dict[str, Any]]:
        if not images:
            return []
        out = []
        for path in images:
            p = Path(path)
            mime = mimetypes.guess_type(p.name)[0] or "image/png"
            out.append(
                {
                    "type": "image",
                    "mimeType": mime,
                    "fileName": p.name,
                    "content": base64.b64encode(p.read_bytes()).decode(),
                },
            )
        return out

    def _submit(
        self,
        message: str,
        *,
        kind: str,
        attachments: list[dict[str, Any]] | None = None,
        steer_into: str | None = None,
    ) -> _Run:
        client = self._client
        if client is None:
            raise Unsupported("gateway client is not connected")
        params: dict[str, Any] = {
            "sessionKey": self.session_key,
            "message": message,
            "idempotencyKey": uuid.uuid4().hex,
        }
        if attachments:
            params["attachments"] = attachments
        if steer_into:
            params["queueMode"] = "steer"
            params["expectedRunId"] = steer_into
        ack = client.call("chat.send", params, timeout=120.0)
        run_id = str(ack.get("runId") or "")
        run = _Run(run_id, message, kind)
        run.ack = str(ack.get("status") or "")
        run.state = run.ack
        with self._runs_lock:
            if run_id:
                self._runs[run_id] = run
            if kind == "turn":
                self._active = run
        if not run_id:
            run.state = "error"
            run.error = f"chat.send returned no runId: {ack}"
            run.done.set()
        elif run.state in ("ok", "failed", "killed"):
            # "ok" is a cached/immediately-finalized ack; anything else here
            # is terminal without ever having run.
            if run.state != "ok":
                run.error = f"chat.send acked {run.state}"
            run.done.set()
        return run

    def _wait_run(self, run: _Run, deadline: float) -> bool:
        while not run.done.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            if self._client is not None and not self._client.alive:
                run.state = "error"
                run.error = "gateway connection closed mid-turn"
                run.done.set()
                return True
            run.done.wait(timeout=min(0.5, remaining))
        return True

    def _wait_handle(self, handle: _GatewayRunHandle, timeout: float) -> Reply:
        """Wait for the turn and for everything steered into it.

        A steer that the Gateway drained into the active run finishes with
        that run; one it had to start as its own turn afterwards finishes
        later. Both belong to this handle, so the reply is complete only when
        every run it owns is terminal — the same layered quiescence the CM
        arm drains for.
        """
        deadline = time.monotonic() + timeout
        primary = handle._run
        if not self._wait_run(primary, deadline):
            return Reply(text="", ok=False, error=f"timed out after {timeout}s")
        # Followers can keep arriving while earlier ones are drained (a scene
        # speaks several lines); loop until the list stops growing.
        waited = 0
        while waited < len(handle.followers):
            follower = handle.followers[waited]
            waited += 1
            if not self._wait_run(follower, deadline):
                return Reply(
                    text=primary.reply_text(),
                    ok=False,
                    error=f"timed out after {timeout}s waiting for a steered turn",
                )
        texts = [primary.reply_text()] + [
            f.reply_text() for f in handle.followers if f.reply_text()
        ]
        text = "\n\n".join(t for t in texts if t)
        meta: dict[str, Any] = {
            "run_id": primary.run_id,
            "state": primary.state,
            "followers": [
                {"run_id": f.run_id, "kind": f.kind, "state": f.state}
                for f in handle.followers
            ],
        }
        if primary.usage is not None:
            meta["usage"] = primary.usage
        ok = primary.state == "final"
        return Reply(
            text=text,
            ok=ok,
            error="" if ok else (primary.error or f"run ended {primary.state}"),
            raw=primary.message,
            meta=meta,
        )

    def _interject(
        self,
        handle: _GatewayRunHandle,
        text: str,
        *,
        sender: str | None,
    ) -> dict[str, Any]:
        """Reach the running turn through OpenClaw's own steering queue.

        With an active run the message is sent ``queueMode: "steer"`` bound
        to that run. The Gateway acks it as its own runId and, once it has
        drained the text into the active run at a boundary, closes that runId
        with an empty terminal ``chat`` frame — which is what this records
        as delivered live. If no run is active the message simply starts a
        turn on the idle session, recorded as ``new_turn``.
        """
        message = text if sender is None else f"[{sender}] {text}"
        primary = handle._run
        record: dict[str, Any] = {"delivered": False, "text": message}
        active = None if primary.done.is_set() else primary
        try:
            run = self._submit(
                message,
                kind="steer" if active is not None else "turn",
                steer_into=active.run_id if active is not None else None,
            )
        except GatewayError as exc:
            # The run may have ended between the check and the send; a
            # steer bound to a finished run is refused, so send it as the
            # next turn instead and say so.
            record["steer_error"] = str(exc)
            try:
                run = self._submit(message, kind="turn")
            except GatewayError as exc2:
                record["mode"] = "delivery_failed"
                record["error"] = str(exc2)
                return record
            active = None
        handle.followers.append(run)
        record["run_id"] = run.run_id
        record["ack_status"] = run.ack
        record["delivered"] = True
        if active is None:
            record["mode"] = "new_turn"
            record["note"] = (
                "no run was active; the message starts a turn on the idle session"
            )
            return record

        # Confirm the drain: the steer's own runId is closed by the Gateway
        # (an empty final) as soon as the text has been injected into the
        # active run — before that run's next model call.
        deadline = time.monotonic() + _STEER_CONFIRM_S
        while time.monotonic() < deadline and not run.done.is_set():
            run.done.wait(timeout=0.2)
        landing = (
            "drained_into_active_run"
            if run.done.is_set() and not run.reply_text() and not primary.done.is_set()
            else (
                "active_run_finished_first"
                if primary.done.is_set()
                else "pending_next_boundary"
            )
        )
        record["mode"] = "live_interject"
        record["landing"] = landing
        record["note"] = (
            "OpenClaw steer mode: drained into the active run at its next "
            "model or tool-launch boundary; a running tool call finishes first "
            "and the unstarted tail is skipped (queue-steering.md)."
        )
        self._steer_outcomes.append(
            {
                "steer_run_id": run.run_id,
                "into_run_id": primary.run_id,
                "ack_status": run.ack,
                "landing_at_delivery": landing,
            },
        )
        return record

    def _abort(self, run_id: str) -> None:
        client = self._client
        if client is None:
            return
        try:
            client.call(
                "chat.abort",
                {"sessionKey": self.session_key, "runId": run_id},
                timeout=15.0,
            )
        except Exception:  # noqa: BLE001 - stop is best-effort by contract
            pass

    # ── events ───────────────────────────────────────────────────────

    def _on_event(self, name: str, payload: dict[str, Any]) -> None:
        if name == "chat":
            self._on_chat(payload)
        elif name == "question.requested":
            self._spawn(self._answer_question, payload)
        elif name == "exec.approval.requested":
            self._spawn(self._approve_exec, payload)

    def _on_chat(self, payload: dict[str, Any]) -> None:
        run_id = str(payload.get("runId") or "")
        with self._runs_lock:
            run = self._runs.get(run_id)
        if run is None:
            return
        state = str(payload.get("state") or "")
        if state == "delta":
            delta = payload.get("deltaText")
            if isinstance(delta, str):
                if payload.get("replace"):
                    run.delta = delta
                else:
                    run.delta += delta
            if payload.get("message") is not None:
                run.message = payload.get("message")
            return
        if state in _TERMINAL:
            run.state = state
            if payload.get("message") is not None:
                run.message = payload.get("message")
            if payload.get("usage") is not None:
                run.usage = payload.get("usage")
            if state != "final":
                run.error = str(payload.get("errorMessage") or f"run {state}")
            run.ended_at = time.time()
            # A steer whose runId closes while its target is still running
            # was drained into it; annotate after the fact for the record.
            if run.kind == "steer":
                for entry in self._steer_outcomes:
                    if entry.get("steer_run_id") == run_id and "resolved" not in entry:
                        with self._runs_lock:
                            target = self._runs.get(str(entry.get("into_run_id")))
                        entry["resolved"] = (
                            "drained_into_active_run"
                            if not run.reply_text()
                            and target is not None
                            and not target.done.is_set()
                            else (
                                "own_turn"
                                if run.reply_text()
                                else "closed_after_target"
                            )
                        )
            run.done.set()

    def _spawn(self, fn, *args: Any) -> None:
        threading.Thread(target=fn, args=args, daemon=True).start()

    def _answer_question(self, payload: dict[str, Any]) -> None:
        """Answer an `ask_user` question through the Gateway's own method.

        The whole ask (one to three structured questions with options) is
        put to the scenario's responder as one prompt; the free-text answer
        goes back under every question id — OpenClaw always enables the
        free-text "Other" answer, so no option list constrains a person.
        The tool does not name an addressee, so ``who`` is omitted and the
        scenario's default persona answers.
        """
        qid = str(payload.get("id") or "")
        if not qid or qid in self._questions_seen:
            return
        self._questions_seen.add(qid)
        questions = payload.get("questions") or []
        rendered: list[str] = []
        for q in questions:
            if not isinstance(q, dict):
                continue
            line = str(q.get("question") or "")
            options = [
                str(o.get("label") or "")
                for o in (q.get("options") or [])
                if isinstance(o, dict)
            ]
            if options:
                line += "\nOptions: " + " | ".join(options)
            rendered.append(line)
        asked = "\n\n".join(rendered).strip()
        responder = self._responder
        answer = responder(asked) if responder is not None else "No answer available."
        answer = str(answer)
        entry = {
            "question": asked,
            "answer": answer,
            "question_id": qid,
            "run_id": payload.get("runId"),
            "question_ids": [
                str(q.get("questionId")) for q in questions if isinstance(q, dict)
            ],
        }
        self._clarifications.append(entry)
        client = self._client
        if client is None:
            return
        try:
            client.call(
                "question.resolve",
                {
                    "id": qid,
                    "answers": {
                        "answers": {
                            str(q.get("questionId")): [answer]
                            for q in questions
                            if isinstance(q, dict) and q.get("questionId")
                        },
                    },
                    "resolvedBy": "colleague-persona",
                },
                timeout=30.0,
            )
        except GatewayError as exc:
            entry["resolve_error"] = str(exc)  # expired or cancelled server-side

    def _approve_exec(self, payload: dict[str, Any]) -> None:
        """Backstop: approve one command so a turn cannot hang on a prompt."""
        approval_id = str(payload.get("id") or "")
        record = {"kind": "exec.approval", "id": approval_id, "decision": "allow-once"}
        client = self._client
        if approval_id and client is not None:
            try:
                client.call(
                    "exec.approval.resolve",
                    {"id": approval_id, "decision": "allow-once"},
                    timeout=30.0,
                )
            except GatewayError as exc:
                record["error"] = str(exc)
        self._prompt_events.append(record)

    # ── transcript ───────────────────────────────────────────────────

    def _log(self, direction: str, frame: dict[str, Any]) -> None:
        # Attachments are base64 blobs; keep the log readable.
        if direction == "send" and isinstance(frame.get("params"), dict):
            params = frame["params"]
            if params.get("attachments"):
                frame = {
                    **frame,
                    "params": {
                        **params,
                        "attachments": [
                            {k: v for k, v in a.items() if k != "content"}
                            for a in params["attachments"]
                        ],
                    },
                }
        entry = {"ts": time.time(), "dir": direction, "frame": frame}
        try:
            with self._log_lock, open(self.protocol_log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 - logging must never break a turn
            pass


register("openclaw-gateway", OpenClawGatewaySession)
