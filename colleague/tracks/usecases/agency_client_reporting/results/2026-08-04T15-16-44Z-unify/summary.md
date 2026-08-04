# agency-client-reporting (unify arm) — 2026-08-04T15-16-44Z-unify

- orchestra: `https://api.staging.internal.saas.unify.ai/v0`
- context: `colleague/usecases/agency_client_reporting/2026-08-04T15-16-44Z-unify/default/0`
- UNILLM_CACHE: `false`
- month reported: `2026-07` · seed `20260801`

| phase | LLM calls | prompt tok | completion tok | cost (USD) | wall (s) |
|---|---|---|---|---|---|
| setup | 35 | 3170700 | 12964 | 6.335959 | 686.21 |
| run_1 | 14 | 1416255 | 28511 | 3.229801 | 683.61 |
| run_1_review | 9 | 1256100 | 11207 | 2.031836 | 404.84 |

| run | status | delivered | drafted | blocked | flags matched | extra | missed |
|---|---|---|---|---|---|---|---|
| 1 | completed | 14/14 | 13 | 1 | 4/9 | 0 | 5 |

Run 1 — client `c07` (expired Meta connection): status `blocked`, reason: required source retrieval or report generation failed: RuntimeError: GET /clients/c07/meta_ads?month=2026-08 returned HTTP 401: {"error": "AUTH_EXPIRED", "message": "The Meta Ads connection for this client has expired; a member of the team needs to reconnect the account"}.

## Landing-page transcription

Brief sha256 `d0458d9d30b8c693` · seed `20260801` · month `2026-07`

| page figure | value | where it comes from |
|---|---|---|
| cost of one client's report | $0.248 | run_1 provider cost $3.23 / 13 reports drafted |
| one reporting cycle | 11 min | run_1 wall time, all 14 clients |
| flagged campaigns | 4 | matched of 9 planted, 0 extra, 5 missed |

Not page-eligible:

- setup (one-off, utterance → task): $6.34
- run_1 post-run review tail (once per cycle, not per report): $2.03
