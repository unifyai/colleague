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

ORDER = ("pass", "degraded", "fail", "unsupported")
GLYPH = {"pass": "✅", "degraded": "🟡", "fail": "❌", "unsupported": "➖"}


def load(root: Path) -> list[dict[str, Any]]:
    runs = []
    for path in sorted(root.rglob("results.json")):
        try:
            runs.append(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"skipping {path}: {exc}", file=sys.stderr)
    return runs


def merge(runs: list[dict[str, Any]]) -> dict[str, Any]:
    # (track, arm) -> scenario -> [outcomes across repeats]
    grid: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list),
    )
    tracks: set[str] = set()
    arms: set[str] = set()
    for run in runs:
        # The `standing` experiments predate this runner and name the same
        # two things `experiment` and `system`. Accepting both means a sweep
        # can merge old and new results without rewriting the old ones.
        track = run.get("track") or run.get("experiment")
        arm = run.get("arm") or run.get("system")
        if not track or not arm:
            continue
        arm = {"hermes-agent": "hermes"}.get(arm, arm)
        tracks.add(track)
        arms.add(arm)
        for scenario in run.get("scenarios", []):
            outcome = (scenario.get("result") or {}).get("outcome", "fail")
            grid[(track, arm)][scenario["name"]].append(outcome)
    return {
        "tracks": sorted(tracks),
        "arms": sorted(arms),
        "grid": {f"{t}|{a}": dict(v) for (t, a), v in grid.items()},
        "runs": len(runs),
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
        "✅ pass · 🟡 degraded · ❌ fail · ➖ no mechanism (excluded from accuracy)",
        "",
    ]
    for track in merged["tracks"]:
        scenarios: list[str] = []
        for arm in arms:
            scenarios.extend(merged["grid"].get(f"{track}|{arm}", {}).keys())
        seen: list[str] = []
        for s in scenarios:
            if s not in seen:
                seen.append(s)
        if not seen:
            continue
        lines.append(f"### {track}")
        lines.append("")
        lines.append("| scenario | " + " | ".join(arms) + " |")
        lines.append("|---" * (len(arms) + 1) + "|")
        for scenario in seen:
            row = [scenario]
            for arm in arms:
                row.append(
                    _cell(merged["grid"].get(f"{track}|{arm}", {}).get(scenario, []))
                )
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    lines.append("### Credited rate by arm")
    lines.append("")
    lines.append("| arm | credited | scored | unsupported | rate |")
    lines.append("|---|---|---|---|---|")
    for arm in arms:
        credited = scored = unsupported = 0
        for key, scenarios in merged["grid"].items():
            if not key.endswith(f"|{arm}"):
                continue
            for outcomes in scenarios.values():
                for o in outcomes:
                    if o == "unsupported":
                        unsupported += 1
                        continue
                    scored += 1
                    if o in ("pass", "degraded"):
                        credited += 1
        rate = f"{credited / scored:.0%}" if scored else "—"
        lines.append(f"| {arm} | {credited} | {scored} | {unsupported} | {rate} |")
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
    executed = sum(
        len(outcomes)
        for scenarios in merged["grid"].values()
        for outcomes in scenarios.values()
    )
    if args.require_scenarios and executed == 0:
        print(
            f"no scenarios executed across {merged['runs']} shards — "
            "every arm was unavailable",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
