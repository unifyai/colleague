"""One entrypoint for all human-testable Colleague protocols.

Conversational tracks use ``python -m colleague.run TRACK --arm human``.
This module supplies the recurring automation half:

    python -m colleague.human standing edge_week --mode operator
    python -m colleague.human standing silent_drift --mode builder
"""

from __future__ import annotations

import argparse
import sys

from colleague.tracks.standing.human_legacy import RUNNERS as LEGACY_RUNNERS
from colleague.tracks.usecases.human import RUNNERS as USECASE_RUNNERS

SERIES = {
    "change_without_regression": (
        "colleague.tracks.standing.change_without_regression.protocol",
        "experiment",
    ),
    "drift_recovery": (
        "colleague.tracks.standing.drift_recovery.protocol",
        "experiment",
    ),
    "edge_week": ("colleague.tracks.standing.edge_week.protocol", "experiment"),
    "repair_locality": (
        "colleague.tracks.standing.repair_locality.protocol",
        "experiment",
    ),
    "silent_drift": (
        "colleague.tracks.standing.silent_drift.protocol",
        "experiment",
    ),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="colleague.human")
    sub = parser.add_subparsers(dest="kind", required=True)
    standing = sub.add_parser("standing")
    standing.add_argument("experiment", choices=sorted({*SERIES, *LEGACY_RUNNERS}))
    standing.add_argument("--mode", choices=("operator", "builder"), default="builder")
    standing.add_argument("--hourly-rate-usd", type=float, default=30.0)
    standing.add_argument("--participant-id", default="anonymous")
    usecase = sub.add_parser("usecase")
    usecase.add_argument("name", choices=sorted(USECASE_RUNNERS))
    usecase.add_argument("--mode", choices=("operator", "builder"), default="operator")
    usecase.add_argument("--hourly-rate-usd", type=float, default=30.0)
    usecase.add_argument("--participant-id", default="anonymous")
    args = parser.parse_args(argv)

    if args.kind == "usecase":
        return USECASE_RUNNERS[args.name](
            mode=args.mode,
            hourly_rate_usd=args.hourly_rate_usd,
            participant_id=args.participant_id,
        )

    if args.experiment in LEGACY_RUNNERS:
        return LEGACY_RUNNERS[args.experiment](
            mode=args.mode,
            hourly_rate_usd=args.hourly_rate_usd,
            participant_id=args.participant_id,
        )

    import importlib

    module, factory = SERIES[args.experiment]
    experiment = getattr(importlib.import_module(module), factory)()
    from colleague.tracks.standing.series.human_arm import run

    return run(
        experiment,
        mode=args.mode,
        hourly_rate_usd=args.hourly_rate_usd,
        participant_id=args.participant_id,
    )


if __name__ == "__main__":
    sys.exit(main())
