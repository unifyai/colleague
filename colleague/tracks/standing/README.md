# Standing work

Eight experiments test work that outlives its originating conversation. See
the experiment README files for their fixtures and exact scorers.

Every experiment now has two human protocols using those same fixtures and
scorers:

```bash
python -m colleague.human standing recurring_report --mode operator
python -m colleague.human standing recurring_report --mode builder
python -m colleague.human standing silent_drift --mode builder \
  --participant-id p001 --hourly-rate-usd 35
```

Operator mode measures manual human performance on every simulated wake.
Builder mode measures a human-authored automation: setup and update labour are
metered, the supplied command is fired unattended, and the person returns only
at protocol-defined intervention points. Both record exact outcomes, elapsed
time and human labour cost; builder fires additionally record unattended
runtime. Full controls and the coverage table are in
[`../../../HUMAN_TESTING.md`](../../../HUMAN_TESTING.md).
