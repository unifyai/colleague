# edge_week-currency (unify arm) — 2026-08-18T21-14-27Z-currency-unify

- orchestra: `https://api.staging.internal.saas.unify.ai/v0`
- edge_week: `5`
- edge: `currency`

| phase | LLM calls | prompt tok | completion tok | planning | verification | repair | wall (s) |
|---|---|---|---|---|---|---|---|
| setup | 82 | 3836333 | 19301 | 3855634 | 0 | 0 | 1050.6 |
| week_1 | 6 | 164202 | 3961 | 168163 | 0 | 0 | 102.84 |
| week_1_review | 10 | 446864 | 11759 | 458623 | 0 | 0 | 456.93 |
| week_2 | 1 | 2165 | 1433 | 0 | 3598 | 0 | 100.77 |
| week_2_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.12 |
| week_3 | 13 | 55734 | 5573 | 31440 | 29867 | 0 | 302.73 |
| week_3_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.15 |
| week_4 | 3 | 12722 | 1549 | 10731 | 3540 | 0 | 96.04 |
| week_4_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.16 |
| week_5 | 9 | 26344 | 2474 | 10420 | 18398 | 0 | 169.79 |
| week_5_review | 2 | 6819 | 1615 | 0 | 8434 | 0 | 186.17 |

| fire | events | outcome | score | edge | reports_delivered | reminders_sent | tokens |
|---|---|---|---|---|---|---|---|
| 1 | - | correct | 2 |  | 1 | 5 | 626786 (p626786/v0/r0) |
| 2 | - | wrong | 0 |  | 0 | 0 | 3598 (p0/v3598/r0) |
| 3 | - | wrong | 0 |  | 0 | 0 | 61307 (p31440/v29867/r0) |
| 4 | - | wrong | 0 |  | 0 | 0 | 14271 (p10731/v3540/r0) |
| 5 | edge:currency | wrong | 0 | currency | 0 | 0 | 37252 (p10420/v26832/r0) |

Series findings:

- regular_weeks_correct: `1`
- regular_weeks: `4`
- edge_week_outcome: `"wrong"`
- tokens_regular_weeks_mean: `176490.5`
- tokens_edge_week: `37252`

Total score: 2 / 10 (1 correct, 0 held, 4 wrong)
