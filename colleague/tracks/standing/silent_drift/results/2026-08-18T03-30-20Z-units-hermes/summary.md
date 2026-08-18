# silent_drift-units (hermes arm) — 2026-08-18T03-30-20Z-units-hermes

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter
- drift_after_fire: `4`
- orders_per_fire: `80`
- drift: `amount: minor units (int) -> major units (float)`

| phase | LLM calls | prompt tok | completion tok | planning | verification | repair | wall (s) |
|---|---|---|---|---|---|---|---|
| setup | 7 | 299021 | 2858 | 301879 | 0 | 0 | 95.49 |
| fire_1 | 0 | 0 | 0 | 0 | 0 | 0 | 0.31 |
| fire_2 | 0 | 0 | 0 | 0 | 0 | 0 | 0.26 |
| fire_3 | 0 | 0 | 0 | 0 | 0 | 0 | 0.25 |
| fire_4 | 0 | 0 | 0 | 0 | 0 | 0 | 0.26 |
| fire_5 | 0 | 0 | 0 | 0 | 0 | 0 | 0.27 |
| fire_6 | 0 | 0 | 0 | 0 | 0 | 0 | 0.31 |
| operator_fix | 14 | 933300 | 6293 | 939593 | 0 | 0 | 179.38 |
| fire_7 | 0 | 0 | 0 | 0 | 0 | 0 | 0.4 |
| fire_8 | 0 | 0 | 0 | 0 | 0 | 0 | 0.34 |
| fire_9 | 0 | 0 | 0 | 0 | 0 | 0 | 0.29 |
| fire_10 | 0 | 0 | 0 | 0 | 0 | 0 | 0.29 |

| fire | events | outcome | score | drifted | batches_delivered | tokens |
|---|---|---|---|---|---|---|
| 1 | - | correct | 2 | no | 1 | 0 (p0/v0/r0) |
| 2 | - | correct | 2 | no | 1 | 0 (p0/v0/r0) |
| 3 | - | correct | 2 | no | 1 | 0 (p0/v0/r0) |
| 4 | - | correct | 2 | no | 1 | 0 (p0/v0/r0) |
| 5 | drift:units | held | 1 | yes | 0 | 0 (p0/v0/r0) |
| 6 | - | held | 1 | yes | 0 | 0 (p0/v0/r0) |
| 7 | - | correct | 2 | yes | 1 | 0 (p0/v0/r0) |
| 8 | - | correct | 2 | yes | 1 | 0 (p0/v0/r0) |
| 9 | - | correct | 2 | yes | 1 | 0 (p0/v0/r0) |
| 10 | - | correct | 2 | yes | 1 | 0 (p0/v0/r0) |

Total score: 18 / 20 (8 correct, 2 held, 0 wrong)
