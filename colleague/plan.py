"""Expand a benchmark request into independently-runnable shards.

A shard is one matrix job. The finest safe unit is a single scenario against
a single arm, but not every track can be split that way: `continuity`,
`custody` and `teaching` hold one session across their scenarios, so their
scenarios are one unit or the measurement is destroyed. That constraint lives
here rather than in the workflow, because it is a property of the track and
the workflow should not have to know about it.

    python -m colleague.plan --tracks all --arms unify,openclaw --repeat 3

Emits JSON on stdout, suitable for a GitHub Actions matrix.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from typing import Any

from colleague.arms.sessions import ARMS, AUTOMATED_ARMS
from colleague.run import TRACKS

#: The `standing` experiments predate this runner and keep their own launchers.
STANDING = (
    "recurring_report",
    "drift_recovery",
    "semantic_triage",
    "policy_propagation",
)


def track_shards(track: str) -> list[dict[str, Any]]:
    """One entry per independently-runnable unit within a track."""
    scenario = importlib.import_module(f"colleague.tracks.{track}.scenario")
    scope = getattr(scenario, "SESSION_SCOPE", "scenario")
    names = [s["name"] for s in scenario.scenarios("http://x")]
    if scope == "track":
        # Splitting these would run each scenario in a fresh session, which
        # is precisely the thing they exist to detect the absence of.
        return [{"track": track, "only": "", "scenarios": len(names), "scope": scope}]
    return [
        {"track": track, "only": name, "scenarios": 1, "scope": scope} for name in names
    ]


def build(
    *,
    tracks: list[str],
    arms: list[str],
    repeat: int = 1,
    shard_scenarios: bool = True,
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for track in tracks:
        shards = (
            track_shards(track)
            if shard_scenarios
            else [{"track": track, "only": "", "scenarios": 0, "scope": "track"}]
        )
        for shard in shards:
            for arm in arms:
                for rep in range(1, repeat + 1):
                    label = shard["only"] or "all"
                    jobs.append(
                        {
                            **shard,
                            "arm": arm,
                            "repeat": rep,
                            "name": f"{track}/{label}/{arm}"
                            + (f"#{rep}" if repeat > 1 else ""),
                            "artifact": f"{track}--{label}--{arm}--{rep}",
                        },
                    )
    return jobs


def _resolve(value: str, all_values: tuple[str, ...]) -> list[str]:
    if value.strip().lower() in {"all", "*", ""}:
        return list(all_values)
    out = [v.strip() for v in value.split(",") if v.strip()]
    unknown = [v for v in out if v not in all_values]
    if unknown:
        raise SystemExit(
            f"unknown: {', '.join(unknown)}. known: {', '.join(all_values)}",
        )
    return out


def _resolve_arms(value: str) -> list[str]:
    """Cloud ``all`` means unattended arms; humans must be explicit."""
    if value.strip().lower() in {"all", "*", ""}:
        return list(AUTOMATED_ARMS)
    return _resolve(value, ARMS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="colleague.plan")
    parser.add_argument("--tracks", default="all")
    parser.add_argument("--arms", default="unify")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument(
        "--no-shard",
        action="store_true",
        help="one job per track instead of one per scenario",
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    jobs = build(
        tracks=_resolve(args.tracks, TRACKS),
        arms=_resolve_arms(args.arms),
        repeat=args.repeat,
        shard_scenarios=not args.no_shard,
    )
    if args.pretty:
        for job in jobs:
            print(f"{job['name']:52s} scenarios={job['scenarios']}")
        print(f"\n{len(jobs)} jobs", file=sys.stderr)
        return 0
    print(json.dumps({"include": jobs}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
