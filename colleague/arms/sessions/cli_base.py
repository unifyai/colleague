"""Shared plumbing for the process-driven arms.

The hermes, OpenClaw, prime-agent and OpenCode adapters all spawn their
harness as a subprocess, metered by the same local recording proxy in front
of OpenRouter. What differs is the command line, the isolation envelope,
and — the part these tracks care about — whether anything can reach a run
that has already started.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from colleague.arms.proxy import RecordingProxy
from colleague.harness.attachments import attachment_note, materialize
from colleague.harness.ledger import PhaseLedger
from colleague.harness.session import ArmSession, Reply


class CliSession(ArmSession):
    """Run directory, recording proxy and phase ledger, shared by three arms."""

    arm: str = ""

    def __init__(
        self,
        *,
        results_dir: Path,
        run_id: str | None = None,
        proxy_port: int = 0,
        timeout_s: float = 900.0,
        transport: str = "text",
    ) -> None:
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise SystemExit("OPENROUTER_API_KEY is required to meter this arm")
        self.run_id = run_id or (
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ") + f"-{self.arm}"
        )
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_s = timeout_s
        #: The transport the runner intends ("text" | "voice"). Boot-time
        #: information only: an arm whose product must be *configured* to
        #: field a call (OpenClaw's voice-call plugin) reads it in setup();
        #: it never substitutes for the per-scenario voice availability probe.
        self.transport = transport
        self.log_path = self.results_dir / f"{self.arm}_cli.log"
        self.ledger_path = self.results_dir / "proxy_ledger.jsonl"
        self.proxy = RecordingProxy(
            port=proxy_port,
            ledger_path=self.ledger_path,
        ).start()
        self.ledger = PhaseLedger(self.ledger_path)

    @property
    def proxy_base_url(self) -> str:
        return self.proxy.base_url

    def take_attachments(self, text: str, attachments: list[str] | None) -> str:
        """Materialise shared files into the workspace; extend the message.

        The workspace analogue of a chat surface saving an attachment to
        disk: the files land under ``workspace/attachments/`` and the one
        harness-composed sentence tells the arm where. Received paths are
        remembered so the deliverable collector never mistakes an input the
        harness placed for work the arm produced.
        """
        if not attachments:
            return text
        workspace = getattr(self, "workspace", None)
        if workspace is None:
            raise RuntimeError(f"{self.arm}: attachments before setup()")
        landed = materialize(attachments, Path(workspace) / "attachments")
        self.received_attachments = getattr(self, "received_attachments", set())
        self.received_attachments.update(p.resolve() for p in landed)
        return f"{text}\n\n{attachment_note([str(p) for p in landed])}"

    def _reply(self, code: int, text: str) -> Reply:
        return Reply(
            text=text,
            ok=code == 0,
            error="" if code == 0 else f"exit code {code}",
            meta={"exit_code": code},
        )

    def close(self) -> None:
        try:
            self.proxy.stop()
        except Exception:  # noqa: BLE001 - teardown is best-effort
            pass

    def cost_snapshot(self) -> dict[str, Any]:
        return self.ledger.cost_snapshot()

    def artifacts(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "results_dir": str(self.results_dir),
            "ledger": str(self.ledger_path),
        }
