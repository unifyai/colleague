"""Per-phase token/cost accounting shared by every proxy-metered arm.

A proxy sees requests, not intentions, so it cannot tell a call that planned
from one that verified or repaired. Every phase here therefore reports its
whole spend under ``planning`` in ``by_purpose`` — the same shape the unify
arm's in-process ledger fills from unify's purpose tags — so a plot can lay
the arms side by side without special-casing who was metered how.
"""

from __future__ import annotations

import json
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


class PhaseLedger:
    """Phase windows over the proxy ledger file (counts + aggregation)."""

    def __init__(self, ledger_path: Path) -> None:
        self.ledger_path = ledger_path
        self.marks: list[tuple[str, int, int, float]] = []

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
                "provider_cost_usd": None,
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
                if row.get("usage_missing"):
                    stats["usage_missing_calls"] += 1
                model = row.get("response_model") or row.get("request_model") or "?"
                stats["models"][model] = stats["models"].get(model, 0) + 1
            stats["by_purpose"] = _purpose_split(stats)
            phases.append(stats)
        background = {
            "name": "background",
            "wall_seconds": 0.0,
            "llm_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "provider_cost_usd": None,
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
        if background["llm_calls"] or background.get("other_http_calls"):
            background["by_purpose"] = _purpose_split(background)
            phases.append(background)
        return phases
