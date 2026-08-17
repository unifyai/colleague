"""Silent drift: hermes-agent arm. The protocol is `protocol.py`; the engine is
`colleague/tracks/standing/series/cli_arms.py`. Launch via run_hermes.sh."""

from __future__ import annotations

import sys

from colleague.tracks.standing.series.cli_arms import run
from colleague.tracks.standing.silent_drift.protocol import experiment

if __name__ == "__main__":
    sys.exit(run(experiment(), "hermes"))
