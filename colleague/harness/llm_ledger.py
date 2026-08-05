"""Per-phase LLM accounting for benchmark runs.

Registers a unillm LLM event listener and records every completed LLM call
(model, token usage, provider cost). Phases mark index windows over the ledger,
so each benchmark phase (setup, run_1, run_2, ...) gets an exact
call/token/cost attribution. Calls that land outside any phase window are
attributed to a "background" bucket rather than silently dropped.

The listener fires synchronously inside the LLM client after each completion,
from whatever thread made the call, so accounting is complete regardless of
asyncio/thread topology. Non-streaming calls only (the Unify runtime does not
stream), so usage is always present on the response.

unillm isolates a listener that raises, so a ledger whose callback drifts out
of step with `LLMEvent` records nothing and reports $0 — a missing measurement
that reads as a free run. `install` drives a synthetic event through the real
callback to make that mismatch fail immediately, and `metering_fault` reports
any loss that happened during the run.

Failed calls are recorded too, via a LiteLLM failure callback rather than the
unillm hook, which only ever sees completions. Without them a provider timeout
is invisible to the harness, and a scorer cannot tell "the system found
nothing" from "the call that would have found it died" — see `install`.

Lived in `tracks/standing/recurring_report/measure.py` first; promoted here
once the conversational tracks needed the same metering — the unify arm has
no proxy in front of it, so without this hook its token column is simply
empty while every CLI arm is metered. `measure` re-exports for the standing
drivers.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from unillm import add_llm_event_listener
from unillm.llm_events import LLMEvent


@dataclass
class LLMCallRecord:
    ts: float
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    provider_cost: float | None
    origin: str | None
    usage_raw: dict[str, Any] | None
    # Set only on a call that never completed. A failure carries no usage and
    # no cost, so it lives in the same list purely to share the index space the
    # phase windows are cut from — see `_on_litellm_failure`.
    error: str | None = None
    status_code: int | None = None
    detail: str | None = None

    @property
    def failed(self) -> bool:
        return self.error is not None

    def to_json(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "provider_cost": self.provider_cost,
            "origin": self.origin,
            "usage_raw": self.usage_raw,
            "error": self.error,
            "status_code": self.status_code,
            "detail": self.detail,
        }


@dataclass
class PhaseStats:
    name: str
    wall_seconds: float = 0.0
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    provider_cost: float = 0.0
    models: dict[str, int] = field(default_factory=dict)
    failed_calls: int = 0
    errors: dict[str, int] = field(default_factory=dict)

    def add(self, record: LLMCallRecord) -> None:
        if record.failed:
            # Counted apart from `llm_calls` on purpose. Callers read
            # `llm_calls == 0` as "this phase was never metered" to label a
            # void cost column; folding failures in would make an unmetered
            # phase look metered and silently un-void the cost.
            self.failed_calls += 1
            key = record.error or "unknown"
            self.errors[key] = self.errors.get(key, 0) + 1
            return
        self.llm_calls += 1
        self.prompt_tokens += record.prompt_tokens
        self.completion_tokens += record.completion_tokens
        self.total_tokens += record.total_tokens
        self.provider_cost += record.provider_cost or 0.0
        self.models[record.model] = self.models.get(record.model, 0) + 1

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "wall_seconds": round(self.wall_seconds, 2),
            "llm_calls": self.llm_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "provider_cost_usd": round(self.provider_cost, 6),
            "models": self.models,
            "failed_calls": self.failed_calls,
            "errors": self.errors,
        }


def _extract_usage(event: LLMEvent) -> tuple[int, int, int, dict[str, Any] | None]:
    response = event.response or {}
    usage = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(usage, dict):
        return 0, 0, 0, None
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or (prompt + completion))
    return prompt, completion, total, usage


class LLMLedger:
    """Append-only record of every LLM call in the process, with phase windows."""

    def __init__(self, *, capture_requests_path: Path | None = None) -> None:
        self._records: list[LLMCallRecord] = []
        self._lock = threading.Lock()
        self._phase_marks: list[tuple[str, int, int, float]] = []
        self._boundaries: list[tuple[str, int, float | None]] = []
        self._listener: Any = None
        self._failure_hook_installed = False
        # Full request bodies enable offline replay of specific decision
        # points (rerun a critical call with modified prompts without paying
        # for a whole run). Written as JSONL; large, so results .gitignore
        # files keep it out of version control.
        self._capture_requests_path = capture_requests_path

    def install(self) -> None:
        """Register as a unillm listener, after self-testing the record path.

        Listener registration is additive and process-global, so this coexists
        with the EventBus listener unify.init() registers regardless of which
        ran first, and neither displaces the other.

        Also registers a LiteLLM failure callback, because the unillm event
        hook structurally cannot report a failure: LLMEvent carries only
        request/response/cost/origin and fires *after* a completion, so a call
        that never completed produces no event at all. That blind spot is not
        cosmetic — a provider timeout looked identical to "the system chose not
        to flag anything", which is precisely how an infrastructure fault got
        recorded as a detection miss. LiteLLM is the transport under every
        provider call here, and its failure_callback is the one place in this
        repo's reach where a dead call is observable.

        Raises:
            RuntimeError: if the record path cannot handle a synthetic event,
                which means this ledger and the installed unillm disagree about
                LLMEvent and every total would come out zero.
        """
        self._self_test()
        self._listener = add_llm_event_listener(self._on_event)
        try:
            import litellm

            if self._on_litellm_failure not in litellm.failure_callback:
                litellm.failure_callback.append(self._on_litellm_failure)
                self._failure_hook_installed = True
        except Exception:
            pass  # metering must never be what breaks a paid run

    def _self_test(self) -> None:
        """Prove the record path works before the run spends anything.

        unillm calls a listener inside a try/except so a raising listener can
        never fail an LLM call. That isolation means a `_on_event` which reads a
        field `LLMEvent` no longer carries records nothing at all, and the run
        ends with a $0 phase table that looks like a free run rather than a
        broken measurement — the exact way three runs were lost. Driving one
        synthetic event through the real callback, unguarded, turns that whole
        class of drift into an error at t=0, before any provider is paid.

        Drives the same callback that gets registered, then discards whatever it
        recorded, so the probe is exactly as representative as the real path and
        still leaves no record or captured request behind. Runs before
        registration, so nothing else can be writing to `_records`.
        """
        before = self._count()
        capture, self._capture_requests_path = self._capture_requests_path, None
        try:
            self._on_event(
                LLMEvent(
                    request={"model": "probe/metering-self-test"},
                    response={
                        "usage": {
                            "prompt_tokens": 1,
                            "completion_tokens": 1,
                            "total_tokens": 2,
                        },
                    },
                    provider_cost=0.0,
                ),
            )
            recorded = self._count() - before
        except Exception as exc:
            raise RuntimeError(
                "LLM metering is broken: recording an event raised "
                f"{type(exc).__name__}: {exc}. This ledger and the installed "
                "unillm disagree about LLMEvent, so every cost and token total "
                "would be reported as zero. Refusing to start a paid run.",
            ) from exc
        finally:
            self._capture_requests_path = capture
            with self._lock:
                del self._records[before:]
        if recorded != 1:
            raise RuntimeError(
                "LLM metering is broken: recording a synthetic event produced "
                f"{recorded} records instead of 1. Refusing to start a paid run "
                "that could not be measured.",
            )

    def metering_fault(self) -> str | None:
        """Why these totals cannot be trusted, or None when they can.

        Distinguishes "nothing was spent" from "spending was not observed", so a
        zero-cost phase table is never read as a free run.
        """
        if self._listener is None:
            return "ledger was never installed; no LLM call was observed"
        if not self._listener.healthy:
            return (
                f"{self._listener.failed} event(s) were lost: "
                f"{self._listener.last_error!r}"
            )
        return None

    def require_metering(self) -> None:
        """Raise if any observed spending went unrecorded."""
        fault = self.metering_fault()
        if fault is not None:
            raise RuntimeError(f"LLM metering is unreliable: {fault}")

    def uninstall(self) -> None:
        if self._listener is not None:
            self._listener.remove()
            self._listener = None
        if self._failure_hook_installed:
            try:
                import litellm

                litellm.failure_callback.remove(self._on_litellm_failure)
            except Exception:
                pass
            self._failure_hook_installed = False

    def _on_litellm_failure(
        self,
        kwargs: Any = None,
        response_obj: Any = None,
        start_time: Any = None,
        end_time: Any = None,
    ) -> None:
        """Record a provider call that never returned a completion.

        Appended to the same `_records` list as successes so it lands inside
        whichever phase window is open — the windows are cut by list index, so
        a separate list would need a parallel set of boundaries to attribute.
        `PhaseStats.add` keeps the two apart once the window is resolved.
        """
        try:
            exc = (kwargs or {}).get("exception")
            model = str((kwargs or {}).get("model") or "unknown")
            status = getattr(exc, "status_code", None)
            record = LLMCallRecord(
                ts=time.time(),
                model=model,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                provider_cost=None,
                origin="litellm.failure_callback",
                usage_raw=None,
                error=type(exc).__name__ if exc is not None else "UnknownError",
                status_code=status if isinstance(status, int) else None,
                detail=" ".join(str(exc).split())[:300] if exc is not None else None,
            )
            with self._lock:
                self._records.append(record)
        except Exception:
            pass  # a metering callback must never surface into the run

    def failures(self) -> list[LLMCallRecord]:
        with self._lock:
            return [r for r in self._records if r.failed]

    def _on_event(self, event: LLMEvent) -> None:
        prompt, completion, total, usage = _extract_usage(event)
        record = LLMCallRecord(
            ts=time.time(),
            model=str((event.request or {}).get("model") or "unknown"),
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            provider_cost=event.provider_cost,
            origin=event.origin,
            usage_raw=usage,
        )
        with self._lock:
            self._records.append(record)
            if self._capture_requests_path is not None:
                try:
                    with open(
                        self._capture_requests_path,
                        "a",
                        encoding="utf-8",
                    ) as f:
                        f.write(
                            json.dumps(
                                {"ts": record.ts, "request": event.request},
                                default=str,
                            )
                            + "\n",
                        )
                except Exception:
                    pass  # capture is best-effort; never break accounting

    def _count(self) -> int:
        with self._lock:
            return len(self._records)

    def last_event_ts(self) -> float | None:
        with self._lock:
            return self._records[-1].ts if self._records else None

    async def wait_quiescent(
        self,
        *,
        idle_seconds: float,
        timeout_seconds: float,
        poll_seconds: float = 2.0,
    ) -> bool:
        """Wait until no LLM call has completed for idle_seconds.

        Detached post-run work (storage/librarian reviews) outlives the act
        handle's result. In production, wakes are a week apart so reviews
        always finish between runs; this barrier restores that invariant in
        compressed simulation and makes per-phase attribution exact. Returns
        False when timeout_seconds elapses with activity still ongoing.
        """
        barrier_start = time.monotonic()
        barrier_start_wall = time.time()
        while True:
            last = self.last_event_ts()
            reference = last if last is not None else barrier_start_wall
            if time.time() - reference >= idle_seconds:
                return True
            if time.monotonic() - barrier_start >= timeout_seconds:
                return False
            await asyncio.sleep(poll_seconds)

    def boundary(self, name: str) -> None:
        """Mark the start of a named segment at the current ledger position.

        The `phase` context manager needs the caller to hold a `with` block
        open across the work, which a session adapter cannot do — `begin`
        returns before the turn finishes. A boundary is the fire-and-forget
        version: everything recorded after it (until the next boundary)
        belongs to it. `segments()` turns the marks into PhaseStats.
        """
        with self._lock:
            self._boundaries.append((name, len(self._records), time.monotonic()))

    def segments(self) -> list[PhaseStats]:
        """Stats between consecutive boundaries; the last runs to the end.

        Calls recorded before the first boundary land in a leading "setup"
        segment, so nothing is silently dropped.
        """
        with self._lock:
            records = list(self._records)
            marks = list(self._boundaries)
        out: list[PhaseStats] = []
        if marks and marks[0][1] > 0:
            marks.insert(0, ("setup", 0, None))
        for i, (name, start, t0) in enumerate(marks):
            end = marks[i + 1][1] if i + 1 < len(marks) else len(records)
            t1 = marks[i + 1][2] if i + 1 < len(marks) else time.monotonic()
            stats = PhaseStats(
                name=name,
                wall_seconds=(t1 - t0) if (t0 is not None and t1 is not None) else 0.0,
            )
            for idx in range(start, end):
                stats.add(records[idx])
            out.append(stats)
        return out

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        start_idx = self._count()
        t0 = time.monotonic()
        try:
            yield
        finally:
            wall = time.monotonic() - t0
            self._phase_marks.append((name, start_idx, self._count(), wall))

    def summarize(self) -> list[PhaseStats]:
        """Phase stats in order, plus a trailing "background" bucket for calls
        that landed outside every phase window."""
        with self._lock:
            records = list(self._records)
        phases: list[PhaseStats] = []
        covered: set[int] = set()
        for name, start, end, wall in self._phase_marks:
            stats = PhaseStats(name=name, wall_seconds=wall)
            for idx in range(start, end):
                stats.add(records[idx])
                covered.add(idx)
            phases.append(stats)
        background = PhaseStats(name="background")
        for idx, record in enumerate(records):
            if idx not in covered:
                background.add(record)
        if background.llm_calls:
            phases.append(background)
        return phases

    def dump(self, path: Path) -> None:
        with self._lock:
            records = list(self._records)
        with open(path, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record.to_json(), default=str) + "\n")
