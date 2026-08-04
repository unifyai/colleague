# agency-client-reporting (unify arm) — 2026-08-04T17-36-52Z-unify

- orchestra: `https://api.staging.internal.saas.unify.ai/v0`
- context: `colleague/usecases/agency_client_reporting/2026-08-04T17-36-52Z-unify/default/0`
- UNILLM_CACHE: `false`
- month reported: `2026-07` · seed `20260801`

| phase | LLM calls | prompt tok | completion tok | cost (USD) | wall (s) |
|---|---|---|---|---|---|
| setup | 0 | 0 | 0 | 0.0 | 2712.04 |
| run_1 | 0 | 0 | 0 | 0.0 | 619.16 |
| run_1_review | 0 | 0 | 0 | 0.0 | 181.33 |
| run_2 | 0 | 0 | 0 | 0.0 | 745.57 |
| run_2_review | 0 | 0 | 0 | 0.0 | 180.15 |

| run | status | delivered | drafted | blocked | flags matched | extra | missed |
|---|---|---|---|---|---|---|---|
| 1 | completed | 14/14 | 13 | 1 | 9/9 | 0 | 0 |
| 2 | completed | 14/14 | 13 | 1 | 9/9 | 0 | 0 |

Run 1 — client `c07` (expired Meta connection): status `blocked`, reason: The report could not be drafted because meta_ads for 2026-07 failed: The Meta Ads connection for this client has expired; a member of the team needs to reconnect the account.

Run 2 — client `c07` (expired Meta connection): status `blocked`, reason: The report could not be drafted because meta_ads for 2026-07 failed: The Meta Ads connection for this client has expired; a member of the team needs to reconnect the account.

## Landing-page transcription

Brief sha256 `d0458d9d30b8c693` · seed `20260801` · month `2026-07`

| page figure | value | where it comes from |
|---|---|---|
| cost of one client's report | $0.0000 | run_1 (description regime) provider cost $0.0000 / 13 reports drafted |
| one reporting cycle | 10 min | run_1 wall time, all 14 clients |
| flagged campaigns | 9 | matched of 9 planted, 0 extra, 0 missed |

Not page-eligible:

- setup (one-off, utterance → task): $0.0000
- run_1 post-run review tail (once per cycle, not per report): $0.0000
- run_2 (converged regime, cheaper than any first month): $0.0000, entrypoint 0 → 0
