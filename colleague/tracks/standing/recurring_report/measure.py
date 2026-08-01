"""Per-phase LLM accounting for benchmark runs.

Installs unillm's process-global LLM event hook and records every completed
LLM call (model, token usage, provider cost). Phases mark index windows over
the ledger, so each benchmark phase (setup, run_1, run_2, ...) gets an exact
call/token/cost attribution. Calls that land outside any phase window are
attributed to a "background" bucket rather than silently dropped.

The hook fires synchronously inside the LLM client after each completion, from
whatever thread made the call, so accounting is complete regardless of
asyncio/thread topology. Non-streaming calls only (the Unify runtime does not
stream), so usage is always present on the response.
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

from unillm import get_global_llm_event_hook, set_global_llm_event_hook
from unillm.llm_events import LLMEvent


@dataclass
class LLMCallRecord:
    ts: float
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    provider_cost: float | None
    billed_cost: float | None
    origin: str | None
    usage_raw: dict[str, Any] | None

    def to_json(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "provider_cost": self.provider_cost,
            "billed_cost": self.billed_cost,
            "origin": self.origin,
            "usage_raw": self.usage_raw,
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

    def add(self, record: LLMCallRecord) -> None:
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
        self._chained_hook: Any = None
        # Full request bodies enable offline replay of specific decision
        # points (rerun a critical call with modified prompts without paying
        # for a whole run). Written as JSONL; large, so results .gitignore
        # files keep it out of version control.
        self._capture_requests_path = capture_requests_path

    def install(self) -> None:
        """Install as the process-global hook, chaining any existing hook.

        unify.init() installs its own global hook (EventBus wiring), and
        set_global_llm_event_hook is last-write-wins — so this must run
        AFTER unify.init(), and the pre-existing hook is forwarded to so
        production wiring keeps working.
        """
        self._chained_hook = get_global_llm_event_hook()
        set_global_llm_event_hook(self._on_event)

    def uninstall(self) -> None:
        set_global_llm_event_hook(self._chained_hook)
        self._chained_hook = None

    def _on_event(self, event: LLMEvent) -> None:
        prompt, completion, total, usage = _extract_usage(event)
        record = LLMCallRecord(
            ts=time.time(),
            model=str((event.request or {}).get("model") or "unknown"),
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            provider_cost=event.provider_cost,
            billed_cost=event.billed_cost,
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
        if self._chained_hook is not None:
            try:
                self._chained_hook(event)
            except Exception:
                pass  # never let downstream wiring break accounting

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
