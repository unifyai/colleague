"""One entrypoint: `python -m colleague.run <track> --arm <arm>`.

The `standing` experiments each ship their own `run_<arm>.sh`, which was
sixteen launchers by the time the fourth arm landed. Every track added since
goes through here instead.

    python -m colleague.run inheritance --arm unify
    python -m colleague.run interruption --arm openclaw --only wrong_recipients
    python -m colleague.run --list
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

from colleague.arms.sessions import ARMS
from colleague.harness.runner import run_track

TRACKS = (
    "inheritance",
    "interruption",
    "continuity",
    "attribution",
    "concurrency",
    "custody",
    "teaching",
    "membership",
    "recall",
    "screenshare",
    "meeting",
)

ROOT = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="colleague.run")
    parser.add_argument("track", nargs="?", choices=TRACKS)
    parser.add_argument("--arm", choices=[*ARMS, "mock"], default="unify")
    parser.add_argument(
        "--mode",
        choices=("ideal", "naive"),
        default="ideal",
        help="mock arm only: `ideal` should PASS every scenario, `naive` should FAIL",
    )
    parser.add_argument("--only", help="run a single scenario by name")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--port", type=int, default=0, help="0 picks a free port")
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help=(
            "run the track this many times; anything a live role-player "
            "touches is a distribution, and repeats are how it is measured"
        ),
    )
    parser.add_argument("--list", action="store_true", help="list tracks and scenarios")
    args = parser.parse_args(argv)

    if args.list or not args.track:
        for track in TRACKS:
            try:
                scenario = importlib.import_module(f"colleague.tracks.{track}.scenario")
                names = [s["name"] for s in scenario.scenarios("http://x")]
            except Exception as exc:  # noqa: BLE001 - listing must never hard fail
                names = [f"<not loadable: {type(exc).__name__}>"]
            print(f"{track}:")
            for n in names:
                print(f"  - {n}")
        return 0

    fixture = importlib.import_module(f"colleague.tracks.{args.track}.fixture")
    scenario = importlib.import_module(f"colleague.tracks.{args.track}.scenario")
    worst = 0
    for _ in range(max(1, args.repeat)):
        worst = max(
            worst,
            run_track(
                track=args.track,
                arm=args.arm,
                fixture_module=fixture,
                scenario_module=scenario,
                results_root=ROOT / "tracks" / args.track / "results",
                seed=args.seed,
                port=args.port,
                timeout_s=args.timeout,
                only=args.only,
                mode=args.mode,
            ),
        )
    return worst


if __name__ == "__main__":
    sys.exit(main())
