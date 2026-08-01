# drift_recovery (unify arm) — 2026-07-31T11-54-41Z-unify

- orchestra: `https://api.staging.internal.saas.unify.ai/v0`
- drift after fire 4: `unit_price_cents -> unit_price_minor`

| phase | LLM calls | prompt tok | completion tok | cost (USD) | wall (s) |
|---|---|---|---|---|---|
| setup | 12 | 593345 | 2741 | 2.503941 | 268.31 |
| fire_1 | 5 | 330660 | 1769 | 1.609587 | 47.67 |
| fire_1_review | 7 | 559570 | 3199 | 1.041362 | 252.74 |
| fire_2 | 0 | 0 | 0 | 0.0 | 8.98 |
| fire_2_review | 0 | 0 | 0 | 0.0 | 0.0 |
| fire_3 | 0 | 0 | 0 | 0.0 | 11.26 |
| fire_3_review | 0 | 0 | 0 | 0.0 | 0.0 |
| fire_4 | 0 | 0 | 0 | 0.0 | 9.26 |
| fire_4_review | 0 | 0 | 0 | 0.0 | 0.0 |
| fire_5 | 4 | 36831 | 3600 | 0.190634 | 84.94 |
| fire_5_review | 0 | 0 | 0 | 0.0 | 176.07 |
| fire_6 | 4 | 42078 | 4160 | 0.200943 | 97.13 |
| fire_6_review | 0 | 0 | 0 | 0.0 | 176.08 |
| fire_7 | 4 | 49085 | 5288 | 0.261247 | 118.1 |
| fire_7_review | 0 | 0 | 0 | 0.0 | 176.07 |
| fire_8 | 2 | 18858 | 4558 | 0.188361 | 96.25 |
| fire_8_review | 0 | 0 | 0 | 0.0 | 176.08 |
| fire_9 | 5 | 71253 | 11576 | 0.470978 | 223.95 |
| fire_9_review | 0 | 0 | 0 | 0.0 | 176.1 |
| fire_10 | 0 | 0 | 0 | 0.0 | 9.16 |
| fire_10_review | 0 | 0 | 0 | 0.0 | 0.0 |

| fire | drifted | status | delivered | correct |
|---|---|---|---|---|
| 1 | False | completed | 1 | True |
| 2 | False | completed | 1 | True |
| 3 | False | completed | 1 | True |
| 4 | False | completed | 1 | True |
| 5 | True | error | 0 | False |
| 6 | True | error | 0 | False |
| 7 | True | error | 0 | False |
| 8 | True | error | 0 | False |
| 9 | True | completed | 1 | True |
| 10 | True | completed | 1 | True |
