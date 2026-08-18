# repair_locality (hermes arm) — 2026-08-18T03-46-14Z-hermes

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter
- drift_after_fire: `4`
- release_per_fire: `{'orders': 24, 'refunds': 9, 'tickets': 15}`
- drift: `refunds.amount_cents -> amount_minor (orders, tickets unchanged)`

| phase | LLM calls | prompt tok | completion tok | planning | verification | repair | wall (s) |
|---|---|---|---|---|---|---|---|
| setup | 10 | 453402 | 5260 | 458662 | 0 | 0 | 1029.11 |
| fire_1 | 0 | 0 | 0 | 0 | 0 | 0 | 0.35 |
| fire_2 | 0 | 0 | 0 | 0 | 0 | 0 | 0.3 |
| fire_3 | 0 | 0 | 0 | 0 | 0 | 0 | 0.34 |
| fire_4 | 0 | 0 | 0 | 0 | 0 | 0 | 0.29 |
| fire_5 | 0 | 0 | 0 | 0 | 0 | 0 | 0.3 |
| fire_6 | 0 | 0 | 0 | 0 | 0 | 0 | 0.29 |
| operator_fix | 12 | 635822 | 3711 | 639533 | 0 | 0 | 111.74 |
| fire_7 | 0 | 0 | 0 | 0 | 0 | 0 | 0.31 |
| fire_8 | 0 | 0 | 0 | 0 | 0 | 0 | 0.32 |
| fire_9 | 0 | 0 | 0 | 0 | 0 | 0 | 0.32 |
| fire_10 | 0 | 0 | 0 | 0 | 0 | 0 | 0.31 |

| fire | events | outcome | score | drifted | reports_delivered | sections_correct | tokens |
|---|---|---|---|---|---|---|---|
| 1 | - | correct | 2 | no | 1 | {"orders":true,"refunds":true,"tickets":true} | 0 (p0/v0/r0) |
| 2 | - | correct | 2 | no | 1 | {"orders":true,"refunds":true,"tickets":true} | 0 (p0/v0/r0) |
| 3 | - | correct | 2 | no | 1 | {"orders":true,"refunds":true,"tickets":true} | 0 (p0/v0/r0) |
| 4 | - | correct | 2 | no | 1 | {"orders":true,"refunds":true,"tickets":true} | 0 (p0/v0/r0) |
| 5 | drift:refunds.amount_cents->amount_minor | held | 1 | yes | 0 | None | 0 (p0/v0/r0) |
| 6 | - | held | 1 | yes | 0 | None | 0 (p0/v0/r0) |
| 7 | - | correct | 2 | yes | 1 | {"orders":true,"refunds":true,"tickets":true} | 0 (p0/v0/r0) |
| 8 | - | correct | 2 | yes | 1 | {"orders":true,"refunds":true,"tickets":true} | 0 (p0/v0/r0) |
| 9 | - | correct | 2 | yes | 1 | {"orders":true,"refunds":true,"tickets":true} | 0 (p0/v0/r0) |
| 10 | - | correct | 2 | yes | 1 | {"orders":true,"refunds":true,"tickets":true} | 0 (p0/v0/r0) |

Series findings:

- recovered: `true`
- first_correct_after_drift: `7`
- post_drift_correct: `4`
- post_drift_fires: `6`
- repair_tokens: `0`
- orders_shape_identical_after_repair: `true`
- tickets_shape_identical_after_repair: `true`

Total score: 18 / 20 (8 correct, 2 held, 0 wrong)
