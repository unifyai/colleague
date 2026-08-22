"""prime-agent through its JSONL-RPC surface.

Print mode (`pi -p`, one process per turn, sessions continued with `-c`)
cannot reach a running turn. The product's steering and follow-up lanes —
`core/session-action-store.ts`: ``QueuedMessageLane = "steering" |
"followUp"``, delivery policy ``next_turn_boundary`` for steering and
``when_run_idle`` for follow-ups — live on its interactive TUI and on RPC
mode (`docs/rpc.md`), the documented headless integration surface for
"embedding the agent in other applications, IDEs, or custom UIs". This arm
speaks that, through the transport in `colleague/arms/prime_agent.py`:

    prompt          the response arrives once the prompt is accepted; the
                    turn streams as events and ends at ``agent_end`` — or,
                    when a steer was queued against it, at the end of the
                    continuation run the runtime pumps for that steer
    steer           the steering lane: "delivered after the current
                    assistant turn finishes executing its tool calls, before
                    the next LLM call". Never an abort, never a restart.
    abort           stops the current operation
    the same file   continuity: one long-lived process holds one session,
                    persisted to the run-local session dir; a later prompt on
                    it is a warm turn

Isolation: a throwaway agent dir with the proxy-metered provider, a
run-local session dir, a scratch workspace, and a per-session daemon socket
that is shut down on close. The product's skills, extensions, prompt
templates and context files stay enabled: nothing is preloaded in the
throwaway agent dir, so the arm still reasons from the request alone, but
what it writes during a track is picked up the way the product would pick
it up.

There is no ask-the-user tool anywhere in prime-agent (`side-question` runs
the other way), so ``clarification`` stays false and no channel is faked.

Live outcomes recorded in NOTE.md beside this file's first runs.
"""

from __future__ import annotations

from typing import Any

from colleague.arms.prime_agent import PrimeAgentRpc, RpcError, Turn, scrub_archive
from colleague.arms.sessions import register
from colleague.arms.sessions.cli_base import CliSession
from colleague.harness.capability import PROFILES
from colleague.harness.session import Reply, RunHandle, compose


class _RpcRunHandle(RunHandle):
    """A prompt in flight, plus any turns a scene started on the idle agent."""

    def __init__(self, session: "PrimeAgentRpcSession", turn: Turn) -> None:
        self._session = session
        self._turn = turn
        self.followers: list[Turn] = []

    def wait(self, timeout: float = 900.0) -> Reply:
        return self._session._wait_handle(self, timeout)

    def interject(self, text: str, *, sender: str | None = None) -> dict[str, Any]:
        return self._session._interject(self, text, sender=sender)

    def stop(self) -> None:
        self._session._rpc.abort()

    @property
    def done(self) -> bool:
        return self._turn.done.is_set() and all(f.done.is_set() for f in self.followers)


class PrimeAgentRpcSession(CliSession):
    arm = "prime-agent-rpc"
    profile = PROFILES["prime-agent-rpc"]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._rpc: PrimeAgentRpc | None = None
        self._steer_log: list[dict[str, Any]] = []
        self.protocol_log = self.results_dir / "prime_agent_rpc_protocol.jsonl"

    # ── lifecycle ────────────────────────────────────────────────────

    def setup(self) -> None:
        self.agent_dir = self.results_dir / "prime_agent_dir"
        self.session_dir = self.results_dir / "prime_sessions"
        self.workspace = self.results_dir / "workspace"
        self._rpc = PrimeAgentRpc(
            agent_dir=self.agent_dir,
            session_dir=self.session_dir,
            workspace=self.workspace,
            proxy_base_url=self.proxy_base_url,
            stderr_log=self.log_path,
            protocol_log=self.protocol_log,
        ).start()

    def close(self) -> None:
        if self._rpc is not None:
            try:
                self._rpc.close()
            except Exception:  # noqa: BLE001 - teardown is best-effort
                pass
        try:
            scrub_archive(self.agent_dir)
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
        del persist  # one process, one session: it persists by construction
        assert self._rpc is not None, "call setup() first"
        text = self.take_attachments(text, attachments)
        prompt = compose(context, text if sender is None else f"[{sender}] {text}")
        return _RpcRunHandle(self, self._rpc.submit(prompt, images=images))

    def resume(
        self,
        text: str,
        *,
        sender: str | None = None,
        attachments: list[str] | None = None,
    ) -> Reply:
        assert self._rpc is not None, "call setup() first"
        text = self.take_attachments(text, attachments)
        prompt = text if sender is None else f"[{sender}] {text}"
        return _RpcRunHandle(self, self._rpc.submit(prompt)).wait(
            timeout=self.timeout_s,
        )

    def artifacts(self) -> dict[str, Any]:
        rpc = self._rpc
        return {
            **super().artifacts(),
            "agent_dir": str(self.agent_dir),
            "session_dir": str(self.session_dir),
            "workspace": str(self.workspace),
            "protocol_log": str(self.protocol_log),
            "session_file": rpc.session_file if rpc else "",
            "steers": list(self._steer_log),
            "ui_events": list(rpc.ui_events) if rpc else [],
        }

    # ── turns ────────────────────────────────────────────────────────

    def _wait_handle(self, handle: _RpcRunHandle, timeout: float) -> Reply:
        """Wait for the prompt and for every turn a scene started meanwhile."""
        import time

        rpc = self._rpc
        assert rpc is not None
        deadline = time.monotonic() + timeout
        turn = handle._turn
        why = rpc.wait(turn, max(0.0, deadline - time.monotonic()))
        if why == "timeout":
            return Reply(text="", ok=False, error=f"timed out after {timeout}s")
        if why == "exited":
            return Reply(text="", ok=False, error="prime-agent rpc process exited")
        # Followers can keep arriving while earlier ones are drained (a scene
        # speaks several lines); loop until the list stops growing.
        waited = 0
        while waited < len(handle.followers):
            follower = handle.followers[waited]
            waited += 1
            why = rpc.wait(follower, max(0.0, deadline - time.monotonic()))
            if why:
                return Reply(
                    text=turn.text,
                    ok=False,
                    error=f"{why} waiting for a follow-on turn",
                )
        texts = [turn.text] + [f.text for f in handle.followers if f.text]
        return Reply(
            text="\n\n".join(t for t in texts if t),
            ok=not turn.error,
            error=turn.error,
            raw=turn.messages,
            meta={
                "agent_runs": turn.runs,
                "followers": [
                    {"runs": f.runs, "error": f.error} for f in handle.followers
                ],
            },
        )

    def _interject(
        self,
        handle: _RpcRunHandle,
        text: str,
        *,
        sender: str | None,
    ) -> dict[str, Any]:
        """Reach the running turn through prime-agent's steering lane.

        With a run streaming, ``steer`` queues on the steering lane
        (delivery policy ``next_turn_boundary``: after the current assistant
        turn's tool calls, before the next model call). With nothing running
        the message is an ordinary prompt to an idle agent, recorded as such.
        """
        rpc = self._rpc
        assert rpc is not None
        message = text if sender is None else f"[{sender}] {text}"
        record: dict[str, Any] = {"delivered": False, "text": message}
        streaming = rpc.streaming
        try:
            if not streaming:
                follower = rpc.submit(message)
                if follower.error and "already processing" in follower.error:
                    # A continuation run started between the check and the
                    # prompt; the runtime is busy after all — steer it.
                    streaming = True
                    rpc.finish_turn(follower)
                else:
                    handle.followers.append(follower)
                    record.update(
                        delivered=True,
                        mode="new_turn",
                        note="no run was active; the message starts a turn on the idle agent",
                    )
            if streaming:
                rpc.steer(message, target=rpc.current_turn() or handle._turn)
                record.update(
                    delivered=True,
                    mode="live_interject",
                    lane="steering",
                    delivery_policy="next_turn_boundary",
                    note=(
                        "prime-agent steering lane: delivered after the current "
                        "assistant turn finishes executing its tool calls, before "
                        "the next LLM call (docs/rpc.md, session-action-store.ts); "
                        "the runtime pumps it as the next agent run in the same "
                        "session."
                    ),
                )
        except RpcError as exc:
            record["mode"] = "delivery_failed"
            record["error"] = str(exc)
        self._steer_log.append(dict(record))
        return record


register("prime-agent-rpc", PrimeAgentRpcSession)
