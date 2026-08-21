# silent_drift-units (unify arm) — 2026-08-20T17-50-11Z-units-unify

- orchestra: `https://api.staging.internal.saas.unify.ai/v0`
- drift_after_fire: `4`
- orders_per_fire: `80`
- drift: `amount: minor units (int) -> major units (float)`

| phase | LLM calls | prompt tok | completion tok | planning | verification | repair | wall (s) |
|---|---|---|---|---|---|---|---|
| setup | 22 | 849959 | 6558 | 856517 | 0 | 0 | 337.2 |
| fire_1 | 7 | 201996 | 5566 | 207562 | 0 | 0 | 83.5 |
| fire_1_review | 15 | 754850 | 15242 | 770092 | 0 | 0 | 422.93 |
| fire_2 | 4 | 15723 | 2893 | 12343 | 6273 | 0 | 64.29 |
| fire_2_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.08 |
| fire_3 | 3 | 14404 | 2021 | 13021 | 3404 | 0 | 47.43 |
| fire_3_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.14 |
| fire_4 | 3 | 13467 | 1480 | 11533 | 3414 | 0 | 41.96 |
| fire_4_review | 0 | 0 | 0 | 0 | 0 | 0 | 26.02 |
| fire_5 | 20 | 137015 | 8551 | 130559 | 15007 | 0 | 231.78 |
| fire_5_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.16 |
| fire_6 | 14 | 82202 | 2935 | 74365 | 10772 | 0 | 129.92 |
| fire_6_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.14 |
| fire_7 | 14 | 83657 | 3458 | 76330 | 10785 | 0 | 140.36 |
| fire_7_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.15 |
| fire_8 | 13 | 72965 | 2966 | 65191 | 10740 | 0 | 130.3 |
| fire_8_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.15 |
| fire_9 | 3 | 11859 | 1036 | 9296 | 3599 | 0 | 38.81 |
| fire_9_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.16 |
| fire_10 | 3 | 11836 | 1154 | 9392 | 3598 | 0 | 38.82 |
| fire_10_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.14 |

| fire | events | outcome | score | drifted | batches_delivered | tokens |
|---|---|---|---|---|---|---|
| 1 | - | correct | 2 | no | 1 | 977654 (p977654/v0/r0) |
| 2 | - | wrong | 0 | no | 0 | 18616 (p12343/v6273/r0) |
| 3 | - | wrong | 0 | no | 0 | 16425 (p13021/v3404/r0) |
| 4 | - | wrong | 0 | no | 0 | 14947 (p11533/v3414/r0) |
| 5 | drift:units | wrong | 0 | yes | 0 | 145566 (p130559/v15007/r0) |
| 6 | - | wrong | 0 | yes | 0 | 85137 (p74365/v10772/r0) |
| 7 | - | wrong | 0 | yes | 0 | 87115 (p76330/v10785/r0) |
| 8 | - | wrong | 0 | yes | 0 | 75931 (p65191/v10740/r0) |
| 9 | - | wrong | 0 | yes | 0 | 12895 (p9296/v3599/r0) |
| 10 | - | wrong | 0 | yes | 0 | 12990 (p9392/v3598/r0) |

Total score: 2 / 20 (1 correct, 0 held, 9 wrong)
