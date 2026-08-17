"""Digest graph for silent_drift: outcome per fire and tokens by purpose per arm.

.venv/bin/python -m colleague.tracks.standing.silent_drift.plot [--variant units|page]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from colleague.tracks.standing.series.plot import render_experiment
from colleague.tracks.standing.silent_drift.fixture import VARIANTS
from colleague.tracks.standing.silent_drift.protocol import DRIFT_AFTER_FIRE

EXPERIMENT_DIR = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=VARIANTS, default=None)
    args = parser.parse_args()
    for variant in [args.variant] if args.variant else VARIANTS:
        render_experiment(
            EXPERIMENT_DIR,
            title=f"Silent drift ({variant})",
            subtitle=(
                "amount switches from minor to major units before fire 5"
                if variant == "units"
                else "the orders page caps at 50 before fire 5, under 'returns every pending order'"
            ),
            variant=variant,
            events={DRIFT_AFTER_FIRE + 1: "drift"},
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
