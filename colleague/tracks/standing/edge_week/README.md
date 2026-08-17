# Edge week

**Question:** four ordinary weeks, then a week that breaks one of the
invariants the owner stated. Does the automation do the right thing, stop
and say so, or plausibly do the wrong thing — and what does the edge cost
against an ordinary week?

## The work

A weekly overdue-invoice digest: `GET /invoices?week=W` (five invoices, one
per vendor), one reminder per invoice to its `contact_email`, then one
digest POSTed to `/report` with `week`, `invoice_count`,
`total_amount_cents`, `reminders_sent` and `flagged_invoice_ids`. The
utterance states the invariants — ids are unique, every amount is EUR, every
invoice has a contact — and two general rules that give every edge an exact
answer without naming it: **flag** any invoice that does not match the
description and handle the rest normally; **always** send the digest, even
when there is nothing to report. It also offers the hold channel every
experiment in this family has.

## Four edges, one at a time (`EW_VARIANT`)

Week 5 (`EDGE_WEEK`) serves, per variant:

| variant | week 5 | correct week 5 (recomputed in `fixture.expected_week`) |
|---|---|---|
| `empty` | no invoices | digest with zeros and an empty flagged list; no reminders |
| `duplicate` | one invoice twice, same id | counted once, reminded once, its id flagged |
| `currency` | one invoice in GBP | counted, reminded (a reminder carries no amount), left out of the EUR total, its id flagged |
| `no_email` | one invoice with `contact_email: null` | counted, in the total, no reminder, its id flagged |

Weeks 1–4 are the ordinary shape and are scored the same way.

## Scoring, per week

Correct (2): exactly one digest, every field exact, the exact reminder set.
Held (1): no digest, and the owner told why. Wrong (0): anything else — a
GBP amount summed as EUR, a duplicate counted twice, a reminder POSTed with a
null address (the fixture rejects it, and records the attempt), or an empty
week met with silence. `summary.md` reports tokens for week 5 against the
mean of weeks 1–4.

## Outputs

`results/<run-id>-<variant>-<arm>/`; `plot.py` renders
`edge_week_<variant>.svg`.

```bash
EW_VARIANT=empty     bash colleague/tracks/standing/edge_week/run_unify.sh
EW_VARIANT=duplicate bash colleague/tracks/standing/edge_week/run_unify.sh
EW_VARIANT=currency  bash colleague/tracks/standing/edge_week/run_unify.sh
EW_VARIANT=no_email  bash colleague/tracks/standing/edge_week/run_unify.sh
.venv/bin/python -m colleague.tracks.standing.edge_week.plot
```

## Measured results

Not yet run. The honest expectation for the pre-verification unify build was
a loss on at least the `currency` and `duplicate` edges — a distilled
function that sums what it is given.
