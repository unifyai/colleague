"""One entrypoint for the standing fire-series experiments, person-shaped.

    python -m colleague.tracks.standing.run semantic_triage --arm unify-cm
    python -m colleague.tracks.standing.run silent_drift --arm hermes-tui --variant units
    python -m colleague.tracks.standing.run --list

Every experiment runs through the person engine
(`colleague.tracks.standing.series.person`): the brief is delivered in
English through the arm's conversation surface, the system decides how the
work recurs, and the harness plays only the clock. The per-experiment
`run_<arm>.sh` launchers of the old installed-and-fired regime are gone;
environment preparation for the unify-cm arm (staging Orchestra, key,
UNILLM_CACHE=false) is the same as for any conversational-track run.

Experiment knobs keep their historical env prefixes (`ST_SEED`,
`RWR_RUNS`, `DR_QUIESCE_IDLE_S`, ...).
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from colleague.tracks.standing.series.person import PERSON_ARMS, run_series
from colleague.tracks.standing.series.spec import Experiment


def _drift_recovery(_variant: str | None) -> Experiment:
    from colleague.tracks.standing.drift_recovery.protocol import experiment

    return experiment()


def _silent_drift(variant: str | None) -> Experiment:
    from colleague.tracks.standing.silent_drift.protocol import SilentDrift

    return SilentDrift(variant) if variant else SilentDrift()


def _edge_week(variant: str | None) -> Experiment:
    from colleague.tracks.standing.edge_week.protocol import EdgeWeek

    return EdgeWeek(variant) if variant else EdgeWeek()


def _repair_locality(_variant: str | None) -> Experiment:
    from colleague.tracks.standing.repair_locality.protocol import experiment

    return experiment()


def _change_without_regression(_variant: str | None) -> Experiment:
    from colleague.tracks.standing.change_without_regression.protocol import (
        experiment,
    )

    return experiment()


def _semantic_triage(_variant: str | None) -> Experiment:
    from colleague.tracks.standing.semantic_triage.protocol import experiment

    return experiment()


def _policy_propagation(_variant: str | None) -> Experiment:
    from colleague.tracks.standing.policy_propagation.protocol import experiment

    return experiment()


def _recurring_report(_variant: str | None) -> Experiment:
    from colleague.tracks.standing.recurring_report.protocol import experiment

    return experiment()


EXPERIMENTS: dict[str, Callable[[str | None], Experiment]] = {
    "recurring_report": _recurring_report,
    "semantic_triage": _semantic_triage,
    "policy_propagation": _policy_propagation,
    "drift_recovery": _drift_recovery,
    "silent_drift": _silent_drift,
    "edge_week": _edge_week,
    "repair_locality": _repair_locality,
    "change_without_regression": _change_without_regression,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="colleague.tracks.standing.run")
    parser.add_argument("experiment", nargs="?", choices=sorted(EXPERIMENTS))
    parser.add_argument("--arm", choices=PERSON_ARMS, default="unify-cm")
    parser.add_argument(
        "--variant",
        default=None,
        help="experiment variant (silent_drift: units|page; edge_week: "
        "empty|duplicate|currency|no_email)",
    )
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)

    if args.list or not args.experiment:
        for name in EXPERIMENTS:
            print(name)
        return 0

    experiment = EXPERIMENTS[args.experiment](args.variant)
    return run_series(experiment, args.arm)


if __name__ == "__main__":
    sys.exit(main())
