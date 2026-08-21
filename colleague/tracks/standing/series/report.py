"""The run record every arm writes: ``results.json`` and ``summary.md``.

Per-fire token attribution is derived here from the phase table rather than
inside each arm's loop: a fire's spend is the ``<label>`` phase plus its
``<label>_review`` phase where the arm has one, split by purpose. That keeps
``fires[i].tokens`` identical in shape across arms — the CLI arms carry the
whole fire under ``planning``, the unify arm splits it — which is what the
distillation-curve plot reads.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from colleague.tracks.standing.series.spec import Experiment

PURPOSES = ("planning", "verification", "repair")


def empty_tokens() -> dict[str, dict[str, int]]:
    return {p: {"prompt": 0, "completion": 0, "calls": 0} for p in PURPOSES}


def _add_phase(tokens: dict[str, dict[str, int]], phase: dict[str, Any]) -> None:
    split = phase.get("by_purpose") or {}
    if not split:
        # A phase table written before purposes existed: everything planned.
        split = {
            "planning": {
                "llm_calls": int(phase.get("llm_calls") or 0),
                "prompt_tokens": int(phase.get("prompt_tokens") or 0),
                "completion_tokens": int(phase.get("completion_tokens") or 0),
            },
        }
    for purpose, bucket in split.items():
        if purpose not in tokens:
            continue
        tokens[purpose]["prompt"] += int(bucket.get("prompt_tokens") or 0)
        tokens[purpose]["completion"] += int(bucket.get("completion_tokens") or 0)
        tokens[purpose]["calls"] += int(bucket.get("llm_calls") or 0)


def tokens_for_label(
    phases: list[dict[str, Any]],
    label: str,
    *,
    extra_phases: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Tokens of the phase named ``label``, its ``_review``, and ``extra_phases``."""
    tokens = empty_tokens()
    names = {label, f"{label}_review", *extra_phases}
    folded = []
    for phase in phases:
        if phase.get("name") in names:
            _add_phase(tokens, phase)
            folded.append(str(phase.get("name")))
    total = sum(v["prompt"] + v["completion"] for v in tokens.values())
    return {**tokens, "total": total, "phases": folded}


def attach_fire_tokens(
    rows: list[dict[str, Any]],
    phases: list[dict[str, Any]],
    experiment: Experiment,
    *,
    operator_fix_before: int | None = None,
) -> None:
    """Give every fire the tokens spent for it.

    A fire's cost is its own phase plus whatever the model was brought back
    for *before* it: the owner's messages delivered ahead of that fire
    (``message_<i>``…) and, for arms a person fixes, the operator-fix turn
    played before it. Folding those in keeps the per-fire series honest — the
    fire after a change request or a repair is the one that paid for it — and
    each row lists the phases it absorbed.
    """
    for row in rows:
        i = int(row["fire"])
        extra = tuple(
            name
            for name in (str(p.get("name", "")) for p in phases)
            if name == f"message_{i}" or name.startswith(f"message_{i}_")
        )
        if operator_fix_before == i:
            extra += ("operator_fix",)
        row["tokens"] = tokens_for_label(
            phases,
            experiment.label(i),
            extra_phases=extra,
        )


def _cost_for_names(phases: list[dict[str, Any]], names: set[str]) -> dict[str, Any]:
    selected = [p for p in phases if p.get("name") in names]
    provider_missing = any(
        int(p.get("llm_calls") or 0) > 0 and p.get("provider_cost_usd") is None
        for p in selected
    )
    provider_values = [
        float(p["provider_cost_usd"])
        for p in selected
        if p.get("provider_cost_usd") is not None
    ]
    rates = [
        float(p["human_hourly_rate_usd"])
        for p in selected
        if p.get("human_hourly_rate_usd") is not None
    ]
    human_active = round(
        sum(float(p.get("human_active_seconds") or 0.0) for p in selected),
        3,
    )
    llm_calls = sum(int(p.get("llm_calls") or 0) for p in selected)
    return {
        "meter": (
            "human_labor" if rates else ("model_usage" if llm_calls else "wall_time")
        ),
        "elapsed_seconds": round(
            sum(float(p.get("wall_seconds") or 0.0) for p in selected),
            3,
        ),
        "provider_cost_usd": (
            None
            if provider_missing or not provider_values
            else round(sum(provider_values), 6)
        ),
        "provider_cost_missing_calls": sum(
            int(p.get("provider_cost_missing_calls") or 0) for p in selected
        ),
        "llm_calls": llm_calls,
        "prompt_tokens": sum(int(p.get("prompt_tokens") or 0) for p in selected),
        "completion_tokens": sum(
            int(p.get("completion_tokens") or 0) for p in selected
        ),
        "total_tokens": sum(int(p.get("total_tokens") or 0) for p in selected),
        "human_active_seconds": human_active,
        "human_hourly_rate_usd": rates[-1] if rates else None,
        "human_labor_cost_usd": round(
            sum(float(p.get("human_labor_cost_usd") or 0.0) for p in selected),
            6,
        ),
        "phases": [str(p.get("name")) for p in selected],
    }


def attach_fire_cost(
    rows: list[dict[str, Any]],
    phases: list[dict[str, Any]],
    experiment: Experiment,
    *,
    operator_fix_before: int | None = None,
) -> None:
    """Attach resource-neutral elapsed/provider/labour cost to every fire."""
    for row in rows:
        i = int(row["fire"])
        names = {experiment.label(i), f"{experiment.label(i)}_review"}
        names.update(
            str(p.get("name"))
            for p in phases
            if p.get("name") == f"message_{i}"
            or str(p.get("name", "")).startswith(f"message_{i}_")
        )
        if operator_fix_before == i:
            names.add("operator_fix")
        row["cost"] = _cost_for_names(phases, names)


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, (list, dict)):
        return json.dumps(value, separators=(",", ":"))[:60]
    return str(value)


def render_summary(
    results: dict[str, Any],
    *,
    experiment: Experiment,
    arm: str,
) -> str:
    lines = [
        f"# {experiment.name}{experiment.run_suffix()} ({arm} arm) — {results['run_id']}",
        "",
    ]
    if results.get("model"):
        lines.append(f"- model: `{results['model']}` via recording proxy -> OpenRouter")
    if results.get("orchestra_url"):
        lines.append(f"- orchestra: `{results['orchestra_url']}`")
    for key, value in experiment.describe().items():
        lines.append(f"- {key}: `{value}`")
    lines += [
        "",
        "| phase | LLM calls | prompt tok | completion tok | planning | verification | repair | wall (s) | provider USD | human active (s) | labour USD |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in results.get("phases", []):
        split = p.get("by_purpose") or {}

        def _tot(purpose: str) -> int:
            b = split.get(purpose) or {}
            return int(b.get("prompt_tokens") or 0) + int(
                b.get("completion_tokens") or 0,
            )

        lines.append(
            f"| {p['name']} | {p.get('llm_calls', 0)} | {p.get('prompt_tokens', 0)} | "
            f"{p.get('completion_tokens', 0)} | {_tot('planning')} | "
            f"{_tot('verification')} | {_tot('repair')} | {p.get('wall_seconds', 0)} |"
            f" {p.get('provider_cost_usd') if p.get('provider_cost_usd') is not None else '—'} |"
            f" {p.get('human_active_seconds', 0)} | {p.get('human_labor_cost_usd', 0)} |",
        )
    columns = [
        "fire",
        "events",
        "outcome",
        "score",
        *experiment.fire_columns,
        "tokens",
        "cost",
    ]
    lines += [
        "",
        "| " + " | ".join(columns) + " |",
        "|" + "---|" * len(columns),
    ]
    for r in results.get("fires", []):
        cells = []
        for c in columns:
            if c == "tokens":
                t = r.get("tokens") or {}
                cells.append(
                    f"{t.get('total', 0)} "
                    f"(p{sum((t.get('planning') or {}).get(k, 0) for k in ('prompt', 'completion'))}"
                    f"/v{sum((t.get('verification') or {}).get(k, 0) for k in ('prompt', 'completion'))}"
                    f"/r{sum((t.get('repair') or {}).get(k, 0) for k in ('prompt', 'completion'))})",
                )
            elif c == "cost":
                cost = r.get("cost") or {}
                if float(cost.get("human_active_seconds") or 0.0):
                    cells.append(
                        f"{cost.get('human_active_seconds', 0)}s / "
                        f"${cost.get('human_labor_cost_usd', 0)} labour",
                    )
                elif cost.get("provider_cost_usd") is not None:
                    cells.append(f"${cost.get('provider_cost_usd')} provider")
                else:
                    cells.append(f"{cost.get('elapsed_seconds', 0)}s")
            elif c == "events":
                cells.append(", ".join(r.get("events") or []) or "-")
            else:
                cells.append(_fmt(r.get(c, "")))
        lines.append("| " + " | ".join(cells) + " |")
    if results.get("series"):
        lines += ["", "Series findings:", ""]
        for key, value in results["series"].items():
            lines.append(f"- {key}: `{json.dumps(value, default=str)}`")
    scored = [r for r in results.get("fires", [])]
    if scored:
        total = sum(int(r.get("score") or 0) for r in scored)
        lines += [
            "",
            f"Total score: {total} / {2 * len(scored)} "
            f"({sum(1 for r in scored if r.get('correct'))} correct, "
            f"{sum(1 for r in scored if r.get('held'))} held, "
            f"{sum(1 for r in scored if r.get('outcome') == 'wrong')} wrong)",
        ]
    return "\n".join(lines) + "\n"


def finalize(
    results: dict[str, Any],
    *,
    phases: list[dict[str, Any]],
    results_dir: Path,
    experiment: Experiment,
    arm: str,
) -> str:
    """Attach phases and per-fire tokens, write both files, return the summary."""
    results["phases"] = phases
    results["cost"] = _cost_for_names(
        phases,
        {str(p.get("name")) for p in phases},
    )
    if results["cost"]["meter"] == "human_labor":
        results["cost"]["participant_id"] = results.get("participant_id")
    fix = results.get("operator_fix")
    attach_fire_tokens(
        results.get("fires", []),
        phases,
        experiment,
        operator_fix_before=(
            int(fix["before_fire"])
            if isinstance(fix, dict) and fix.get("before_fire")
            else None
        ),
    )
    attach_fire_cost(
        results.get("fires", []),
        phases,
        experiment,
        operator_fix_before=(
            int(fix["before_fire"])
            if isinstance(fix, dict) and fix.get("before_fire")
            else None
        ),
    )
    results["series"] = experiment.summarize(results.get("fires", []))
    results["finished_at"] = datetime.now(timezone.utc).isoformat()
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / "results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    summary = render_summary(results, experiment=experiment, arm=arm)
    (results_dir / "summary.md").write_text(summary, encoding="utf-8")
    return summary
