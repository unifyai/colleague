"""hermes-agent as a conversational session.

`hermes chat -q` is a one-shot headless turn. There is no loop to address
once it starts, so `interject` raises and the scenario records
`UNSUPPORTED` rather than a failure.

Continuation, however, is a real product capability this adapter previously
discarded: the CLI persists every session to SQLite and its own source
blesses the automation pattern `hermes chat -Q --resume <id> -q "..."`
(hermes `cli_agent_setup_mixin.py`). `resume()` uses it, so `continuity`
and `custody` measure hermes's session model rather than an adapter
artifact. Fresh `begin()` turns stay stateless — that part is faithful.
"""

from __future__ import annotations

import re
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

#: The CLI announces the durable session key two ways: quiet mode prints
#: `session_id: <id>` and interactive exit prints `--resume <id>`. Both land
#: in the combined log because stderr is folded into it.
_SESSION_ID_RE = re.compile(r"(?:session_id:\s*|--resume\s+)([0-9a-zA-Z_]+)")


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
        self._last_session_id: str | None = None

    def _turn(self, prompt: str, *, resume_id: str | None = None) -> Reply:
        args = ["chat", "-Q", "-q", prompt]
        if resume_id:
            args += ["--resume", resume_id]
        code, tail = _run_hermes(
            args,
            hermes_home=self.home,
            workdir=self.workdir,
            proxy_base_url=self.proxy_base_url,
            log_path=self.log_path,
            timeout_s=self.timeout_s,
        )
        ids = _SESSION_ID_RE.findall(tail)
        if ids:
            self._last_session_id = ids[-1]
        return self._reply(code, tail)

    def resume(self, text: str, *, sender: str | None = None) -> Reply:
        """Continue the most recent session through hermes's own `--resume`."""
        if self._last_session_id is None:
            # No prior turn to continue — a cold turn is the honest fallback,
            # and the run record will show it (no resume flag in the log).
            return self._turn(text if sender is None else f"[{sender}] {text}")
        prompt = text if sender is None else f"[{sender}] {text}"
        return self._turn(prompt, resume_id=self._last_session_id)

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
