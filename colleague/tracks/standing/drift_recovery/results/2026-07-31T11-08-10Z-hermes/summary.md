# drift_recovery (hermes-agent arm) — 2026-07-31T11-08-10Z-hermes

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter
- drift after fire 4: `unit_price_cents -> unit_price_minor`

| phase | LLM calls | prompt tok | completion tok | usage-missing | wall (s) |
|---|---|---|---|---|---|
| setup | 16 | 667959 | 4082 | 0 | 133.87 |
| fire_1 | 0 | 0 | 0 | 0 | 0.34 |
| fire_2 | 0 | 0 | 0 | 0 | 0.34 |
| fire_3 | 0 | 0 | 0 | 0 | 0.29 |
| fire_4 | 0 | 0 | 0 | 0 | 0.29 |
| fire_5 | 0 | 0 | 0 | 0 | 0.29 |
| fire_6 | 0 | 0 | 0 | 0 | 0.3 |
| operator_fix | 17 | 739746 | 3406 | 0 | 113.09 |
| fire_7 | 0 | 0 | 0 | 0 | 0.35 |
| fire_8 | 0 | 0 | 0 | 0 | 0.29 |
| fire_9 | 0 | 0 | 0 | 0 | 0.29 |
| fire_10 | 0 | 0 | 0 | 0 | 0.29 |

| fire | drifted | delivered | correct | job status |
|---|---|---|---|---|
| 1 | False | 1 | True | ok |
| 2 | False | 1 | True | ok |
| 3 | False | 1 | True | ok |
| 4 | False | 1 | True | ok |
| 5 | True | 0 | False | error |
| 6 | True | 0 | False | error |
| 7 | True | 1 | True | ok |
| 8 | True | 1 | True | ok |
| 9 | True | 1 | True | ok |
| 10 | True | 1 | True | ok |
