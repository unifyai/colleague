# agency-client-reporting (unify arm) — 2026-08-05T15-53-55Z-unify

- orchestra: `https://api.staging.internal.saas.unify.ai/v0`
- context: `colleague/usecases/agency_client_reporting/2026-08-05T15-53-55Z-unify/default/0`
- UNILLM_CACHE: `false`
- fixture booted on `2026-07` (the month before now) · seed `20260801`
- task activates `2026-09-01T09:00:00Z`, which reports `2026-08`; each run is re-anchored to the pair its own regime compares

| phase | LLM calls | prompt tok | completion tok | cost (USD) | wall (s) |
|---|---|---|---|---|---|
| setup | 0 | 0 | 0 | 0.0 | 2472.23 |
| run_1 | 0 | 0 | 0 | 0.0 | 1361.16 |
| run_1_review | 0 | 0 | 0 | 0.0 | 180.1 |
| run_2 | 0 | 0 | 0 | 0.0 | 2759.27 |
| run_2_review | 0 | 0 | 0 | 0.0 | 180.08 |

> **The cost column is void for `setup`, `run_1`, `run_1_review`, `run_2`, `run_2_review`.** Those phases did real work and the ledger metered no calls, so their cost is missing, not zero. Reconstruct from `GET /v0/credits/transactions?category=llm` and cross-check against the account balance delta before any cost figure is quoted.

| run | regime | month | status | delivered | drafted | blocked | flags matched | extra | missed |
|---|---|---|---|---|---|---|---|---|---|
| 1 | entrypoint | `2026-07` | completed | 14/14 | 12 | 2 | 9/11 | 0 | 2 |
| 2 | entrypoint | `2026-07` | completed | 14/14 | 9 | 5 | 7/11 | 0 | 4 |

Run 1 — client `c07` (expired Meta connection): status `blocked`, reason: Could not draft the 2026-07 report for Atlas Legal Partners: HTTPError: HTTP Error 401: Unauthorized

Run 2 — client `c07` (expired Meta connection): status `blocked`, reason: Could not draft the 2026-07 report for Atlas Legal Partners: HTTPError: HTTP Error 401: Unauthorized

## Landing-page transcription

Brief sha256 `d0458d9d30b8c693` · seed `20260801` · month `2026-07`

| page figure | value | where it comes from |
|---|---|---|
| cost of one client's report | **not measured** | the ledger recorded 0 calls for this phase, so its cost is missing rather than zero — reconstruct from billing before any cost figure goes on the page |
| one reporting cycle | 23 min | run_1 wall time, all 14 clients |
| flagged campaigns | 9 | matched of 11 planted, 0 extra, 2 missed |

Not page-eligible:

- setup (one-off, utterance → task): $0.0000
- run_1 post-run review tail (once per cycle, not per report): $0.0000
- run_2 (converged regime, cheaper than any first month): $0.0000, entrypoint 0 → 0
