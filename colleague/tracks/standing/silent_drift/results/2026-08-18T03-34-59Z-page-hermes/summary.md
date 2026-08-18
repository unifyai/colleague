# silent_drift-page (hermes arm) — 2026-08-18T03-34-59Z-page-hermes

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter
- drift_after_fire: `4`
- orders_per_fire: `80`
- drift: `page cap 100 -> 50 under 'returns every pending order'`

| phase | LLM calls | prompt tok | completion tok | planning | verification | repair | wall (s) |
|---|---|---|---|---|---|---|---|
| setup | 8 | 347033 | 3792 | 350825 | 0 | 0 | 93.75 |
| fire_1 | 0 | 0 | 0 | 0 | 0 | 0 | 0.35 |
| fire_2 | 0 | 0 | 0 | 0 | 0 | 0 | 0.28 |
| fire_3 | 0 | 0 | 0 | 0 | 0 | 0 | 0.29 |
| fire_4 | 0 | 0 | 0 | 0 | 0 | 0 | 0.34 |
| fire_5 | 0 | 0 | 0 | 0 | 0 | 0 | 0.29 |
| fire_6 | 0 | 0 | 0 | 0 | 0 | 0 | 0.29 |
| operator_fix | 16 | 830715 | 2549 | 833264 | 0 | 0 | 102.52 |
| fire_7 | 0 | 0 | 0 | 0 | 0 | 0 | 0.29 |
| fire_8 | 0 | 0 | 0 | 0 | 0 | 0 | 0.3 |
| fire_9 | 0 | 0 | 0 | 0 | 0 | 0 | 0.3 |
| fire_10 | 0 | 0 | 0 | 0 | 0 | 0 | 0.28 |

| fire | events | outcome | score | drifted | batches_delivered | tokens |
|---|---|---|---|---|---|---|
| 1 | - | correct | 2 | no | 1 | 0 (p0/v0/r0) |
| 2 | - | correct | 2 | no | 1 | 0 (p0/v0/r0) |
| 3 | - | correct | 2 | no | 1 | 0 (p0/v0/r0) |
| 4 | - | correct | 2 | no | 1 | 0 (p0/v0/r0) |
| 5 | drift:page | wrong | 0 | yes | 1 | 0 (p0/v0/r0) |
| 6 | - | wrong | 0 | yes | 1 | 0 (p0/v0/r0) |
| 7 | - | wrong | 0 | yes | 1 | 0 (p0/v0/r0) |
| 8 | - | wrong | 0 | yes | 1 | 0 (p0/v0/r0) |
| 9 | - | wrong | 0 | yes | 1 | 0 (p0/v0/r0) |
| 10 | - | wrong | 0 | yes | 1 | 0 (p0/v0/r0) |

Total score: 8 / 20 (4 correct, 0 held, 6 wrong)
