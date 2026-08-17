"""Drift recovery: unify arm. The protocol is `protocol.py`; the engine is
`colleague/tracks/standing/series/unify_arm.py`. Launch via run_unify.sh."""

from __future__ import annotations

import sys

from colleague.tracks.standing.drift_recovery.protocol import experiment
from colleague.tracks.standing.series.unify_arm import main

if __name__ == "__main__":
    sys.exit(main(experiment()))
