"""One engine for every fire-series experiment in the `standing` track.

An experiment declares its world (a fixture), what it says once (the
utterance), what changes between fires, what the owner says between fires,
and how a fire is scored. The engine supplies the rest — booting an arm,
firing its automation, metering every phase, and writing the run record —
once per arm rather than once per arm per experiment.
"""
