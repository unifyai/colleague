"""Per-phase token/cost accounting shared by every proxy-metered arm.

A proxy sees requests, not intentions, so it cannot tell a call that planned
from one that verified or repaired. Every phase here therefore reports its
whole spend under ``planning`` in ``by_purpose`` — the same shape the unify
arm's in-process ledger fills from unify's purpose tags — so a plot can lay
the arms side by side without special-casing who was metered how.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

PURPOSES = ("planning", "verification", "repair")


def _purpose_split(stats: dict[str, Any]) -> dict[str, dict[str, int]]:
    split = {
        p: {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
        for p in PURPOSES
    }
    split["planning"] = {
        "llm_calls": int(stats["llm_calls"]),
        "prompt_tokens": int(stats["prompt_tokens"]),
        "completion_tokens": int(stats["completion_tokens"]),
    }
    return split


def _row_cost(row: dict[str, Any]) -> float | None:
    usage = row.get("usage_raw") or {}
    value = usage.get("cost") if isinstance(usage, dict) else None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class PhaseLedger:
    """Phase windows over the proxy ledger file (counts + aggregation)."""

    def __init__(self, ledger_path: Path) -> None:
        self.ledger_path = ledger_path
        self.marks: list[tuple[str, int, int, float]] = []
        self._boundary_row = 0
        self._boundary_time = time.monotonic()

    def _lines(self) -> list[dict[str, Any]]:
        if not self.ledger_path.exists():
            return []
        rows = []
        for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def count(self) -> int:
        return len(self._lines())

    def mark(self, name: str, start: int, end: int, wall: float) -> None:
        self.marks.append((name, start, end, wall))

    def boundary(self, name: str) -> None:
        """Close a phase window at the current row count.

        The session-facing twin of ``mark``: a turn-driven arm knows only
        that a turn just ended, never row indices, so each boundary claims
        every row since the previous one. Windows built either way
        aggregate identically in ``summarize``.
        """
        end = self.count()
        now = time.monotonic()
        self.mark(name, self._boundary_row, end, now - self._boundary_time)
        self._boundary_row = end
        self._boundary_time = now

    def segments(self) -> list[dict[str, Any]]:
        """The phase windows as plain dicts — ``summarize`` under the name
        the session interface uses."""
        return self.summarize()

    def cost_snapshot(self) -> dict[str, Any]:
        """Whole-file counters in the shape the runner diffs per scenario.

        The void-cost rule lives here once, for every proxy-metered arm: a
        single call the provider did not price voids the sum (``None``,
        never a partial total masquerading as the whole).
        """
        rows = [
            r
            for r in self._lines()
            if "/chat/completions" in str(r.get("path", ""))
        ]
        costs: list[float] = []
        missing = 0
        for row in rows:
            value = _row_cost(row)
            if value is None:
                missing += 1
            else:
                costs.append(value)
        return {
            "meter": "model_usage",
            "llm_calls": len(rows),
            "prompt_tokens": sum(int(r.get("prompt_tokens") or 0) for r in rows),
            "completion_tokens": sum(
                int(r.get("completion_tokens") or 0) for r in rows
            ),
            "provider_cost_usd": round(sum(costs), 6) if not missing else None,
            "provider_cost_missing_calls": missing,
        }

    def summarize(self) -> list[dict[str, Any]]:
        rows = self._lines()
        phases = []
        covered: set[int] = set()
        for name, start, end, wall in self.marks:
            stats = {
                "name": name,
                "wall_seconds": round(wall, 2),
                "llm_calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "provider_cost_usd": 0.0,
                "provider_cost_missing_calls": 0,
                "usage_missing_calls": 0,
                "other_http_calls": 0,
                "models": {},
            }
            for idx in range(start, min(end, len(rows))):
                row = rows[idx]
                covered.add(idx)
                # Only completion requests are LLM calls; catalog/model GETs
                # are free metadata traffic and would inflate the count.
                if "/chat/completions" not in str(row.get("path", "")):
                    stats["other_http_calls"] += 1
                    continue
                stats["llm_calls"] += 1
                stats["prompt_tokens"] += int(row.get("prompt_tokens") or 0)
                stats["completion_tokens"] += int(row.get("completion_tokens") or 0)
                stats["total_tokens"] += int(row.get("total_tokens") or 0)
                row_cost = _row_cost(row)
                if row_cost is None:
                    stats["provider_cost_missing_calls"] += 1
                else:
                    stats["provider_cost_usd"] += row_cost
                if row.get("usage_missing"):
                    stats["usage_missing_calls"] += 1
                model = row.get("response_model") or row.get("request_model") or "?"
                stats["models"][model] = stats["models"].get(model, 0) + 1
            stats["by_purpose"] = _purpose_split(stats)
            if stats["llm_calls"] and stats["provider_cost_missing_calls"]:
                stats["provider_cost_usd"] = None
            else:
                stats["provider_cost_usd"] = round(float(stats["provider_cost_usd"]), 6)
            phases.append(stats)
        background = {
            "name": "background",
            "wall_seconds": 0.0,
            "llm_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "provider_cost_usd": 0.0,
            "provider_cost_missing_calls": 0,
            "usage_missing_calls": 0,
            "models": {},
        }
        for idx, row in enumerate(rows):
            if idx in covered:
                continue
            if "/chat/completions" not in str(row.get("path", "")):
                background["other_http_calls"] = (
                    background.get("other_http_calls", 0) + 1
                )
                continue
            background["llm_calls"] += 1
            background["prompt_tokens"] += int(row.get("prompt_tokens") or 0)
            background["completion_tokens"] += int(row.get("completion_tokens") or 0)
            background["total_tokens"] += int(row.get("total_tokens") or 0)
            row_cost = _row_cost(row)
            if row_cost is None:
                background["provider_cost_missing_calls"] += 1
            else:
                background["provider_cost_usd"] += row_cost
        if background["llm_calls"] or background.get("other_http_calls"):
            if background["llm_calls"] and background["provider_cost_missing_calls"]:
                background["provider_cost_usd"] = None
            else:
                background["provider_cost_usd"] = round(
                    float(background["provider_cost_usd"]),
                    6,
                )
            background["by_purpose"] = _purpose_split(background)
            phases.append(background)
        return phases
