# edge_week-no_email (unify arm) — 2026-08-20T17-50-12Z-no_email-unify

- orchestra: `https://api.staging.internal.saas.unify.ai/v0`
- edge_week: `5`
- edge: `no_email`

| phase | LLM calls | prompt tok | completion tok | planning | verification | repair | wall (s) |
|---|---|---|---|---|---|---|---|
| setup | 30 | 1113825 | 5634 | 1119459 | 0 | 0 | 329.93 |
| week_1 | 7 | 163570 | 3553 | 167123 | 0 | 0 | 56.6 |
| week_1_review | 16 | 550905 | 8752 | 559657 | 0 | 0 | 345.84 |
| week_2 | 4 | 12635 | 2436 | 9822 | 5249 | 0 | 53.04 |
| week_2_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.08 |
| week_3 | 3 | 10951 | 1047 | 9085 | 2913 | 0 | 34.82 |
| week_3_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.12 |
| week_4 | 3 | 10911 | 1659 | 9655 | 2915 | 0 | 40.47 |
| week_4_review | 0 | 0 | 0 | 0 | 0 | 0 | 162.12 |
| week_5 | 18 | 181742 | 11367 | 178791 | 14318 | 0 | 281.36 |
| week_5_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.16 |

| fire | events | outcome | score | edge | reports_delivered | reminders_sent | tokens |
|---|---|---|---|---|---|---|---|
| 1 | - | correct | 2 |  | 1 | 5 | 726780 (p726780/v0/r0) |
| 2 | - | wrong | 0 |  | 0 | 0 | 15071 (p9822/v5249/r0) |
| 3 | - | wrong | 0 |  | 0 | 0 | 11998 (p9085/v2913/r0) |
| 4 | - | wrong | 0 |  | 0 | 0 | 12570 (p9655/v2915/r0) |
| 5 | edge:no_email | wrong | 0 | no_email | 0 | 0 | 193109 (p178791/v14318/r0) |

Series findings:

- regular_weeks_correct: `1`
- regular_weeks: `4`
- edge_week_outcome: `"wrong"`
- tokens_regular_weeks_mean: `191604.8`
- tokens_edge_week: `193109`

Total score: 2 / 10 (1 correct, 0 held, 4 wrong)
