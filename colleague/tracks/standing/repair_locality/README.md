# Repair locality

**Question:** one report, three independent inputs, one of them drifts. Does
the arm recover, what does the repair cost, and does the repair stay where
the break was?

## The work

An hourly operations report from three seq-keyed streams — orders, refunds,
tickets — each with its own cursor in the last report (`GET /reports/last`).
Every run reads all three and POSTs one JSON object with an `orders`, a
`refunds` and a `tickets` section. Before fire 5 the refunds API renames
`amount_cents` to `amount_minor`; the other two streams never change.

## Protocol

10 fires; 24 orders, 9 refunds and 15 tickets released before each. Unify
arm unattended; CLI arms get the operator once after 2 consecutive
non-correct fires, as in `drift_recovery`.

## Scoring

Per fire, the shared rubric (correct 2 / held 1 / wrong 0), with each
section also scored on its own so `results.json` says which one broke.
Then, over the series (`summarize`):

- **recovery** — first correct fire after the drift, and how many of fires
  5–10 were correct;
- **repair cost** — the `repair` token bucket summed over the run for the
  unify arm; the `operator_fix` phase for arms fixed by a person;
- **locality** — whether the `orders` and `tickets` sections of every
  post-drift report have exactly the shape they had in the last pre-drift
  one: the same keys, in the same order, holding the same value types. A
  repair that rewrote the whole automation and "tidied" an untouched
  section on the way shows up here even when the tidied numbers are right.

The unify driver also records which stored functions changed around each
fire (`functions_changed`). That is evidence for the run record — it lets a
reader see whether the repair touched one leaf or the root — and is never a
score, since the benchmark asks what the report's consumer sees, not how the
arm is built.

## Outputs

`results/<run-id>-<arm>/`; `plot.py` renders `repair_locality.svg`.

```bash
bash colleague/tracks/standing/repair_locality/run_unify.sh
bash colleague/tracks/standing/repair_locality/run_hermes.sh      # also run_openclaw.sh, run_opencode.sh
.venv/bin/python -m colleague.tracks.standing.repair_locality.plot
```

## Measured results

Not yet run.
