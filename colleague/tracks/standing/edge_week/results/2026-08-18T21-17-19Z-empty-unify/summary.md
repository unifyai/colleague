# edge_week-empty (unify arm) — 2026-08-18T21-17-19Z-empty-unify

- orchestra: `https://api.staging.internal.saas.unify.ai/v0`
- edge_week: `5`
- edge: `empty`

| phase | LLM calls | prompt tok | completion tok | planning | verification | repair | wall (s) |
|---|---|---|---|---|---|---|---|
| setup | 68 | 2838277 | 13770 | 2852047 | 0 | 0 | 826.75 |
| week_1 | 7 | 163958 | 3406 | 167364 | 0 | 0 | 105.59 |
| week_1_review | 15 | 592489 | 8739 | 601228 | 0 | 0 | 451.14 |
| week_2 | 4 | 13949 | 2189 | 9679 | 6459 | 0 | 91.1 |
| week_2_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.15 |
| week_3 | 3 | 11163 | 1006 | 9008 | 3161 | 0 | 69.15 |
| week_3_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.16 |
| week_4 | 3 | 11516 | 968 | 9328 | 3156 | 0 | 68.89 |
| week_4_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.17 |
| week_5 | 3 | 11694 | 1047 | 9577 | 3164 | 0 | 70.38 |
| week_5_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.17 |

| fire | events | outcome | score | edge | reports_delivered | reminders_sent | tokens |
|---|---|---|---|---|---|---|---|
| 1 | - | correct | 2 |  | 1 | 5 | 768592 (p768592/v0/r0) |
| 2 | - | wrong | 0 |  | 0 | 0 | 16138 (p9679/v6459/r0) |
| 3 | - | wrong | 0 |  | 0 | 0 | 12169 (p9008/v3161/r0) |
| 4 | - | wrong | 0 |  | 0 | 0 | 12484 (p9328/v3156/r0) |
| 5 | edge:empty | wrong | 0 | empty | 0 | 0 | 12741 (p9577/v3164/r0) |

Series findings:

- regular_weeks_correct: `1`
- regular_weeks: `4`
- edge_week_outcome: `"wrong"`
- tokens_regular_weeks_mean: `202345.8`
- tokens_edge_week: `12741`

Total score: 2 / 10 (1 correct, 0 held, 4 wrong)
