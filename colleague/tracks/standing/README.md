# Standing work

Eight experiments test work that outlives its originating conversation. See
the experiment README files for their fixtures and exact scorers.

Every experiment runs person-shaped, through one engine
(`series/person.py`): the brief is delivered in English through the arm's
conversation surface, whether and how the work comes to recur is the
system's own choice (recorded, never enforced), and the harness plays only
the clock — firing whatever the system itself scheduled, through the
product's own machinery, then observing the fixture's sink.

```bash
python -m colleague.tracks.standing.run semantic_triage --arm unify-cm
python -m colleague.tracks.standing.run silent_drift --variant units --arm hermes-tui
python -m colleague.tracks.standing.run --list
```

Results committed before 2026-08-21 are old-regime (installed-and-fired)
and labelled so in each experiment README; they are not comparable with
person-shaped runs.

Every experiment has one direct human protocol using those same fixtures and
scorers:

```bash
python -m colleague.human standing recurring_report
python -m colleague.human standing silent_drift \
  --participant-id p001 --hourly-rate-usd 35
```

The participant performs every simulated occurrence directly. Notes, task
history and familiarity persist between occurrences, allowing normal human
learning to affect later work. The protocol records exact outcomes, elapsed
time and human labour cost for initial read-in, updates and every occurrence.
It never asks the participant to write code or technical instructions. Full
controls and the coverage table are in
[`../../../HUMAN_TESTING.md`](../../../HUMAN_TESTING.md).

## The persona boundary

The owner's clarification answers now come from an owner persona under the
same information bound the old scripted constant enforced: his brief and
his own delivered messages are everything he knows, he never adds
information, and asked anything he points back and says go ahead (label
`repointed`; the scripted fallback is the old constant, unchanged, and is
what deterministic runs use). Persona spend lands in its own
`persona_ledger.jsonl` and is reported as `persona_tokens` /
`persona_exchanges`, never in the arm's columns.
