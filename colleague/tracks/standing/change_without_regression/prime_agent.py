"""Change without regression: prime-agent arm. The protocol is `protocol.py`; the engine is
`colleague/tracks/standing/series/cli_arms.py`. Launch via run_prime_agent.sh."""

from __future__ import annotations

import sys

from colleague.tracks.standing.change_without_regression.protocol import experiment
from colleague.tracks.standing.series.cli_arms import run

if __name__ == "__main__":
    sys.exit(run(experiment(), "prime-agent"))
