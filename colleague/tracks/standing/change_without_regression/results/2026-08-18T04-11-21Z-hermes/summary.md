# change_without_regression (hermes arm) — 2026-08-18T04-11-21Z-hermes

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter
- steady_fires: `3`
- orders_per_fire: `40`
- change: `add total_refunded_cents; old columns ['batch_start_seq', 'batch_end_seq', 'order_count', 'total_units', 'total_revenue_cents'] byte-identical`

| phase | LLM calls | prompt tok | completion tok | planning | verification | repair | wall (s) |
|---|---|---|---|---|---|---|---|
| setup | 7 | 296826 | 2785 | 299611 | 0 | 0 | 653.92 |
| fire_1 | 0 | 0 | 0 | 0 | 0 | 0 | 0.55 |
| fire_2 | 0 | 0 | 0 | 0 | 0 | 0 | 0.45 |
| fire_3 | 0 | 0 | 0 | 0 | 0 | 0 | 0.4 |
| message_4 | 7 | 295979 | 1852 | 297831 | 0 | 0 | 69.27 |
| fire_4 | 0 | 0 | 0 | 0 | 0 | 0 | 0.39 |
| fire_5 | 0 | 0 | 0 | 0 | 0 | 0 | 0.34 |
| fire_6 | 0 | 0 | 0 | 0 | 0 | 0 | 0.35 |

| fire | events | outcome | score | changed | batches_delivered | old_columns_identical | new_column_correct | tokens |
|---|---|---|---|---|---|---|---|---|
| 1 | - | correct | 2 | no | 1 | yes | None | 0 (p0/v0/r0) |
| 2 | - | correct | 2 | no | 1 | yes | None | 0 (p0/v0/r0) |
| 3 | - | correct | 2 | no | 1 | yes | None | 0 (p0/v0/r0) |
| 4 | change_requested | correct | 2 | yes | 1 | yes | yes | 297831 (p297831/v0/r0) |
| 5 | - | correct | 2 | yes | 1 | yes | yes | 0 (p0/v0/r0) |
| 6 | - | correct | 2 | yes | 1 | yes | yes | 0 (p0/v0/r0) |

Series findings:

- steady_state_reached: `true`
- new_column_correct_fires: `3`
- old_columns_identical_fires: `3`
- post_change_fires: `3`
- regression_free: `true`

Total score: 12 / 12 (6 correct, 0 held, 0 wrong)
