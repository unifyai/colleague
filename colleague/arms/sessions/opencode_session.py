"""OpenCode as a conversational session.

`opencode run` is one-shot: the process exits when the turn ends, so there
is nothing to interject into and `interject` raises. Workspace files survive
between turns, which is real continuity of a kind — the agent can read what
it wrote last time — but the working state it had in memory does not, which
is what the `continuity` track puts a number on.

Host safety carries over from the `standing` track: OpenCode improvises host
scheduling and has twice installed real user crontab entries. The crontab is
snapshotted before the session and restored after every turn, on signals,
and at exit.
"""

from __future__ import annotations

from typing import Any

from colleague.arms.opencode import (
    BENCH_MODEL,
    arm_crontab_guard,
    defuse_host_artifacts,
    opencode_env,
    prepare_workspace,
    require_opencode,
    restore_crontab,
    run_opencode,
    scrub_state_archive,
    snapshot_crontab,
    write_opencode_config,
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


class OpenCodeSession(CliSession):
    arm = "opencode"
    profile = PROFILES["opencode"]

    def setup(self) -> None:
        require_opencode()
        self.state_root = self.results_dir / "opencode_state"
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.workspace = self.results_dir / "workspace"
        prepare_workspace(self.workspace)
        self.config_path = self.state_root / "opencode.json"
        write_opencode_config(
            self.config_path,
            proxy_base_url=self.proxy_base_url,
            model=BENCH_MODEL,
        )
        self._crontab_before = snapshot_crontab()
        arm_crontab_guard(self.results_dir, self._crontab_before)
        #: Host crontab lines the agent installed, captured before each
        #: restore. The host never keeps them, but they are what the agent
        #: bound to a clock — the fire-series clock runs exactly these.
        self.agent_crontab_lines: list[str] = []
        # Touch the env once so the CLI shim is on PATH before any turn.
        opencode_env(self.state_root, self.config_path)

    def _capture_crontab_additions(self) -> None:
        after = snapshot_crontab()
        before_lines = (self._crontab_before or "").splitlines()
        for line in (after or "").splitlines():
            if (
                line.strip()
                and not line.strip().startswith("#")
                and line not in before_lines
                and line not in self.agent_crontab_lines
            ):
                self.agent_crontab_lines.append(line)

    def _turn(self, prompt: str) -> Reply:
        code, out = run_opencode(
            ["run", prompt],
            workspace=self.workspace,
            state_root=self.state_root,
            config_path=self.config_path,
            log_path=self.log_path,
            timeout_s=self.timeout_s,
        )
        # OpenCode writes host crontab entries unprompted; capture what the
        # agent bound to the clock, then put the host back after every single
        # turn rather than only at the end.
        self._capture_crontab_additions()
        restore_crontab(self._crontab_before)
        return self._reply(code, out)

    def begin(
        self,
        text: str,
        *,
        persist: bool = False,
        context: str | None = None,
        sender: str | None = None,
        images: list[str] | None = None,
    ) -> RunHandle:
        del persist  # no session state survives the process
        if images:
            raise Unsupported(
                "this arm's driver has no way to attach an image to a turn",
            )
        prompt = compose(context, text if sender is None else f"[{sender}] {text}")
        return ThreadedRunHandle(self._turn, prompt)

    def close(self) -> None:
        try:
            defuse_host_artifacts(self.results_dir, self._crontab_before)
            scrub_state_archive(self.state_root, self.workspace)
        except Exception:  # noqa: BLE001 - teardown is best-effort
            pass
        super().close()

    def artifacts(self) -> dict[str, Any]:
        return {**super().artifacts(), "workspace": str(self.workspace)}


register("opencode", OpenCodeSession)
