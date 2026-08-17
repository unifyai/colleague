"""Digest graph for edge_week: outcome per week and tokens by purpose per arm.

.venv/bin/python -m colleague.tracks.standing.edge_week.plot [--variant empty|duplicate|currency|no_email]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from colleague.tracks.standing.edge_week.fixture import EDGE_WEEK, VARIANTS
from colleague.tracks.standing.series.plot import render_experiment

EXPERIMENT_DIR = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=VARIANTS, default=None)
    args = parser.parse_args()
    for variant in [args.variant] if args.variant else VARIANTS:
        render_experiment(
            EXPERIMENT_DIR,
            title=f"Edge week ({variant})",
            subtitle=f"four ordinary weeks, then week {EDGE_WEEK}: {variant}",
            variant=variant,
            events={EDGE_WEEK: "edge"},
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
