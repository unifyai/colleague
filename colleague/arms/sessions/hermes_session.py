"""hermes-agent as a conversational session.

`hermes chat -q` is a one-shot headless turn. There is no loop to address
once it starts, so `interject` raises and the scenario records
`UNSUPPORTED` rather than a failure. Turns are stateless with respect to
each other, which the `continuity` track measures directly: the second
request re-derives everything the first one worked out.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from colleague.arms.hermes import (
    BENCH_MODEL,
    CONFIG_TEMPLATE,
    HERMES_REPO,
    _run_hermes,
    defuse_hermes_artifacts,
)
from colleague.arms.sessions import register
from colleague.arms.sessions.cli_base import CliSession
from colleague.harness.capability import PROFILES
from colleague.harness.session import Reply, RunHandle, ThreadedRunHandle, compose


class HermesSession(CliSession):
    arm = "hermes"
    profile = PROFILES["hermes"]

    def setup(self) -> None:
        binary = HERMES_REPO / ".venv" / "bin" / "hermes"
        if not binary.exists():
            raise SystemExit(f"hermes binary missing — run `uv sync` in {HERMES_REPO}")
        self.home = self.results_dir / "hermes_home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.workdir = self.results_dir / "workspace"
        self.workdir.mkdir(parents=True, exist_ok=True)
        (self.home / "config.yaml").write_text(
            CONFIG_TEMPLATE.format(model=BENCH_MODEL),
            encoding="utf-8",
        )

    def _turn(self, prompt: str) -> Reply:
        code, tail = _run_hermes(
            ["chat", "-q", prompt],
            hermes_home=self.home,
            workdir=self.workdir,
            proxy_base_url=self.proxy_base_url,
            log_path=self.log_path,
            timeout_s=self.timeout_s,
        )
        return self._reply(code, tail)

    def begin(
        self,
        text: str,
        *,
        persist: bool = False,
        context: str | None = None,
        sender: str | None = None,
    ) -> RunHandle:
        del persist  # hermes has no persistent session to keep alive
        prompt = compose(context, text if sender is None else f"[{sender}] {text}")
        return ThreadedRunHandle(self._turn, prompt)

    def close(self) -> None:
        try:
            defuse_hermes_artifacts(self.home)
        except Exception:  # noqa: BLE001 - teardown is best-effort
            pass
        super().close()

    def artifacts(self) -> dict[str, Any]:
        return {**super().artifacts(), "hermes_home": str(self.home)}


register("hermes", HermesSession)
