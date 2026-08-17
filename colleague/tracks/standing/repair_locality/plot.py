"""Digest graph for repair_locality: outcome per fire and tokens by purpose per arm.

.venv/bin/python -m colleague.tracks.standing.repair_locality.plot
"""

from __future__ import annotations

from pathlib import Path

from colleague.tracks.standing.repair_locality.protocol import DRIFT_AFTER_FIRE
from colleague.tracks.standing.series.plot import render_experiment

EXPERIMENT_DIR = Path(__file__).resolve().parent


def main() -> int:
    render_experiment(
        EXPERIMENT_DIR,
        title="Repair locality",
        subtitle="refunds.amount_cents is renamed before fire 5; orders and tickets never change",
        events={DRIFT_AFTER_FIRE + 1: "drift (refunds)"},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
