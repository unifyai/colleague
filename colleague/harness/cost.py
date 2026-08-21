"""Resource-neutral cost records shared by machine and human arms.

Correctness is comparable across every arm; its implementation costs are not.
Every scenario nevertheless records elapsed time, and arms may add native
meters.  The human arm adds active labour and prices it at the participant's
declared hourly rate.  Model arms keep reporting tokens/provider spend through
their existing ledgers; a missing provider meter is ``None``, never a false
zero.
"""

from __future__ import annotations

from typing import Any, Mapping


def delta(
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
    *,
    elapsed_seconds: float,
) -> dict[str, Any]:
    """Return one scenario's cost from cumulative arm snapshots."""
    start = dict(before or {})
    end = dict(after or {})
    record: dict[str, Any] = {
        "elapsed_seconds": round(max(0.0, elapsed_seconds), 3),
        "meter": "wall_time",
        # Populated by model-specific ledgers where available.  ``None`` is
        # intentionally distinct from a measured zero-cost execution.
        "provider_cost_usd": None,
    }
    if end.get("meter") == "human_labor":
        active = max(
            0.0,
            float(end.get("active_seconds") or 0.0)
            - float(start.get("active_seconds") or 0.0),
        )
        rate = float(end.get("hourly_rate_usd") or 0.0)
        record.update(
            {
                "meter": "human_labor",
                "human_active_seconds": round(active, 3),
                "human_hourly_rate_usd": rate,
                "human_labor_cost_usd": round(active * rate / 3600.0, 6),
                "participant_id": end.get("participant_id"),
                "turns": max(
                    0,
                    int(end.get("turns") or 0) - int(start.get("turns") or 0),
                ),
            },
        )
    elif end.get("meter") == "model_usage":
        calls = max(
            0,
            int(end.get("llm_calls") or 0) - int(start.get("llm_calls") or 0),
        )
        prompt = max(
            0,
            int(end.get("prompt_tokens") or 0) - int(start.get("prompt_tokens") or 0),
        )
        completion = max(
            0,
            int(end.get("completion_tokens") or 0)
            - int(start.get("completion_tokens") or 0),
        )
        before_cost = start.get("provider_cost_usd")
        after_cost = end.get("provider_cost_usd")
        provider = (
            round(float(after_cost) - float(before_cost or 0.0), 6)
            if after_cost is not None
            else None
        )
        record.update(
            {
                "meter": "model_usage",
                "llm_calls": calls,
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
                "provider_cost_usd": provider,
                "provider_cost_missing_calls": max(
                    0,
                    int(end.get("provider_cost_missing_calls") or 0)
                    - int(start.get("provider_cost_missing_calls") or 0),
                ),
            },
        )
    return record


def total(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Fold scenario cost records without pretending unlike units are equal."""
    out: dict[str, Any] = {
        "elapsed_seconds": round(
            sum(float(r.get("elapsed_seconds") or 0.0) for r in records),
            3,
        ),
        "provider_cost_usd": None,
    }
    measured_provider = [
        float(r["provider_cost_usd"])
        for r in records
        if r.get("provider_cost_usd") is not None
    ]
    if measured_provider:
        out["provider_cost_usd"] = round(sum(measured_provider), 6)
    human = [r for r in records if r.get("meter") == "human_labor"]
    model = [r for r in records if r.get("meter") == "model_usage"]
    if human:
        out.update(
            {
                "meter": "human_labor",
                "human_active_seconds": round(
                    sum(float(r.get("human_active_seconds") or 0.0) for r in human),
                    3,
                ),
                "human_labor_cost_usd": round(
                    sum(float(r.get("human_labor_cost_usd") or 0.0) for r in human),
                    6,
                ),
                "human_hourly_rate_usd": human[-1].get("human_hourly_rate_usd"),
                "participant_id": human[-1].get("participant_id"),
            },
        )
    elif model:
        out.update(
            {
                "meter": "model_usage",
                "llm_calls": sum(int(r.get("llm_calls") or 0) for r in model),
                "prompt_tokens": sum(int(r.get("prompt_tokens") or 0) for r in model),
                "completion_tokens": sum(
                    int(r.get("completion_tokens") or 0) for r in model
                ),
                "total_tokens": sum(int(r.get("total_tokens") or 0) for r in model),
            },
        )
    else:
        out["meter"] = "wall_time"
    return out
