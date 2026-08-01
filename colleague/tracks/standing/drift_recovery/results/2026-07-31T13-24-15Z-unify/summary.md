# drift_recovery (unify arm) — 2026-07-31T13-24-15Z-unify

- orchestra: `https://api.staging.internal.saas.unify.ai/v0`
- drift after fire 4: `unit_price_cents -> unit_price_minor`

| phase | LLM calls | prompt tok | completion tok | cost (USD) | wall (s) |
|---|---|---|---|---|---|
| setup | 11 | 651201 | 2119 | 2.987817 | 259.59 |
| fire_1 | 5 | 248858 | 2415 | 1.118415 | 53.46 |
| fire_1_review | 7 | 567636 | 4395 | 1.091366 | 271.24 |
| fire_2 | 0 | 0 | 0 | 0.0 | 9.68 |
| fire_2_review | 0 | 0 | 0 | 0.0 | 0.0 |
| fire_3 | 0 | 0 | 0 | 0.0 | 9.52 |
| fire_3_review | 0 | 0 | 0 | 0.0 | 0.0 |
| fire_4 | 0 | 0 | 0 | 0.0 | 9.7 |
| fire_4_review | 0 | 0 | 0 | 0.0 | 0.0 |
| fire_5 | 3 | 28535 | 3392 | 0.182659 | 82.12 |
| fire_5_review | 0 | 0 | 0 | 0.0 | 176.1 |
| fire_6 | 0 | 0 | 0 | 0.0 | 10.5 |
| fire_6_review | 0 | 0 | 0 | 0.0 | 0.0 |
| fire_7 | 0 | 0 | 0 | 0.0 | 11.71 |
| fire_7_review | 0 | 0 | 0 | 0.0 | 0.0 |
| fire_8 | 0 | 0 | 0 | 0.0 | 9.37 |
| fire_8_review | 0 | 0 | 0 | 0.0 | 0.0 |
| fire_9 | 0 | 0 | 0 | 0.0 | 10.21 |
| fire_9_review | 0 | 0 | 0 | 0.0 | 0.0 |
| fire_10 | 0 | 0 | 0 | 0.0 | 9.35 |
| fire_10_review | 0 | 0 | 0 | 0.0 | 0.0 |

| fire | drifted | status | delivered | correct |
|---|---|---|---|---|
| 1 | False | completed | 1 | True |
| 2 | False | completed | 1 | True |
| 3 | False | completed | 1 | True |
| 4 | False | completed | 1 | True |
| 5 | True | completed | 1 | True |
| 6 | True | completed | 1 | True |
| 7 | True | completed | 1 | True |
| 8 | True | completed | 1 | True |
| 9 | True | completed | 1 | True |
| 10 | True | completed | 1 | True |
