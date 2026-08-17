"""The proxy-metered CLI arms of a fire-series experiment: hermes, OpenClaw, OpenCode.

Every one of them is driven the same way — the identical utterance as one
headless chat turn, the automation the agent created fired through the
harness's own trigger for that arm, the same fixture serving data and
receiving deliveries, the same scorer — so the loop is written once and the
arms differ only in a small adapter: how to set up, how to say something,
how to fire, what to snapshot, what to defuse.

Recovery protocol for these arms (from `drift_recovery`): none of them has a
model in the loop at steady state, so after `operator_fix_after_failures`
consecutive non-correct fires the harness plays the realistic operator move
— one natural-language "it has been failing, please investigate and fix it"
message — measured like any other phase. Fires then continue. Owner
messages the experiment itself delivers (a change request, a rule
amendment) are separate: they go to every arm on the same fire, unify
included.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from colleague.arms.proxy import RecordingProxy
from colleague.harness.ledger import PhaseLedger
from colleague.tracks.standing.series.report import finalize
from colleague.tracks.standing.series.spec import Experiment, messages_since


class CliArm:
    """What the loop needs from one CLI harness."""

    name: str
    fire_fields: tuple[str, ...] = ()

    def __init__(self, *, results_dir: Path, proxy_base_url: str, timeout_s: float):
        self.results_dir = results_dir
        self.proxy_base_url = proxy_base_url
        self.timeout_s = timeout_s

    def start(self) -> None:
        return None

    def setup(self, utterance: str) -> dict[str, Any]:
        raise NotImplementedError

    def automation_ready(self) -> tuple[bool, str]:
        """Whether exactly one automation exists after setup, and a note."""
        raise NotImplementedError

    def message(self, text: str) -> dict[str, Any]:
        raise NotImplementedError

    def fire(self) -> dict[str, Any]:
        raise NotImplementedError

    def snapshot(self) -> Any:
        return None

    def defuse(self) -> Any:
        return None

    def describe(self) -> dict[str, Any]:
        return {}


class HermesArm(CliArm):
    name = "hermes"
    fire_fields = ("exit_code", "job_last_status")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        from colleague.arms import hermes as toolkit

        self.t = toolkit
        if not (toolkit.HERMES_REPO / ".venv" / "bin" / "hermes").exists():
            raise SystemExit(
                f"hermes binary missing — run `uv sync` in {toolkit.HERMES_REPO}",
            )
        self.home = self.results_dir / "hermes_home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.workdir = self.results_dir / "workspace"
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.results_dir / "hermes_cli.log"
        self.job_id: str | None = None

    def start(self) -> None:
        (self.home / "config.yaml").write_text(
            self.t.CONFIG_TEMPLATE.format(model=self.t.BENCH_MODEL),
            encoding="utf-8",
        )

    def _chat(self, text: str) -> tuple[int, str]:
        return self.t._run_hermes(
            ["chat", "-q", text],
            hermes_home=self.home,
            workdir=self.workdir,
            proxy_base_url=self.proxy_base_url,
            log_path=self.log_path,
            timeout_s=self.timeout_s,
        )

    def setup(self, utterance: str) -> dict[str, Any]:
        code, tail = self._chat(utterance)
        return {"exit_code": code, "log_tail": tail}

    def automation_ready(self) -> tuple[bool, str]:
        jobs = self.t._load_cron_jobs(self.home)
        if len(jobs) != 1:
            return (
                False,
                f"expected exactly one cron job after setup, found {len(jobs)}",
            )
        self.job_id = str(jobs[0].get("id"))
        return True, f"cron job created: {self.job_id} ({jobs[0].get('name')})"

    def message(self, text: str) -> dict[str, Any]:
        code, _ = self._chat(text)
        return {"exit_code": code}

    def fire(self) -> dict[str, Any]:
        code, _ = self.t._run_hermes(
            ["cron", "run", str(self.job_id)],
            hermes_home=self.home,
            workdir=self.workdir,
            proxy_base_url=self.proxy_base_url,
            log_path=self.log_path,
            timeout_s=self.timeout_s,
        )
        jobs = self.t._load_cron_jobs(self.home)
        return {
            "exit_code": code,
            "job_last_status": jobs[0].get("last_status") if jobs else None,
        }

    def snapshot(self) -> Any:
        return self.t._snapshot_profile_artifacts(self.home)

    def defuse(self) -> Any:
        return self.t.defuse_hermes_artifacts(self.home)

    def describe(self) -> dict[str, Any]:
        return {"hermes_repo": str(self.t.HERMES_REPO), "model": self.t.BENCH_MODEL}


class OpenClawArm(CliArm):
    name = "openclaw"
    fire_fields = ("fire_status",)

    def __init__(self, *, gateway_port: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        from colleague.arms import openclaw as toolkit

        self.t = toolkit
        if not (toolkit.OPENCLAW_REPO / "dist").is_dir():
            raise SystemExit(
                "OpenClaw build output missing — run `pnpm install && pnpm build` "
                f"in {toolkit.OPENCLAW_REPO}",
            )
        self.gateway_port = gateway_port
        self.state_dir = self.results_dir / "openclaw_state"
        self.workspace = self.results_dir / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.log_path = self.results_dir / "openclaw_cli.log"
        self.gateway: Any = None
        self.job_id: str | None = None

    def start(self) -> None:
        self.t.write_openclaw_config(
            self.state_dir,
            proxy_base_url=self.proxy_base_url,
            workspace=self.workspace,
        )
        self.gateway = self.t.GatewayProcess(
            state_dir=self.state_dir,
            gateway_port=self.gateway_port,
            log_path=self.results_dir / "gateway.log",
        ).start()
        print(f"[gateway] up on port {self.gateway_port}")

    def _agent(self, text: str) -> tuple[int, str]:
        return self.t.run_openclaw(
            [
                "agent",
                "--session-id",
                "benchmark-setup",
                "-m",
                text,
                "--json",
                "--timeout",
                str(int(self.timeout_s)),
            ],
            state_dir=self.state_dir,
            gateway_port=self.gateway_port,
            log_path=self.log_path,
            timeout_s=self.timeout_s + 60,
        )

    def setup(self, utterance: str) -> dict[str, Any]:
        code, out = self._agent(utterance)
        payload = self.t.extract_json(out)
        return {
            "exit_code": code,
            "final_text": (
                (payload or {}).get("result", {}).get("finalAssistantVisibleText")
                if isinstance(payload, dict)
                else None
            ),
        }

    def automation_ready(self) -> tuple[bool, str]:
        jobs = self.t.cron_jobs(self.state_dir, self.gateway_port, self.log_path)
        if len(jobs) != 1:
            return (
                False,
                f"expected exactly one cron job after setup, found {len(jobs)}",
            )
        self.job_id = str(jobs[0].get("id"))
        return True, f"cron job created: {self.job_id} ({jobs[0].get('name')})"

    def message(self, text: str) -> dict[str, Any]:
        code, _ = self._agent(text)
        return {"exit_code": code}

    def fire(self) -> dict[str, Any]:
        fire = self.t.cron_fire(
            str(self.job_id),
            state_dir=self.state_dir,
            gateway_port=self.gateway_port,
            log_path=self.log_path,
            timeout_s=self.timeout_s,
        )
        return {"fire_status": fire.get("status")}

    def snapshot(self) -> Any:
        return self.t.snapshot_artifacts(
            self.state_dir,
            self.workspace,
            self.gateway_port,
            self.log_path,
        )

    def defuse(self) -> Any:
        return self.t.defuse_openclaw_artifacts(
            self.state_dir,
            self.gateway,
            self.gateway_port,
            self.log_path,
        )

    def describe(self) -> dict[str, Any]:
        return {"openclaw_repo": str(self.t.OPENCLAW_REPO), "model": self.t.BENCH_MODEL}


class OpenCodeArm(CliArm):
    name = "opencode"
    fire_fields = ("fire_mode", "exit_code")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        from colleague.arms import opencode as toolkit

        self.t = toolkit
        toolkit.require_opencode()
        self.state_root = self.results_dir / "opencode_state"
        self.workspace = self.results_dir / "workspace"
        self.config_path = self.results_dir / "opencode.json"
        self.log_path = self.results_dir / "opencode_cli.log"
        toolkit.prepare_workspace(self.workspace)
        self.crontab_before = toolkit.snapshot_crontab()
        toolkit.arm_crontab_guard(self.results_dir, self.crontab_before)

    def start(self) -> None:
        self.t.write_opencode_config(
            self.config_path,
            proxy_base_url=self.proxy_base_url,
        )

    def _run(self, text: str) -> tuple[int, str]:
        return self.t.run_opencode(
            ["run", text],
            workspace=self.workspace,
            state_root=self.state_root,
            config_path=self.config_path,
            log_path=self.log_path,
            timeout_s=self.timeout_s,
        )

    def setup(self, utterance: str) -> dict[str, Any]:
        code, out = self._run(utterance)
        return {"exit_code": code, "output_tail": out[-2000:]}

    def automation_ready(self) -> tuple[bool, str]:
        # OpenCode has no scheduler; the harness supplies the wake (see
        # `colleague/arms/opencode.py`), so whatever it persisted is fired.
        return True, f"persisted={self.snapshot()}"

    def message(self, text: str) -> dict[str, Any]:
        code, _ = self._run(text)
        return {"exit_code": code}

    def fire(self) -> dict[str, Any]:
        fire = self.t.fire_automation(
            workspace=self.workspace,
            state_root=self.state_root,
            config_path=self.config_path,
            log_path=self.log_path,
            timeout_s=self.timeout_s,
        )
        return {"fire_mode": fire["fire_mode"], "exit_code": fire["exit_code"]}

    def snapshot(self) -> Any:
        return {
            "workspace_files": self.t.workspace_files(self.workspace),
            "commands": self.t.discover_commands(self.workspace),
            "scripts": [p.name for p in self.t.discover_scripts(self.workspace)],
        }

    def defuse(self) -> Any:
        actions = self.t.defuse_host_artifacts(self.results_dir, self.crontab_before)
        if actions:
            print(f"[defuse] {actions}")
        self.t.scrub_state_archive(self.state_root, self.workspace)
        return actions

    def describe(self) -> dict[str, Any]:
        return {
            "opencode_repo": str(self.t.OPENCODE_REPO),
            "model": self.t.BENCH_MODEL,
            "wake_prompt": self.t.WAKE_PROMPT,
        }


_DEFAULT_PROXY_PORT = {"hermes": 8126, "openclaw": 8159, "opencode": 8175}


def run(experiment: Experiment, arm_name: str) -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SystemExit(f"OPENROUTER_API_KEY is required (use run_{arm_name}.sh)")
    prefix = experiment.env_prefix
    seed = int(os.environ.get(f"{prefix}_SEED", experiment.default_seed))
    fixture_port = int(os.environ.get(f"{prefix}_PORT", experiment.default_port))
    proxy_port = int(
        os.environ.get(f"{prefix}_PROXY_PORT", _DEFAULT_PROXY_PORT[arm_name]),
    )
    phase_timeout_s = float(os.environ.get(f"{prefix}_PHASE_TIMEOUT_S", "1800"))
    run_id = (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        + experiment.run_suffix()
        + f"-{arm_name}"
    )
    results_dir = experiment.directory / "results" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    proxy = RecordingProxy(
        port=proxy_port,
        ledger_path=results_dir / "proxy_ledger.jsonl",
    ).start()
    fixture = experiment.build_fixture(seed=seed, port=fixture_port).start()
    print(f"[fixture] {fixture.base_url} (seed={seed})")
    print(f"[proxy] {proxy.base_url} -> openrouter.ai")
    ledger = PhaseLedger(results_dir / "proxy_ledger.jsonl")

    common = dict(
        results_dir=results_dir,
        proxy_base_url=proxy.base_url,
        timeout_s=phase_timeout_s,
    )
    if arm_name == "hermes":
        arm: CliArm = HermesArm(**common)
    elif arm_name == "openclaw":
        arm = OpenClawArm(
            gateway_port=int(os.environ.get("OC_GATEWAY_PORT", "18936")),
            **common,
        )
    elif arm_name == "opencode":
        arm = OpenCodeArm(**common)
    else:
        raise SystemExit(f"unknown CLI arm {arm_name!r}")

    utterance = experiment.utterance(fixture.base_url)
    results: dict[str, Any] = {
        "experiment": experiment.name,
        "variant": experiment.variant(),
        "system": arm_name,
        "run_id": run_id,
        **arm.describe(),
        "seed": seed,
        "n_fires": experiment.n_fires,
        "operator_fix_after_failures": experiment.operator_fix_after_failures,
        "operator_fix_message": experiment.operator_fix_message,
        "utterance": utterance,
        **experiment.describe(),
        "messages": [],
        "fires": [],
    }

    def _phase(name: str, fn):
        start = ledger.count()
        t0 = time.monotonic()
        out = fn()
        ledger.mark(name, start, ledger.count(), time.monotonic() - t0)
        return out

    exit_code = 0
    try:
        arm.start()
        print(f"[setup] issuing utterance to {arm_name} ...")
        results["setup"] = _phase("setup", lambda: arm.setup(utterance))
        print(f"[setup] exit={results['setup'].get('exit_code')}")
        results["profile_after_setup"] = arm.snapshot()
        ready, note = arm.automation_ready()
        print(f"[setup] {note}")
        if not ready:
            print(f"[abort] {note}")
            return 1

        consecutive_failures = 0
        operator_fix_done = False
        for i in range(1, experiment.n_fires + 1):
            label = experiment.label(i)
            events = experiment.before_fire(fixture, i)
            for event in events:
                print(f"[{label}] world: {event}")

            for k, text in enumerate(experiment.operator_messages(i, fixture.base_url)):
                phase = f"message_{i}" if k == 0 else f"message_{i}_{k}"
                print(f"[{phase}] owner says: {text[:120]}")
                out = _phase(phase, lambda t=text: arm.message(t))
                results["messages"].append(
                    {"before_fire": i, "phase": phase, "text": text, **out},
                )
                print(f"[{phase}] exit={out.get('exit_code')}")

            threshold = experiment.operator_fix_after_failures
            if (
                threshold is not None
                and consecutive_failures >= threshold
                and not operator_fix_done
            ):
                print(f"[operator_fix] issuing fix request to {arm_name} ...")
                out = _phase(
                    "operator_fix",
                    lambda: arm.message(experiment.operator_fix_message),
                )
                results["operator_fix"] = {**out, "before_fire": i}
                operator_fix_done = True
                print(f"[operator_fix] exit={out.get('exit_code')}")

            ctx = experiment.prepare_fire(fixture)
            ctx["fire"] = i
            owner_before = len(fixture.state["owner"])
            print(f"[{label}] pending: {ctx.get('pending', ctx)}")
            fired = _phase(label, arm.fire)
            row = {
                "fire": i,
                "label": label,
                "events": events,
                **fired,
                **experiment.score_fire(
                    fixture,
                    ctx,
                    messages=messages_since(fixture, owner_before),
                ),
            }
            results["fires"].append(row)
            consecutive_failures = 0 if row["correct"] else consecutive_failures + 1
            print(
                f"[{label}] {fired} outcome={row['outcome']} score={row['score']}",
            )
        results["profile_final"] = arm.snapshot()
    finally:
        results["defuse_actions"] = arm.defuse()
        summary = finalize(
            results,
            phases=ledger.summarize(),
            results_dir=results_dir,
            experiment=experiment,
            arm=arm_name,
        )
        fixture.stop()
        proxy.stop()
        print(f"\n{summary}")
        print(f"[done] results in {results_dir}")
    return exit_code
