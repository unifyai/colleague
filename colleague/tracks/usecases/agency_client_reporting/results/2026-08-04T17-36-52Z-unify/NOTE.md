# The run behind the page's figures — cost column reconstructed

This is the run the landing page's `results` array is transcribed from.
Behaviour and wall-clock come straight from `results.json`. **The cost column
in `summary.md` reads zero and is wrong**: the in-process LLM ledger recorded
nothing this run. The real costs below are reconstructed from Orchestra's
credit transactions, which are the billing system of record.

## What was measured

| | |
|---|---|
| month reported | `2026-07` (matches the anchor — window aligned) |
| flags | **9 of 9**, 0 false positives, 0 missed, in both months |
| reports | 13 drafted, 1 blocked |
| the blocked one | `c07`, expired Meta connection, refused rather than written from Google Ads alone |
| one cycle, wall-clock | **619s ≈ 10.3 min** for all 14 clients (`run_1`) |

`run_1` ran description-driven (`entrypoint` was `None` after setup) and
`run_2` executed the stored entrypoint. Both scored 9/9, so the distillation
preserved detection exactly.

## Reconstructed cost

Phase windows are the `wall_seconds` in `results.json` laid end to end from
setup's start (17:37:12Z, from the run log), matched against `category=llm`
credit transactions.

| phase | window (UTC) | calls | cost |
|---|---|---|---|
| setup | 17:37:12–18:22:24 | 69 | $24.0031 |
| run_1 (description) | 18:22:24–18:32:43 | 20 | $3.3217 |
| run_1_review | 18:32:43–18:35:44 | 6 | $2.5302 |
| run_2 (entrypoint) | 18:35:44–18:48:10 | 12 | $0.2916 |
| run_2_review | 18:48:10–18:51:10 | 1 | $0.0300 |
| **total** | | **108** | **$30.1765** |

The total is independently confirmed: the account balance moved from $93.90
to $63.74 across this run, a delta of $30.17.

Per client report: **$0.2555** first month ($3.3217 / 13), **$0.0224** once
settled onto the stored entrypoint ($0.2916 / 13) — an 11× drop.

## The ledger defect

`LLMLedger` is installed after `unify.init()` precisely so unify's own
process-global unillm hook does not overwrite it, and it worked in earlier
runs on this track (58 records, then 42+10). This run it captured zero while
108 calls were billed, so the hook was lost or never fired. Cause not yet
found; it is intermittent rather than a straight ordering bug.

Until it is fixed, treat a zero-cost phase table as a missing measurement
rather than a cheap run, and reconstruct from
`GET /v0/credits/transactions?category=llm` (capped at `limit=200`, so page
it). Cross-check the reconstruction against the balance delta, as above.

## Also worth knowing

Setup posted 14 deliveries of its own before the metered months began — the
brief asks for a schedule and never forbids running one immediately, so that
is a fair reading of it. Those are scored separately in
`results.json.setup.dry_run_score` and excluded from every figure here.

That dry run also scored 9/9 with 13 drafted and 1 blocked. So detection was
confirmed three independent times in this run — once ad hoc during setup, once
description-driven, once through the stored function — and a fourth time
offline, by executing the stored function against the fixture with the
narrative call stubbed, which costs nothing and is the cheapest way to
re-check this page before paying for a run.
