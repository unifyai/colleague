"""The person-shaped fire-series engine: one loop, every arm.

The benchmark interfaces with a harness as though it were a person, so a
fire-series experiment runs the same way for every arm:

1.  **The brief is a conversation.** The experiment's utterance — already
    plain English — is delivered through the arm's session surface
    (`colleague.arms.sessions`), exactly as any conversational track
    delivers a request. Nothing is planted through harness internals.
2.  **The system decides how the work recurs.** A unify task on its
    scheduler, a hermes or OpenClaw cron job, a prime-agent scheduled job,
    a host crontab entry — or nothing. What it chose is recorded as
    evidence (`recurrences_after_setup`), never enforced: the old drivers'
    "abort unless exactly one recurring task" gate is gone, because
    convergence is part of what is being measured.
3.  **The harness is only the clock.** Between fires it advances the
    fixture's world (`experiment.before_fire`) and delivers the owner's
    messages as ordinary conversation turns. A fire delivers the due tick
    for *whatever the system itself bound to the clock*, through the
    product's own firing machinery — the CM's due-task path, `hermes cron
    run`, `openclaw cron run`, a scheduled job's own prompt, the captured
    crontab line — and then observes: the fixture's sink, plus a bounded
    quiescence window on the arm's meter. A system that bound nothing gets
    an empty tick, and the sink shows it.

Per-fire attribution: the unify-cm arm is metered in-process
(`LLMLedger.boundary` marks named windows — `setup`, `message_3`,
`fire_5` — and `segments()` cuts the ledger at them; the fire's window
runs to the next mark, so its detached review tail is included). Every
other arm is metered by the session's recording proxy, with
`PhaseLedger.mark` windows cut the same way. Both produce the phase shape
`series/report.py` folds into per-fire tokens and cost.

The operator-fix protocol survives unchanged from the old regime — it is a
declared human role, not a harness mechanism: for arms other than
`unify-cm`, after `experiment.operator_fix_after_failures` consecutive
non-correct fires the owner sends one fix request, as a conversation turn.
The unify-cm arm is never helped; its runtime's own verify/repair is the
result.

Blocking clarification channels (unify-cm, hermes-tui) are answered by the
owner with one scripted, information-free line — the briefs are complete by
construction, so the only honest answer is "you have everything, proceed".
Rounds are recorded.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from colleague.arms.sessions import build as build_session
from colleague.tracks.standing.series.report import finalize
from colleague.tracks.standing.series.spec import (
    Experiment,
    OwnerMessage,
    messages_since,
)

#: Arms a fire-series experiment can run against — one per harness, the
#: same person-shaped surfaces the conversational tracks use. Voice
#: transports carry no scheduler surface and are not fire-series arms.
PERSON_ARMS = (
    "unify-cm",
    "hermes-tui",
    "openclaw-gateway",
    "opencode",
    "prime-agent-rpc",
)

#: The owner's scripted answer to any clarifying question. Deliberately
#: information-free: the briefs carry every fact by construction, so the
#: answer confirms authority without supplying ground truth. This is the
#: scripted-implementation fallback; live runs play the owner through the
#: persona engine with the same information bound (`owner_pool`).
OWNER_CLARIFICATION_REPLY = (
    "Everything you need is in my earlier message — use your judgment and "
    "go ahead. Don't wait on me."
)


def owner_pool(*, results_dir: Path, run_id: str) -> "PersonaPool":
    """The owner as a persona: same information bound, a person's wording.

    The brief encodes exactly what the owner's messages already said — his
    memory is seeded with each utterance as he sends it — and the standing
    discipline is the one the scripted constant states: nothing new, ever.
    The persona engine's ledger meters him apart from the arm.
    """
    from colleague.harness.conversation import Participant
    from colleague.harness.persona import Persona, PersonaPool

    pool = PersonaPool(
        [
            Persona(
                participant=Participant(
                    id="owner",
                    name="the owner",
                    role="the person the assistant works for",
                    email="owner@colleague.example",
                ),
                brief=(
                    "You are the owner: you sent the assistant the messages "
                    "in this conversation, asking for the recurring work "
                    "they describe. You wrote them to be complete — they "
                    "contain everything the assistant needs. If it asks a "
                    "clarifying question, never add information beyond what "
                    "your own messages already said: point it back to them, "
                    "tell it to use its judgment and go ahead, and never "
                    "ask it to wait on you. You may restate something your "
                    "message literally contained, verbatim, if asked for "
                    "exactly that."
                ),
                fallback=OWNER_CLARIFICATION_REPLY,
                fallback_label="repointed",
            ),
        ],
    )
    pool.bind_ledger(results_dir / "persona_ledger.jsonl", run_id=run_id)
    pool.begin_scenario("series")
    return pool


def _env(prefix: str, key: str, default: Any) -> str:
    return os.environ.get(f"{prefix}_{key}", str(default))


class StandingHooks:
    """What the engine needs from an arm, beyond the ArmSession contract."""

    arm: str = ""
    #: Whether the unify-cm operator-fix exemption applies (its runtime's
    #: own verify/repair is the result; a person never fixes it).
    operator_fixable: bool = True

    def __init__(self, session: Any, *, timeout_s: float) -> None:
        self.session = session
        self.timeout_s = timeout_s

    # -- phases ------------------------------------------------------------

    @contextlib.contextmanager
    def phase(self, label: str) -> Iterator[None]:
        raise NotImplementedError

    def phases(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    # -- conversation ------------------------------------------------------

    def deliver(self, text: str) -> dict[str, Any]:
        """One owner turn through the session surface."""
        reply = self.session.send(text, timeout=self.timeout_s)
        return {
            "status": "completed" if reply.ok else "error",
            "result": (reply.text or reply.error)[:1500],
        }

    # -- the clock ---------------------------------------------------------

    def recurrences(self) -> list[dict[str, Any]]:
        """What the system has bound to the clock right now. Evidence."""
        raise NotImplementedError

    def tick(self) -> list[dict[str, Any]]:
        """Run everything due, through the product's own firing machinery."""
        raise NotImplementedError

    def settle(self, *, idle_s: float, timeout_s: float) -> bool:
        """Bounded quiescence after a tick. Default: ticks are synchronous."""
        return True

    # -- owner channel / evidence -----------------------------------------

    def owner_marker(self) -> Any:
        return None

    def owner_messages_since(self, marker: Any) -> list[OwnerMessage]:
        """Owner messages carried on the arm's own channel, if it has one."""
        return []

    def fire_evidence(self) -> dict[str, Any]:
        """Arm-specific per-fire evidence (entrypoints, job status, ...)."""
        return {}

    def describe(self) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        self.session.close()


class _ProxyPhases:
    """PhaseLedger windows for the proxy-metered arms, shared by all four."""

    @contextlib.contextmanager
    def phase(self, label: str) -> Iterator[None]:
        ledger = self.session.ledger
        start = ledger.count()
        t0 = time.monotonic()
        try:
            yield
        finally:
            ledger.mark(label, start, ledger.count(), time.monotonic() - t0)

    def phases(self) -> list[dict[str, Any]]:
        return self.session.ledger.summarize()


class CmHooks(StandingHooks):
    """unify-cm: the ConversationManager surface, metered in-process."""

    arm = "unify-cm"
    operator_fixable = False

    @contextlib.contextmanager
    def phase(self, label: str) -> Iterator[None]:
        self.session.ledger.boundary(label)
        yield

    def phases(self) -> list[dict[str, Any]]:
        return [s.to_json() for s in self.session.ledger.segments()]

    def recurrences(self) -> list[dict[str, Any]]:
        return self.session.scheduled_recurrences()

    def tick(self) -> list[dict[str, Any]]:
        return self.session.fire_due_recurrences(
            scheduled_for=datetime.now(timezone.utc).isoformat(),
        )

    def settle(self, *, idle_s: float, timeout_s: float) -> bool:
        """The CM drain, then the ledger's idle window.

        The drain covers the queue, the brain and every in-flight action;
        the idle window covers what the drain structurally cannot see — the
        detached storage/librarian reviews that outlive a consumed handle,
        whose calls would otherwise land in the next fire's window.
        """
        settled = self.session.settle(timeout=timeout_s)
        quiet = asyncio.run(
            self.session.ledger.wait_quiescent(
                idle_seconds=idle_s,
                timeout_seconds=timeout_s,
            ),
        )
        return bool(settled and quiet)

    def owner_marker(self) -> int:
        return self.session.egress_marker()

    def owner_messages_since(self, marker: int) -> list[OwnerMessage]:
        return [
            OwnerMessage(text=m["text"], via="arm")
            for m in self.session.owner_messages_since(marker)
        ]

    def fire_evidence(self) -> dict[str, Any]:
        from colleague.arms.unify_runtime import function_snapshots_by_name

        tasks = self.recurrences()
        out: dict[str, Any] = {
            "entrypoints": {str(t["task_id"]): t.get("entrypoint") for t in tasks},
        }
        try:
            out["functions"] = function_snapshots_by_name()
        except Exception:  # noqa: BLE001 - evidence, never control flow
            pass
        return out

    def describe(self) -> dict[str, Any]:
        return {"context": self.session.context, "project": self.session.project}


class HermesHooks(_ProxyPhases, StandingHooks):
    """hermes-tui: the resident TUI gateway session; cron store on disk.

    The tick runs `hermes cron run <id>` for every enabled job the agent
    created — the product's own manual trigger, which executes the job
    exactly as its scheduler tick would. The gateway stays resident (the
    person keeps the app open); the cron runner is its own process against
    the same profile, as the OS scheduler would run it.
    """

    arm = "hermes-tui"

    def recurrences(self) -> list[dict[str, Any]]:
        from colleague.arms.hermes import _load_cron_jobs

        return _load_cron_jobs(self.session.home)

    def tick(self) -> list[dict[str, Any]]:
        from colleague.arms.hermes import _load_cron_jobs, _run_hermes

        fired: list[dict[str, Any]] = []
        for job in self.recurrences():
            job_id = str(job.get("id") or "")
            entry: dict[str, Any] = {"job_id": job_id, "name": job.get("name")}
            if not job_id or job.get("enabled") is False:
                entry["skipped"] = "disabled" if job_id else "no id"
                fired.append(entry)
                continue
            code, _ = _run_hermes(
                ["cron", "run", job_id],
                hermes_home=self.session.home,
                workdir=self.session.workdir,
                proxy_base_url=self.session.proxy_base_url,
                log_path=self.session.log_path,
                timeout_s=self.timeout_s,
            )
            entry["exit_code"] = code
            now = {str(j.get("id")): j for j in _load_cron_jobs(self.session.home)}
            entry["last_status"] = (now.get(job_id) or {}).get("last_status")
            fired.append(entry)
        return fired

    def fire_evidence(self) -> dict[str, Any]:
        return {
            "cron_jobs": [
                {
                    "id": j.get("id"),
                    "enabled": j.get("enabled"),
                    "last_status": j.get("last_status"),
                }
                for j in self.recurrences()
            ],
        }


class OpenClawHooks(_ProxyPhases, StandingHooks):
    """openclaw-gateway: the resident Gateway session; its cron scheduler."""

    arm = "openclaw-gateway"

    def recurrences(self) -> list[dict[str, Any]]:
        from colleague.arms.openclaw import cron_jobs

        return cron_jobs(
            self.session.state_dir,
            self.session.gateway_port,
            self.session.log_path,
        )

    def tick(self) -> list[dict[str, Any]]:
        from colleague.arms.openclaw import cron_fire

        fired: list[dict[str, Any]] = []
        for job in self.recurrences():
            job_id = str(job.get("id") or "")
            entry: dict[str, Any] = {"job_id": job_id, "name": job.get("name")}
            if not job_id or job.get("enabled") is False:
                entry["skipped"] = "disabled" if job_id else "no id"
                fired.append(entry)
                continue
            entry.update(
                cron_fire(
                    job_id,
                    state_dir=self.session.state_dir,
                    gateway_port=self.session.gateway_port,
                    log_path=self.session.log_path,
                    timeout_s=self.timeout_s,
                ),
            )
            fired.append(entry)
        return fired

    def fire_evidence(self) -> dict[str, Any]:
        return {
            "cron_jobs": [
                {"id": j.get("id"), "enabled": j.get("enabled")}
                for j in self.recurrences()
            ],
        }


class _CrontabGuard:
    """Capture-and-restore of the host crontab around agent activity.

    Arms whose agents have installed real host cron entries get the same
    protection the OpenCode session carries: the host never keeps an
    agent-installed entry, but the entry is captured first, because it is
    what the agent bound to the clock and the tick runs exactly it.
    """

    def __init__(self) -> None:
        from colleague.arms.opencode import snapshot_crontab

        self._before = snapshot_crontab()
        self.agent_lines: list[str] = []

    def sweep(self) -> None:
        from colleague.arms.opencode import restore_crontab, snapshot_crontab

        after = snapshot_crontab()
        before_lines = (self._before or "").splitlines()
        for line in (after or "").splitlines():
            if (
                line.strip()
                and not line.strip().startswith("#")
                and line not in before_lines
                and line not in self.agent_lines
            ):
                self.agent_lines.append(line)
        restore_crontab(self._before)

    @staticmethod
    def command_of(line: str) -> str | None:
        fields = line.split(None, 5)
        if len(fields) < 6:
            return None
        command = fields[5]
        for redirect in (">>", "2>&1", ">"):
            idx = command.find(redirect)
            if idx > 0:
                command = command[:idx]
        return command.strip() or None


def _run_clock_command(
    command: str,
    *,
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
    timeout_s: float,
) -> dict[str, Any]:
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"\n===== clock fire: {command}\n")
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(cwd),
                env=env,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout_s,
            )
            log.write(proc.stdout)
            log.write(proc.stderr)
            return {"command": command, "exit_code": proc.returncode}
        except subprocess.TimeoutExpired:
            log.write(f"\n===== TIMEOUT after {timeout_s}s\n")
            return {"command": command, "exit_code": None, "error": "timeout"}


class OpenCodeHooks(_ProxyPhases, StandingHooks):
    """opencode: one-shot CLI turns; the host crontab and cron-spec files.

    OpenCode has no scheduler of its own, so what its agent can bind to a
    clock is a host crontab entry (captured by the session before the host
    is restored) or a crontab-format spec file written into the workspace.
    The tick runs exactly those commands. A lone script the agent wrote but
    never bound to any schedule is not clock-bound and is not run — the old
    drivers' script and wake-prompt fallbacks were the harness deciding the
    mechanism, which is what this engine exists to stop.
    """

    arm = "opencode"

    def recurrences(self) -> list[dict[str, Any]]:
        from colleague.arms.opencode import discover_cron_command

        out: list[dict[str, Any]] = [
            {"kind": "host_crontab", "line": line}
            for line in getattr(self.session, "agent_crontab_lines", [])
        ]
        spec = discover_cron_command(self.session.workspace)
        if spec:
            out.append({"kind": "cron_spec", "command": spec})
        return out

    def tick(self) -> list[dict[str, Any]]:
        from colleague.arms.opencode import opencode_env

        env = opencode_env(self.session.state_root, self.session.config_path)
        fired: list[dict[str, Any]] = []
        seen: set[str] = set()
        for rec in self.recurrences():
            command = (
                _CrontabGuard.command_of(rec["line"])
                if rec["kind"] == "host_crontab"
                else rec["command"]
            )
            if not command or command in seen:
                continue
            seen.add(command)
            fired.append(
                {
                    "kind": rec["kind"],
                    **_run_clock_command(
                        command,
                        cwd=self.session.workspace,
                        env=env,
                        log_path=self.session.log_path,
                        timeout_s=self.timeout_s,
                    ),
                },
            )
        return fired

    def fire_evidence(self) -> dict[str, Any]:
        return {"recurrences": self.recurrences()}


class PrimeAgentHooks(_ProxyPhases, StandingHooks):
    """prime-agent-rpc: the resident RPC session; its own scheduler.

    prime-agent's scheduler has no script payload — every firing is the
    job's own prompt into an agent turn. The tick delivers exactly that:
    each active scheduled job's prompt, verbatim, into the resident
    session, which is what the product's scheduler does when the job comes
    due. Host crontab entries the agent installs are captured and run the
    same way OpenCode's are.
    """

    arm = "prime-agent-rpc"

    def __init__(self, session: Any, *, timeout_s: float) -> None:
        super().__init__(session, timeout_s=timeout_s)
        self._crontab = _CrontabGuard()

    def deliver(self, text: str) -> dict[str, Any]:
        out = super().deliver(text)
        self._crontab.sweep()
        return out

    def recurrences(self) -> list[dict[str, Any]]:
        from colleague.arms.prime_agent import scheduled_jobs

        out: list[dict[str, Any]] = [
            {"kind": "scheduled_job", **job}
            for job in scheduled_jobs(self.session.session_dir)
        ]
        out.extend(
            {"kind": "host_crontab", "line": line} for line in self._crontab.agent_lines
        )
        return out

    def tick(self) -> list[dict[str, Any]]:
        fired: list[dict[str, Any]] = []
        for rec in self.recurrences():
            if rec["kind"] == "scheduled_job":
                if rec.get("status") not in (None, "active"):
                    fired.append(
                        {
                            "kind": "scheduled_job",
                            "job_id": rec.get("id"),
                            "skipped": rec.get("status"),
                        },
                    )
                    continue
                prompt = str(rec.get("prompt") or "")
                if not prompt:
                    fired.append(
                        {
                            "kind": "scheduled_job",
                            "job_id": rec.get("id"),
                            "skipped": "no prompt",
                        },
                    )
                    continue
                reply = self.session.send(prompt, timeout=self.timeout_s)
                fired.append(
                    {
                        "kind": "scheduled_job",
                        "job_id": rec.get("id"),
                        "status": "completed" if reply.ok else "error",
                        "agent_runs": (reply.meta or {}).get("agent_runs"),
                    },
                )
            else:
                command = _CrontabGuard.command_of(rec["line"])
                if command:
                    fired.append(
                        {
                            "kind": "host_crontab",
                            **_run_clock_command(
                                command,
                                cwd=self.session.workspace,
                                env=self.session._rpc.env(),
                                log_path=self.session.log_path,
                                timeout_s=self.timeout_s,
                            ),
                        },
                    )
        self._crontab.sweep()
        return fired

    def fire_evidence(self) -> dict[str, Any]:
        return {
            "recurrences": [
                {k: v for k, v in r.items() if k in ("kind", "id", "status", "line")}
                for r in self.recurrences()
            ],
        }

    def close(self) -> None:
        self._crontab.sweep()
        super().close()


_HOOKS = {
    "unify-cm": CmHooks,
    "hermes-tui": HermesHooks,
    "openclaw-gateway": OpenClawHooks,
    "opencode": OpenCodeHooks,
    "prime-agent-rpc": PrimeAgentHooks,
}


def build_hooks(
    arm: str,
    *,
    results_dir: Path,
    run_id: str,
    track: str,
    timeout_s: float,
) -> StandingHooks:
    """Boot the arm's session and wrap it in its standing hooks."""
    if arm not in _HOOKS:
        raise SystemExit(
            f"unknown fire-series arm {arm!r}; known: {', '.join(PERSON_ARMS)}",
        )
    if arm == "unify-cm":
        session = build_session(
            arm,
            run_id=run_id,
            track=track,
            results_dir=results_dir,
        )
        session.auto_turn_boundaries = False
    else:
        session = build_session(
            arm,
            results_dir=results_dir,
            run_id=run_id,
            timeout_s=timeout_s,
        )
    session.setup()
    hooks = _HOOKS[arm](session, timeout_s=timeout_s)
    clarifications: list[dict[str, Any]] = []
    pool = owner_pool(results_dir=results_dir, run_id=run_id)

    def responder(question: str, who: str | None = None) -> str:
        # The owner is a persona with the same information bound the old
        # scripted constant enforced: nothing beyond his own messages. The
        # reply's label rides along so a re-supplied detail is visible.
        answer = pool.answer("owner", question)
        exchanges = pool.exchanges()
        label = exchanges[-1].get("label") if exchanges else None
        clarifications.append(
            {"question": question, "who": who, "answer": answer, "label": label},
        )
        return answer

    session.on_clarification(responder)
    hooks.owner_clarifications = clarifications  # type: ignore[attr-defined]
    hooks.owner_pool = pool  # type: ignore[attr-defined]
    return hooks


def run_series(experiment: Experiment, arm: str) -> int:
    """Run one fire-series experiment against one arm, person-shaped."""
    prefix = experiment.env_prefix
    seed = int(_env(prefix, "SEED", experiment.default_seed))
    port = int(_env(prefix, "PORT", experiment.default_port))
    phase_timeout_s = float(_env(prefix, "PHASE_TIMEOUT_S", 1800))
    quiesce_idle_s = float(_env(prefix, "QUIESCE_IDLE_S", 180))
    quiesce_timeout_s = float(_env(prefix, "QUIESCE_TIMEOUT_S", 1800))
    run_id = (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        + experiment.run_suffix()
        + f"-{arm}"
    )
    results_dir = experiment.directory / "results" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    fixture = experiment.build_fixture(seed=seed, port=port).start()
    print(f"[fixture] {fixture.base_url} (seed={seed})")
    hooks = build_hooks(
        arm,
        results_dir=results_dir,
        run_id=run_id,
        track=f"standing/{experiment.name}",
        timeout_s=phase_timeout_s,
    )

    utterance = experiment.utterance(fixture.base_url)
    results: dict[str, Any] = {
        "experiment": experiment.name,
        "variant": experiment.variant(),
        "system": arm,
        "regime": "person",
        "run_id": run_id,
        "seed": seed,
        "n_fires": experiment.n_fires,
        "operator_fix_after_failures": (
            experiment.operator_fix_after_failures if hooks.operator_fixable else None
        ),
        "operator_fix_message": experiment.operator_fix_message,
        "utterance": utterance,
        **hooks.describe(),
        **experiment.describe(),
        "messages": [],
        "fires": [],
    }

    exit_code = 0
    try:
        # An experiment may split its brief into several owner turns
        # (policy_propagation sets up three automations); the default is
        # the single utterance every experiment declares.
        setups = (
            experiment.setup_utterances(fixture.base_url)
            if hasattr(experiment, "setup_utterances")
            else [utterance]
        )
        setup_records: list[dict[str, Any]] = []
        for n, text in enumerate(setups, start=1):
            phase_name = "setup" if n == 1 else f"setup_{n}"
            print(f"[{phase_name}] delivering the brief to {arm} ...")
            hooks.owner_pool.note_authored("owner", text)
            with hooks.phase(phase_name):
                out = hooks.deliver(text)
                hooks.settle(idle_s=quiesce_idle_s, timeout_s=quiesce_timeout_s)
            setup_records.append({"phase": phase_name, **out})
            print(f"[{phase_name}] {out['status']}")
        results["setup"] = setup_records[0]
        if len(setup_records) > 1:
            results["setups"] = setup_records
        recurrences = hooks.recurrences()
        results["recurrences_after_setup"] = recurrences
        print(
            f"[setup] the system bound {len(recurrences)} recurrence(s) to "
            "the clock" + ("" if recurrences else " — fires will find nothing"),
        )

        consecutive_failures = 0
        operator_fix_done = False
        for i in range(1, experiment.n_fires + 1):
            label = experiment.label(i)
            events = experiment.before_fire(fixture, i)
            for event in events:
                print(f"[{label}] world: {event}")

            for k, text in enumerate(
                experiment.operator_messages(i, fixture.base_url),
            ):
                phase = f"message_{i}" if k == 0 else f"message_{i}_{k}"
                print(f"[{phase}] owner says: {text[:120]}")
                hooks.owner_pool.note_authored("owner", text)
                with hooks.phase(phase):
                    out = hooks.deliver(text)
                    hooks.settle(
                        idle_s=quiesce_idle_s,
                        timeout_s=quiesce_timeout_s,
                    )
                results["messages"].append(
                    {"before_fire": i, "phase": phase, "text": text, **out},
                )
                print(f"[{phase}] {out['status']}")

            threshold = experiment.operator_fix_after_failures
            if (
                hooks.operator_fixable
                and threshold is not None
                and consecutive_failures >= threshold
                and not operator_fix_done
            ):
                print(f"[operator_fix] the owner asks {arm} to investigate ...")
                with hooks.phase("operator_fix"):
                    out = hooks.deliver(experiment.operator_fix_message)
                    hooks.settle(
                        idle_s=quiesce_idle_s,
                        timeout_s=quiesce_timeout_s,
                    )
                results["operator_fix"] = {**out, "before_fire": i}
                operator_fix_done = True
                print(f"[operator_fix] {out['status']}")

            ctx = experiment.prepare_fire(fixture)
            ctx["fire"] = i
            owner_before = len(fixture.state["owner"])
            native_marker = hooks.owner_marker()
            with hooks.phase(label):
                fired = hooks.tick()
                # An empty tick started nothing, so there is nothing to wait
                # out; the idle window is for work a tick set in motion.
                settled = (
                    hooks.settle(
                        idle_s=quiesce_idle_s,
                        timeout_s=quiesce_timeout_s,
                    )
                    if fired
                    else True
                )
            row = {
                "fire": i,
                "label": label,
                "events": events,
                "fired": fired,
                "settled": settled,
                **experiment.score_fire(
                    fixture,
                    ctx,
                    messages=(
                        messages_since(fixture, owner_before)
                        + hooks.owner_messages_since(native_marker)
                    ),
                ),
                **hooks.fire_evidence(),
            }
            results["fires"].append(row)
            consecutive_failures = 0 if row["correct"] else consecutive_failures + 1
            print(
                f"[{label}] fired={len(fired)} outcome={row['outcome']} "
                f"score={row['score']}",
            )

        results["recurrences_final"] = hooks.recurrences()
        results["clarifications"] = list(
            getattr(hooks, "owner_clarifications", []),
        )
        # The environment's own spend, apart from the arm's phase figures.
        owner_evidence = hooks.owner_pool.evidence()
        results["persona_exchanges"] = len(owner_evidence["persona_exchanges"])
        results["persona_tokens"] = owner_evidence["persona_tokens"]
    except Exception as exc:  # noqa: BLE001 - a crashed run still writes its record
        import traceback

        results["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
        exit_code = 1
    finally:
        summary = finalize(
            results,
            phases=hooks.phases(),
            results_dir=results_dir,
            experiment=experiment,
            arm=arm,
        )
        try:
            hooks.close()
        except Exception:  # noqa: BLE001 - teardown is best-effort
            pass
        fixture.stop()
        print(f"\n{summary}")
        print(f"[done] results in {results_dir}")
    return exit_code
