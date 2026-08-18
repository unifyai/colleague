# edge_week-no_email (hermes arm) — 2026-08-18T03-44-28Z-no_email-hermes

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter
- edge_week: `5`
- edge: `no_email`

| phase | LLM calls | prompt tok | completion tok | planning | verification | repair | wall (s) |
|---|---|---|---|---|---|---|---|
| setup | 7 | 299960 | 3916 | 303876 | 0 | 0 | 103.82 |
| week_1 | 0 | 0 | 0 | 0 | 0 | 0 | 0.4 |
| week_2 | 0 | 0 | 0 | 0 | 0 | 0 | 0.29 |
| week_3 | 0 | 0 | 0 | 0 | 0 | 0 | 0.29 |
| week_4 | 0 | 0 | 0 | 0 | 0 | 0 | 0.29 |
| week_5 | 0 | 0 | 0 | 0 | 0 | 0 | 0.29 |

| fire | events | outcome | score | edge | reports_delivered | reminders_sent | tokens |
|---|---|---|---|---|---|---|---|
| 1 | - | correct | 2 |  | 1 | 5 | 0 (p0/v0/r0) |
| 2 | - | correct | 2 |  | 1 | 5 | 0 (p0/v0/r0) |
| 3 | - | correct | 2 |  | 1 | 5 | 0 (p0/v0/r0) |
| 4 | - | correct | 2 |  | 1 | 5 | 0 (p0/v0/r0) |
| 5 | edge:no_email | held | 1 | no_email | 0 | 0 | 0 (p0/v0/r0) |

Series findings:

- regular_weeks_correct: `4`
- regular_weeks: `4`
- edge_week_outcome: `"held"`
- tokens_regular_weeks_mean: `0.0`
- tokens_edge_week: `0`

Total score: 9 / 10 (4 correct, 1 held, 0 wrong)
