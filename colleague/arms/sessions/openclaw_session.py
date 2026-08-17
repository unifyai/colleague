"""OpenClaw as a conversational session.

OpenClaw keeps sessions, so a follow-up lands in the same context rather
than cold — which makes it the only comparison arm with a real answer for
the `continuity` track.

Steering is the interesting case. A second `agent` call against a session
that is mid-turn does not reach the running turn; it lands after it. That
is `QUEUED_FOLLOWUP`, and it is materially different from an interjection:
by the time the correction is read, whatever the first turn was going to do
has already happened. The `interruption` track measures exactly that gap,
and OpenClaw is the arm that shows the difference between "has a session"
and "can be interrupted".
"""

from __future__ import annotations

from typing import Any

from colleague.arms.openclaw import (
    BENCH_MODEL,
    GatewayProcess,
    defuse_openclaw_artifacts,
    extract_json,
    run_openclaw,
    scrub_state_archive,
    write_openclaw_config,
)
from colleague.arms.sessions import register
from colleague.arms.sessions.cli_base import CliSession
from colleague.harness.capability import PROFILES
from colleague.harness.session import (
    Reply,
    RunHandle,
    ThreadedRunHandle,
    Unsupported,
    compose,
)


class _OpenClawRun(ThreadedRunHandle):
    """A turn, plus the ability to queue the next one against the session."""

    def __init__(self, session: "OpenClawSession", fn, *args: Any) -> None:
        self._session = session
        super().__init__(fn, *args)

    def interject(self, text: str, *, sender: str | None = None) -> dict[str, Any]:
        message = text if sender is None else f"[{sender}] {text}"
        self._session.queue_followup(message)
        return {
            "delivered": True,
            "mode": "queued_followup",
            "note": (
                "OpenClaw has no mid-turn channel; this lands as the next "
                "turn on the same session, after the current one completes."
            ),
        }


class OpenClawSession(CliSession):
    arm = "openclaw"
    profile = PROFILES["openclaw"]

    def __init__(
        self,
        *,
        gateway_port: int = 0,
        session_id: str = "colleague",
        **kw: Any,
    ) -> None:
        super().__init__(**kw)
        self.gateway_port = gateway_port or 8790
        self.session_id = session_id
        self._queued: list[str] = []
        self._gateway: GatewayProcess | None = None

    def setup(self) -> None:
        self.state_dir = self.results_dir / "openclaw_state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.workspace = self.results_dir / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        write_openclaw_config(
            self.state_dir,
            proxy_base_url=self.proxy_base_url,
            workspace=self.workspace,
            model=BENCH_MODEL,
        )
        self._gateway = GatewayProcess(
            state_dir=self.state_dir,
            gateway_port=self.gateway_port,
            log_path=self.results_dir / "gateway.log",
        )
        self._gateway.start()

    def _turn(self, prompt: str) -> Reply:
        code, out = run_openclaw(
            [
                "agent",
                "--session-id",
                self.session_id,
                "-m",
                prompt,
                "--json",
                "--timeout",
                str(int(self.timeout_s)),
            ],
            state_dir=self.state_dir,
            gateway_port=self.gateway_port,
            log_path=self.log_path,
            timeout_s=self.timeout_s,
        )
        parsed = extract_json(out)
        text = out
        if isinstance(parsed, dict):
            text = str(parsed.get("response") or parsed.get("text") or out)
        reply = self._reply(code, text)

        # Anything queued while this turn was running is delivered now,
        # which is the whole shape of the arm's steering story.
        while self._queued:
            followup = self._queued.pop(0)
            code, out = run_openclaw(
                [
                    "agent",
                    "--session-id",
                    self.session_id,
                    "-m",
                    followup,
                    "--json",
                    "--timeout",
                    str(int(self.timeout_s)),
                ],
                state_dir=self.state_dir,
                gateway_port=self.gateway_port,
                log_path=self.log_path,
                timeout_s=self.timeout_s,
            )
            reply.meta.setdefault("followups", []).append(
                {"text": followup, "exit_code": code, "tail": out[-1200:]},
            )
        return reply

    def queue_followup(self, text: str) -> None:
        self._queued.append(text)

    def begin(
        self,
        text: str,
        *,
        persist: bool = False,
        context: str | None = None,
        sender: str | None = None,
        images: list[str] | None = None,
    ) -> RunHandle:
        del persist  # OpenClaw sessions persist by default
        if images:
            raise Unsupported(
                "this arm's driver has no way to attach an image to a turn",
            )
        prompt = compose(context, text if sender is None else f"[{sender}] {text}")
        return _OpenClawRun(self, self._turn, prompt)

    def close(self) -> None:
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

    def artifacts(self) -> dict[str, Any]:
        return {**super().artifacts(), "state_dir": str(self.state_dir)}


register("openclaw", OpenClawSession)
