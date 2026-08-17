"""Silent drift: unify arm. The protocol is `protocol.py`; the engine is
`colleague/tracks/standing/series/unify_arm.py`. Launch via run_unify.sh."""

from __future__ import annotations

import sys

from colleague.tracks.standing.series.unify_arm import main
from colleague.tracks.standing.silent_drift.protocol import experiment

if __name__ == "__main__":
    sys.exit(main(experiment()))
