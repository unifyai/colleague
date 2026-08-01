# drift_recovery (unify arm) — 2026-07-31T11-08-13Z-unify

- orchestra: `https://api.staging.internal.saas.unify.ai/v0`
- drift after fire 4: `unit_price_cents -> unit_price_minor`

| phase | LLM calls | prompt tok | completion tok | cost (USD) | wall (s) |
|---|---|---|---|---|---|
| setup | 11 | 652465 | 2208 | 2.994029 | 269.23 |
| fire_1 | 5 | 247104 | 1533 | 1.082885 | 49.24 |
| fire_1_review | 7 | 549998 | 3696 | 1.039819 | 275.68 |
| fire_2 | 0 | 0 | 0 | 0.0 | 9.04 |
| fire_2_review | 0 | 0 | 0 | 0.0 | 0.0 |
| fire_3 | 0 | 0 | 0 | 0.0 | 9.14 |
| fire_3_review | 0 | 0 | 0 | 0.0 | 0.0 |
| fire_4 | 0 | 0 | 0 | 0.0 | 9.07 |
| fire_4_review | 0 | 0 | 0 | 0.0 | 0.0 |
| fire_5 | 3 | 24772 | 1470 | 0.110772 | 67.49 |
| fire_5_review | 0 | 0 | 0 | 0.0 | 176.08 |
| fire_6 | 7 | 81377 | 5529 | 0.30721 | 120.33 |
| fire_6_review | 0 | 0 | 0 | 0.0 | 176.08 |
| fire_7 | 5 | 249321 | 610 | 0.197575 | 44.03 |
| fire_7_review | 5 | 337156 | 2670 | 0.919404 | 241.21 |
| fire_8 | 5 | 44436 | 4755 | 0.209584 | 105.31 |
| fire_8_review | 0 | 0 | 0 | 0.0 | 176.09 |
| fire_9 | 5 | 249826 | 545 | 0.197303 | 41.77 |
| fire_9_review | 5 | 335983 | 1871 | 0.891622 | 236.81 |
| fire_10 | 7 | 87244 | 5728 | 0.291646 | 114.54 |
| fire_10_review | 0 | 0 | 0 | 0.0 | 178.09 |

| fire | drifted | status | delivered | correct |
|---|---|---|---|---|
| 1 | False | completed | 1 | True |
| 2 | False | completed | 1 | True |
| 3 | False | completed | 1 | True |
| 4 | False | completed | 1 | True |
| 5 | True | error | 0 | False |
| 6 | True | error | 0 | False |
| 7 | True | completed | 0 | False |
| 8 | True | error | 0 | False |
| 9 | True | completed | 0 | False |
| 10 | True | error | 0 | False |
