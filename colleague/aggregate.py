"""Merge shard results into one summary.

Every matrix job uploads a `results.json`. This walks a directory of those,
merges them, and prints a markdown table suitable for a GitHub job summary
plus a combined JSON artifact.

`UNSUPPORTED` is reported in its own column and kept out of every accuracy
figure, the same as it is per-run. An arm that has no mechanism for a track
should be visible as such in the summary rather than dragging an average
down where a reader will mistake it for a loss.

    python -m colleague.aggregate artifacts/ --out summary.md --json merged.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from colleague import taxonomy
from colleague.harness.cost import total as total_cost

ORDER = ("pass", "degraded", "fail", "unsupported", "invalid", "error")
GLYPH = {
    "pass": "✅",
    "degraded": "🟡",
    "fail": "❌",
    "unsupported": "➖",
    # A persona leaked forbidden content: the cell is void — not a gifted
    # PASS, not an unearned FAIL, never in an accuracy denominator. Repeats
    # provide replacement samples.
    "invalid": "🚫",
    "error": "💥",
}


def _cost_from_phases(phases: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Lift old phase-ledger runs into the common run-cost schema."""
    if not phases:
        return None
    calls = sum(int(p.get("llm_calls") or 0) for p in phases)
    rates = [
        float(p["human_hourly_rate_usd"])
        for p in phases
        if p.get("human_hourly_rate_usd") is not None
    ]
    provider_missing = any(
        int(p.get("llm_calls") or 0) > 0 and p.get("provider_cost_usd") is None
        for p in phases
    )
    provider_values = [
        float(p["provider_cost_usd"])
        for p in phases
        if p.get("provider_cost_usd") is not None
    ]
    return {
        "meter": (
            "human_labor" if rates else ("model_usage" if calls else "wall_time")
        ),
        "elapsed_seconds": round(
            sum(float(p.get("wall_seconds") or 0.0) for p in phases),
            3,
        ),
        "llm_calls": calls,
        "prompt_tokens": sum(int(p.get("prompt_tokens") or 0) for p in phases),
        "completion_tokens": sum(int(p.get("completion_tokens") or 0) for p in phases),
        "total_tokens": sum(int(p.get("total_tokens") or 0) for p in phases),
        "provider_cost_usd": (
            None
            if provider_missing or not provider_values
            else round(sum(provider_values), 6)
        ),
        "provider_cost_missing_calls": sum(
            int(p.get("provider_cost_missing_calls") or 0) for p in phases
        ),
        "human_active_seconds": round(
            sum(float(p.get("human_active_seconds") or 0.0) for p in phases),
            3,
        ),
        "human_hourly_rate_usd": rates[-1] if rates else None,
        "human_labor_cost_usd": round(
            sum(float(p.get("human_labor_cost_usd") or 0.0) for p in phases),
            6,
        ),
    }


def load(root: Path) -> list[dict[str, Any]]:
    """Every results.json under ``root``, one per run_id.

    Deduplication is load-bearing rather than tidy. Each shard uploads its
    track's whole results tree, so a results file that ever reaches the repo
    is re-uploaded by every later shard — and a sweep merges the same stale
    run dozens of times, from a code version that no longer exists, as if it
    were part of the fresh one.
    """
    runs: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("results.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            print(f"skipping {path}: {exc}", file=sys.stderr)
            continue
        key = str(data.get("run_id") or path)
        runs[key] = data
    return list(runs.values())


def merge(runs: list[dict[str, Any]]) -> dict[str, Any]:
    # (track, arm) -> scenario -> [outcomes across repeats]
    grid: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list),
    )
    tracks: set[str] = set()
    arms: set[str] = set()
    persona_tokens = 0
    persona_exchanges = 0
    costs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        # The `standing` experiments predate this runner and name the same
        # two things `experiment` and `system`. Accepting both means a sweep
        # can merge old and new results without rewriting the old ones.
        track = run.get("track") or run.get("experiment")
        arm = run.get("arm") or run.get("system")
        if not track or not arm:
            continue
        arm = {"hermes-agent": "hermes"}.get(arm, arm)
        if arm == "human" and run.get("human_mode"):
            arm = f"human-{run['human_mode']}"
        tracks.add(track)
        arms.add(arm)
        scenarios = run.get("scenarios", [])
        for scenario in scenarios:
            outcome = (scenario.get("result") or {}).get("outcome", "fail")
            grid[(track, arm)][scenario["name"]].append(outcome)
            ev = scenario.get("evidence") or {}
            persona_tokens += int(ev.get("persona_tokens") or 0)
            persona_exchanges += len(ev.get("persona_exchanges") or [])
        fires = run.get("fires", [])
        for fire in fires:
            name = str(
                fire.get("label")
                or fire.get("task")
                or fire.get("automation")
                or f"fire_{fire.get('fire', '?')}",
            )
            if fire.get("outcome") == "correct" or fire.get("correct") is True:
                outcome = "pass"
            elif fire.get("outcome") == "held" or fire.get("held") is True:
                outcome = "degraded"
            else:
                outcome = "fail"
            grid[(track, arm)][name].append(outcome)

        run_cost = run.get("cost")
        if not run_cost:
            unit_costs = [
                dict(item["cost"]) for item in [*scenarios, *fires] if item.get("cost")
            ]
            if unit_costs:
                run_cost = total_cost(unit_costs)
        if not run_cost:
            run_cost = _cost_from_phases(run.get("phases") or [])
        if run_cost:
            costs[arm].append(dict(run_cost))
    return {
        "tracks": sorted(tracks),
        "arms": sorted(arms),
        "grid": {f"{t}|{a}": dict(v) for (t, a), v in grid.items()},
        "runs": len(runs),
        # Reported apart from every arm figure: the environment's spend, not
        # the system under test's.
        "persona_tokens": persona_tokens,
        "persona_exchanges": persona_exchanges,
        "costs": dict(costs),
    }


def _cell(outcomes: list[str]) -> str:
    if not outcomes:
        return "·"
    if len(set(outcomes)) == 1:
        glyph = GLYPH.get(outcomes[0], "?")
        return glyph if len(outcomes) == 1 else f"{glyph}×{len(outcomes)}"
    # Repeats disagreed. That is a result about reliability, not noise to
    # average away, so the spread is shown rather than a majority verdict.
    counts = {o: outcomes.count(o) for o in ORDER if o in outcomes}
    return " ".join(f"{GLYPH.get(o, '?')}{n}" for o, n in counts.items())


def to_markdown(merged: dict[str, Any]) -> str:
    arms = merged["arms"]
    lines = [
        "## Colleague benchmark",
        "",
        f"{merged['runs']} shard results merged.",
        "",
        "✅ pass · 🟡 degraded · ❌ fail · ➖ no mechanism (excluded from "
        "accuracy) · 🚫 void (persona leak; excluded from accuracy)",
        "",
    ]
    # Sections are grouped by taxonomy topic, topics in declaration order.
    # A track the taxonomy cannot place still renders, in a trailing group —
    # a summary must never silently hide results it cannot categorise.
    by_topic: dict[str | None, list[str]] = defaultdict(list)
    for track in merged["tracks"]:
        by_topic[taxonomy.topic_of_result_track(track)].append(track)
    ordered = [s for s in taxonomy.TOPICS if s in by_topic]
    if None in by_topic:
        ordered.append(None)
    for slug in ordered:
        topic_open = False
        for track in by_topic[slug]:
            scenarios: list[str] = []
            for arm in arms:
                scenarios.extend(merged["grid"].get(f"{track}|{arm}", {}).keys())
            seen: list[str] = []
            for s in scenarios:
                if s not in seen:
                    seen.append(s)
            if not seen:
                continue
            if not topic_open:
                lines.append(f"### {taxonomy.topic_title(slug)}")
                lines.append("")
                topic_open = True
            tagged = any(taxonomy.tags_for(track, s) for s in seen)
            lines.append(f"#### {track}")
            lines.append("")
            header = ["scenario", *arms] + (["tags"] if tagged else [])
            lines.append("| " + " | ".join(header) + " |")
            lines.append("|---" * len(header) + "|")
            for scenario in seen:
                row = [scenario]
                for arm in arms:
                    row.append(
                        _cell(
                            merged["grid"].get(f"{track}|{arm}", {}).get(scenario, []),
                        ),
                    )
                if tagged:
                    tags = taxonomy.tags_for(track, scenario)
                    row.append(tags.compact() if tags else "")
                lines.append("| " + " | ".join(row) + " |")
            lines.append("")

    lines.append("### Credited rate by arm")
    lines.append("")
    lines.append("| arm | credited | scored | unsupported | invalid | rate |")
    lines.append("|---|---|---|---|---|---|")
    for arm in arms:
        credited = scored = unsupported = invalid = 0
        for key, scenarios in merged["grid"].items():
            if not key.endswith(f"|{arm}"):
                continue
            for outcomes in scenarios.values():
                for o in outcomes:
                    if o == "unsupported":
                        unsupported += 1
                        continue
                    if o == "invalid":
                        # Void by environment fault, not a statement about
                        # the arm — reported, never in the denominator.
                        invalid += 1
                        continue
                    scored += 1
                    if o in ("pass", "degraded"):
                        credited += 1
        rate = f"{credited / scored:.0%}" if scored else "—"
        lines.append(
            f"| {arm} | {credited} | {scored} | {unsupported} | {invalid} "
            f"| {rate} |",
        )

    lines += [
        "",
        "### Cost by arm",
        "",
        "Elapsed time is universal. Human labour is active participant time; "
        "provider spend is reported when the model provider exposes a meter.",
        "",
        "| arm | measured runs | elapsed | tokens | provider cost | human active | labour cost | rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in arms:
        records = merged.get("costs", {}).get(arm, [])
        elapsed = sum(float(r.get("elapsed_seconds") or 0.0) for r in records)
        active = sum(float(r.get("human_active_seconds") or 0.0) for r in records)
        labour = sum(float(r.get("human_labor_cost_usd") or 0.0) for r in records)
        tokens = sum(int(r.get("total_tokens") or 0) for r in records)
        provider_values = [
            float(r["provider_cost_usd"])
            for r in records
            if r.get("provider_cost_usd") is not None
        ]
        provider_missing = any(
            int(r.get("llm_calls") or 0) > 0 and r.get("provider_cost_usd") is None
            for r in records
        )
        rates = [
            r.get("human_hourly_rate_usd")
            for r in records
            if r.get("human_hourly_rate_usd") is not None
        ]
        rate = rates[-1] if rates else None
        lines.append(
            f"| {arm} | {len(records)} | {elapsed:.1f}s | "
            f"{tokens or '—'} | "
            f"{'$' + format(sum(provider_values), '.4f') if provider_values and not provider_missing else '—'} | "
            f"{active:.1f}s | "
            f"{'$' + format(labour, '.4f') if active else '—'} | "
            f"{'$' + format(float(rate), '.2f') + '/h' if rate is not None else '—'} |",
        )

    if merged.get("persona_exchanges"):
        lines.append("")
        lines.append(
            f"_Environment: {merged['persona_exchanges']} persona exchanges, "
            f"{merged['persona_tokens']} tokens. Not charged to any arm._",
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="colleague.aggregate")
    parser.add_argument("root", type=Path)
    parser.add_argument("--out", type=Path, help="write markdown here")
    parser.add_argument("--json", type=Path, help="write merged json here")
    parser.add_argument(
        "--require-scenarios",
        action="store_true",
        help="fail if no scenario actually executed",
    )
    args = parser.parse_args(argv)

    runs = load(args.root)
    if not runs:
        print(f"no results.json found under {args.root}", file=sys.stderr)
        return 1
    merged = merge(runs)
    markdown = to_markdown(merged)
    if args.out:
        args.out.write_text(markdown)
    if args.json:
        args.json.write_text(json.dumps(merged, indent=2))
    print(markdown)

    # A sweep where every arm failed to install produces well-formed, empty
    # results for every shard. Without this the summary renders as an empty
    # table and the run reports success, which is the one outcome a benchmark
    # must never quietly produce.
    all_outcomes = [
        o
        for scenarios in merged["grid"].values()
        for outcomes in scenarios.values()
        for o in outcomes
    ]
    errors = [o for o in all_outcomes if o == "error"]

    if args.require_scenarios and not all_outcomes:
        print(
            f"no scenarios executed across {merged['runs']} shards — "
            "every arm was unavailable",
            file=sys.stderr,
        )
        return 1

    # An ERROR means the harness could not measure. Letting those through
    # would publish a broken sweep as a poor result for the arm, which reads
    # as a finding rather than as a fault.
    if args.require_scenarios and errors:
        print(
            f"{len(errors)} of {len(all_outcomes)} scenarios errored — "
            "the harness could not measure, so these are not results",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
