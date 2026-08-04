# Measurement artifact — the flag count is invalid

This run compared the wrong two months, so `flags matched 4/9` measures
nothing about detection. Cost, wall-clock, the refusal and the convergence
result stand.

## What happened

The harness fired the task on **2026-08-04**, but the task the system created
schedules its first activation for **2026-09-01T09:00:00Z**. The system
computed the report window from that activation rather than from the wall
clock — in its own words, *"activation is 2026-09-01T09:00:00Z, so the
immediately preceding [month]"* — and reported **2026-08 against 2026-07**.

That reading is correct for a run firing on 1 September. The fixture was the
thing out of step: its plants were pinned to the month before *now*
(2026-07, compared against 2026-06), which is not in the pair the system
compared. Nine planted anomalies sat outside the window.

The four campaigns that were flagged are planted ones, but they tripped for a
reversed reason: a 2026-07 anomaly read as the *prior* month of an 08-vs-07
comparison still moves cost per conversion more than 40%. Reported as a
detection rate it would be meaningless in both directions — the misses were
invisible and the hits were accidents.

## What remains valid

- **Cost and wall-clock.** The work performed was the full mechanical shape
  the page describes: 14 clients, two platforms plus analytics, two months
  each, 13 drafted reports and one refusal. Which two months were fetched does
  not change that. `run_1` = $3.23 / 683.6s.
- **The refusal.** Client `c07`'s expired Meta connection blocked its report
  instead of writing the month from Google Ads alone.
- **Convergence, and that the distilled artifact is *not* infected.** A stored
  entrypoint was attached after the first run, and its month logic reads
  `report_month = shift_month(-1)` off `datetime.now(timezone.utc)` — correct
  on any date. The first run's window error did not propagate into the
  function the run distilled.

## Fix

`FixtureServer.set_anchor()` plus `_activation_anchor()` in `unify.py`: after
setup, the harness reads the task's own scheduled activation, re-anchors the
fixture to the month that activation reports, and re-derives ground truth
before the metered run. The fixture follows the task, since the task's reading
of its own activation is the correct one.
