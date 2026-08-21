# repair_locality (unify arm) — 2026-08-20T17-50-07Z-unify

- orchestra: `https://api.staging.internal.saas.unify.ai/v0`
- drift_after_fire: `4`
- release_per_fire: `{'orders': 24, 'refunds': 9, 'tickets': 15}`
- drift: `refunds.amount_cents -> amount_minor (orders, tickets unchanged)`

| phase | LLM calls | prompt tok | completion tok | planning | verification | repair | wall (s) |
|---|---|---|---|---|---|---|---|
| setup | 37 | 1704777 | 15375 | 1720152 | 0 | 0 | 498.95 |
| fire_1 | 13 | 74559 | 5870 | 63730 | 16699 | 0 | 133.7 |
| fire_1_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.09 |
| fire_2 | 4 | 19815 | 3192 | 13046 | 9961 | 0 | 69.3 |
| fire_2_review | 0 | 0 | 0 | 0 | 0 | 0 | 178.08 |
| fire_3 | 3 | 13651 | 938 | 10657 | 3932 | 0 | 24.1 |
| fire_3_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.14 |
| fire_4 | 3 | 13533 | 2064 | 11660 | 3937 | 0 | 31.66 |
| fire_4_review | 0 | 0 | 0 | 0 | 0 | 0 | 86.06 |
| fire_5 | 4 | 17505 | 1262 | 10639 | 8128 | 0 | 39.75 |
| fire_5_review | 0 | 0 | 0 | 0 | 0 | 0 | 178.15 |
| fire_6 | 4 | 18791 | 1610 | 12111 | 8290 | 0 | 37.31 |
| fire_6_review | 0 | 0 | 0 | 0 | 0 | 0 | 178.15 |
| fire_7 | 3 | 15505 | 1026 | 12599 | 3932 | 0 | 27.37 |
| fire_7_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.15 |
| fire_8 | 3 | 14904 | 1367 | 12341 | 3930 | 0 | 31.49 |
| fire_8_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.13 |
| fire_9 | 3 | 20705 | 1461 | 18238 | 3928 | 0 | 32.06 |
| fire_9_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.15 |
| fire_10 | 3 | 18601 | 853 | 15525 | 3929 | 0 | 33.18 |
| fire_10_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.14 |

| fire | events | outcome | score | drifted | reports_delivered | sections_correct | tokens |
|---|---|---|---|---|---|---|---|
| 1 | - | wrong | 0 | no | 0 | None | 80429 (p63730/v16699/r0) |
| 2 | - | correct | 2 | no | 1 | {"orders":true,"refunds":true,"tickets":true} | 23007 (p13046/v9961/r0) |
| 3 | - | wrong | 0 | no | 0 | None | 14589 (p10657/v3932/r0) |
| 4 | - | wrong | 0 | no | 0 | None | 15597 (p11660/v3937/r0) |
| 5 | drift:refunds.amount_cents->amount_minor | held | 1 | yes | 0 | None | 18767 (p10639/v8128/r0) |
| 6 | - | held | 1 | yes | 0 | None | 20401 (p12111/v8290/r0) |
| 7 | - | wrong | 0 | yes | 0 | None | 16531 (p12599/v3932/r0) |
| 8 | - | wrong | 0 | yes | 0 | None | 16271 (p12341/v3930/r0) |
| 9 | - | wrong | 0 | yes | 0 | None | 22166 (p18238/v3928/r0) |
| 10 | - | wrong | 0 | yes | 0 | None | 19454 (p15525/v3929/r0) |

Series findings:

- recovered: `false`
- first_correct_after_drift: `null`
- post_drift_correct: `0`
- post_drift_fires: `6`
- repair_tokens: `0`
- operator_fix_tokens: `0`

Total score: 4 / 20 (1 correct, 2 held, 7 wrong)
