# No figure is eligible from this run — the misses are timeouts

This cycle completed and scored 9/11 then 7/11, and **neither number is a
detection result**. Every missed flag belongs to a client whose report was
blocked by `litellm.Timeout` on the narrative call, so the campaigns were never
written up rather than never noticed.

| run | regime | drafted | blocked | flags | why the misses |
|---|---|---|---|---|---|
| 1 | entrypoint | 12 | 2 | 9/11 | `c04` timed out (its 2 flags), `c07` expected 401 |
| 2 | entrypoint | 9 | 5 | 7/11 | `c08 c09 c11 c12` timed out (4 flags), `c07` expected 401 |

Twenty `litellm.Timeout`s in the run log. Zero false positives in either month:
nothing was over-flagged, and every client that got written up got written up
correctly.

Quoting 9 of 11 would blame the product's judgement for a provider timeout —
the mirror image of the defect this fixture's fourth plant shape exists to
catch, where the system's own arithmetic error was filed as bad platform data.

## Nor is the wall-clock usable

`run_1` reads 1361s (23 min) against a 12-minute reference, because it executed
the full fourteen-client pass **twice**. The log shows a second task run
starting inside the phase after:

    Failed to materialize live task run before execution started (task_id=0)

A scheduled task re-executing itself mid-phase is a defect in its own right and
worth chasing separately from this measurement. The page keeps the 10-minute
figure from `2026-08-04T17-36-52Z`, which was a single clean pass.

## Cost, reconstructed

The ledger metered zero calls for every phase again. From
`GET /v0/credits/transactions?category=llm`: **$38.96 across 170 calls** from
this run's start. That total also contains the ecommerce attempt that aborted
around 15:56Z — the two ran concurrently, so per-run attribution is not
recoverable from timestamps. Do not run two cycles at once while the in-process
ledger is unreliable; it is the only thing that could have separated them.

Auto-topup fired mid-run (balance rose from $8.32 to $14.87 while phases were
still executing), so a balance reading during a run is not a spend measurement.

## What this run does establish

- **Detection logic is not implicated.** No over-flagging in 28 client-months,
  and every completed report was correct.
- **The window fix works.** Both months reported `2026-07`, matching where the
  plants are, with the fixture re-anchored per regime.
- **The environment was degraded throughout.** Earlier cycles today died on
  whitespace response bodies; this one survived setup and hit timeouts instead.
  Runs attempted while that persists will keep producing contaminated numbers.
