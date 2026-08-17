"""Edge week: OpenClaw arm. The protocol is `protocol.py`; the engine is
`colleague/tracks/standing/series/cli_arms.py`. Launch via run_openclaw.sh."""

from __future__ import annotations

import sys

from colleague.tracks.standing.edge_week.protocol import experiment
from colleague.tracks.standing.series.cli_arms import run

if __name__ == "__main__":
    sys.exit(run(experiment(), "openclaw"))
