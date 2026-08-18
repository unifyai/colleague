# edge_week-empty (hermes arm) — 2026-08-18T03-38-19Z-empty-hermes

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter
- edge_week: `5`
- edge: `empty`

| phase | LLM calls | prompt tok | completion tok | planning | verification | repair | wall (s) |
|---|---|---|---|---|---|---|---|
| setup | 8 | 347417 | 5320 | 352737 | 0 | 0 | 113.17 |
| week_1 | 0 | 0 | 0 | 0 | 0 | 0 | 0.29 |
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
| 5 | edge:empty | correct | 2 | empty | 1 | 0 | 0 (p0/v0/r0) |

Series findings:

- regular_weeks_correct: `4`
- regular_weeks: `4`
- edge_week_outcome: `"correct"`
- tokens_regular_weeks_mean: `0.0`
- tokens_edge_week: `0`

Total score: 10 / 10 (5 correct, 0 held, 0 wrong)
