# edge_week-duplicate (unify arm) — 2026-08-20T11-28-04Z-duplicate-unify

- orchestra: `https://api.staging.internal.saas.unify.ai/v0`
- edge_week: `5`
- edge: `duplicate`

| phase | LLM calls | prompt tok | completion tok | planning | verification | repair | wall (s) |
|---|---|---|---|---|---|---|---|
| setup | 21 | 663624 | 5410 | 669034 | 0 | 0 | 324.54 |
| week_1 | 8 | 248511 | 4506 | 253017 | 0 | 0 | 71.87 |
| week_1_review | 21 | 850038 | 12100 | 862138 | 0 | 0 | 448.03 |
| week_2 | 4 | 14192 | 1879 | 10253 | 5818 | 0 | 68.36 |
| week_2_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.09 |
| week_3 | 3 | 12053 | 1620 | 10324 | 3349 | 0 | 44.09 |
| week_3_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.09 |
| week_4 | 3 | 11988 | 983 | 9621 | 3350 | 0 | 41.09 |
| week_4_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.09 |
| week_5 | 3 | 12584 | 1520 | 10749 | 3355 | 0 | 41.92 |
| week_5_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.09 |

| fire | events | outcome | score | edge | reports_delivered | reminders_sent | tokens |
|---|---|---|---|---|---|---|---|
| 1 | - | correct | 2 |  | 1 | 5 | 1115155 (p1115155/v0/r0) |
| 2 | - | wrong | 0 |  | 0 | 0 | 16071 (p10253/v5818/r0) |
| 3 | - | wrong | 0 |  | 0 | 0 | 13673 (p10324/v3349/r0) |
| 4 | - | wrong | 0 |  | 0 | 0 | 12971 (p9621/v3350/r0) |
| 5 | edge:duplicate | wrong | 0 | duplicate | 0 | 0 | 14104 (p10749/v3355/r0) |

Series findings:

- regular_weeks_correct: `1`
- regular_weeks: `4`
- edge_week_outcome: `"wrong"`
- tokens_regular_weeks_mean: `289467.5`
- tokens_edge_week: `14104`

Total score: 2 / 10 (1 correct, 0 held, 4 wrong)
