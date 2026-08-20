"""Shared plumbing for the three CLI-driven arms.

hermes, OpenClaw and OpenCode are all "spawn a process, wait, read stdout",
metered by the same local recording proxy in front of OpenRouter. What
differs is the command line, the isolation envelope, and — the part these
tracks care about — whether anything can reach a run that has already
started.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from colleague.arms.proxy import RecordingProxy
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

    def artifacts(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "results_dir": str(self.results_dir),
            "ledger": str(self.ledger_path),
        }
