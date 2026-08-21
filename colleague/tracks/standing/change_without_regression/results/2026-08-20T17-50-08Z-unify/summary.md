# change_without_regression (unify arm) — 2026-08-20T17-50-08Z-unify

- orchestra: `https://api.staging.internal.saas.unify.ai/v0`
- steady_fires: `3`
- orders_per_fire: `40`
- change: `add total_refunded_cents; old columns ['batch_start_seq', 'batch_end_seq', 'order_count', 'total_units', 'total_revenue_cents'] byte-identical`

| phase | LLM calls | prompt tok | completion tok | planning | verification | repair | wall (s) |
|---|---|---|---|---|---|---|---|
| setup | 29 | 1012118 | 7102 | 1019220 | 0 | 0 | 350.64 |
| fire_1 | 7 | 161260 | 4160 | 165420 | 0 | 0 | 67.6 |
| fire_1_review | 18 | 738372 | 12799 | 751171 | 0 | 0 | 396.59 |
| fire_2 | 4 | 13266 | 1876 | 9933 | 5209 | 0 | 46.65 |
| fire_2_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.07 |
| fire_3 | 28 | 150609 | 12401 | 97566 | 65444 | 0 | 297.96 |
| fire_3_review | 0 | 0 | 0 | 0 | 0 | 0 | 48.05 |
| message_4 | 30 | 1229538 | 11047 | 1240585 | 0 | 0 | 444.66 |
| fire_4 | 4 | 18404 | 2551 | 13283 | 7672 | 0 | 53.7 |
| fire_4_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.15 |
| fire_5 | 20 | 94273 | 6737 | 24714 | 76296 | 0 | 168.01 |
| fire_5_review | 0 | 0 | 0 | 0 | 0 | 0 | 164.13 |
| fire_6 | 8 | 45333 | 2618 | 26751 | 21200 | 0 | 99.34 |
| fire_6_review | 0 | 0 | 0 | 0 | 0 | 0 | 162.13 |

| fire | events | outcome | score | changed | batches_delivered | old_columns_identical | new_column_correct | tokens |
|---|---|---|---|---|---|---|---|---|
| 1 | - | correct | 2 | no | 1 | yes | None | 916591 (p916591/v0/r0) |
| 2 | - | wrong | 0 | no | 0 | no | None | 15142 (p9933/v5209/r0) |
| 3 | - | correct | 2 | no | 1 | yes | None | 163010 (p97566/v65444/r0) |
| 4 | change_requested | wrong | 0 | yes | 0 | no | no | 1261540 (p1253868/v7672/r0) |
| 5 | - | correct | 2 | yes | 1 | yes | yes | 101010 (p24714/v76296/r0) |
| 6 | - | correct | 2 | yes | 1 | yes | yes | 47951 (p26751/v21200/r0) |

Series findings:

- steady_state_reached: `false`
- new_column_correct_fires: `2`
- old_columns_identical_fires: `2`
- post_change_fires: `3`
- regression_free: `false`

Total score: 8 / 12 (4 correct, 0 held, 2 wrong)
