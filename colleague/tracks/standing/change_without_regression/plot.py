"""Digest graph for change_without_regression: outcome per fire and tokens by purpose per arm.

.venv/bin/python -m colleague.tracks.standing.change_without_regression.plot
"""

from __future__ import annotations

from pathlib import Path

from colleague.tracks.standing.change_without_regression.protocol import STEADY_FIRES
from colleague.tracks.standing.series.plot import render_experiment

EXPERIMENT_DIR = Path(__file__).resolve().parent


def main() -> int:
    render_experiment(
        EXPERIMENT_DIR,
        title="Change without regression",
        subtitle="after three correct fires the owner asks for one more column; every old column must not move",
        events={STEADY_FIRES + 1: "change requested"},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
