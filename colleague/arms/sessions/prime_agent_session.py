"""prime-agent as a conversational session.

Driven through its print mode (`pi -p`): one headless turn per process,
metered by the recording proxy through a custom provider in a throwaway
agent directory, sessions saved to a run-local session directory and
continued with `-c` so `continuity` measures what the product keeps.

There is no way into a running turn: `interject` raises, and the profile
says restart-only for exactly that reason. The product has steering and
follow-up lanes on its interactive and JSONL-RPC surfaces; this driver does
not reach them, and it says so — an RPC-driven arm is the faithful surface,
the way `hermes-tui` is for hermes, and is the next step for this arm.

Skills, extensions, prompt templates and context files are all disabled so
the arm reasons from the request alone, as every other arm does. The
IPython kernel is prime-agent's own business: if it can bootstrap it, it
has it; if not, bash and edit remain.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

PRIME_AGENT_REPO = Path(
    os.environ.get("PRIME_AGENT_REPO", str(Path.home() / "prime-agent")),
)
BENCH_MODEL = os.environ.get("PRIME_AGENT_MODEL", "openai/gpt-5.6-sol")
PROVIDER = "openrouter-metered"


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


class PrimeAgentSession(CliSession):
    arm = "prime-agent"
    profile = PROFILES["prime-agent"]

    def setup(self) -> None:
        require_prime_agent()
        self.agent_dir = self.results_dir / "prime_agent_dir"
        self.session_dir = self.results_dir / "prime_sessions"
        self.workspace = self.results_dir / "workspace"
        for d in (self.agent_dir, self.session_dir, self.workspace):
            d.mkdir(parents=True, exist_ok=True)
        write_models_json(
            self.agent_dir,
            proxy_base_url=self.proxy_base_url,
            model=BENCH_MODEL,
        )
        self._has_session = False

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["PRIME_AGENT_CODING_AGENT_DIR"] = str(self.agent_dir)
        env["PRIME_AGENT_SESSION_DIR"] = str(self.session_dir)
        # No colour, no interactive affordances.
        env["NO_COLOR"] = "1"
        env["CI"] = "1"
        return env

    def _turn(self, prompt: str, *, continue_session: bool) -> Reply:
        cmd = [
            "node",
            str(cli_path()),
            "-p",
            "--mode",
            "text",
            "--provider",
            PROVIDER,
            "--model",
            BENCH_MODEL,
            "--session-dir",
            str(self.session_dir),
            "--cwd",
            str(self.workspace),
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-context-files",
            "--offline",
        ]
        if continue_session:
            cmd.append("-c")
        cmd += ["--", prompt]
        with open(self.log_path, "a", encoding="utf-8") as log:
            log.write(
                f"\n===== {datetime.now(timezone.utc).isoformat()} continue={continue_session}\n",
            )
            log.flush()
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(self.workspace),
                    env=self._env(),
                    capture_output=True,
                    text=True,
                    stdin=subprocess.DEVNULL,
                    timeout=self.timeout_s,
                )
                code, out = proc.returncode, proc.stdout
                log.write(proc.stdout)
                if proc.stderr:
                    log.write("\n--- stderr ---\n" + proc.stderr)
            except subprocess.TimeoutExpired as exc:
                code, out = 124, (
                    (exc.stdout or "") if isinstance(exc.stdout, str) else ""
                )
                log.write(f"\n--- timed out after {self.timeout_s}s ---\n")
        self._has_session = True
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
        del persist  # sessions are saved regardless; resume() continues them
        if images:
            raise Unsupported(
                "this arm's driver has no way to attach an image to a turn",
            )
        prompt = compose(context, text if sender is None else f"[{sender}] {text}")
        return ThreadedRunHandle(self._turn, prompt, continue_session=self._has_session)

    def resume(self, text: str, *, sender: str | None = None) -> Reply:
        """Continue the saved session — the product's own `-c`."""
        prompt = text if sender is None else f"[{sender}] {text}"
        return self._turn(prompt, continue_session=True)

    def artifacts(self) -> dict[str, Any]:
        return {
            **super().artifacts(),
            "agent_dir": str(self.agent_dir),
            "session_dir": str(self.session_dir),
            "workspace": str(self.workspace),
        }


register("prime-agent", PrimeAgentSession)
