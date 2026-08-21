# Standing work

Eight experiments test work that outlives its originating conversation. See
the experiment README files for their fixtures and exact scorers.

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
