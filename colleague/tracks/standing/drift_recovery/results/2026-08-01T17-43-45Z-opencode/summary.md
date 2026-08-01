# drift_recovery (opencode arm) — 2026-08-01T17-43-45Z-opencode

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter
- drift after fire 4: `unit_price_cents -> unit_price_minor`

| phase | LLM calls | prompt tok | completion tok | usage-missing | wall (s) |
|---|---|---|---|---|---|
| setup | 13 | 143766 | 3364 | 0 | 68.35 |
| fire_1 | 0 | 0 | 0 | 0 | 0.07 |
| fire_2 | 0 | 0 | 0 | 0 | 0.06 |
| fire_3 | 0 | 0 | 0 | 0 | 0.06 |
| fire_4 | 0 | 0 | 0 | 0 | 0.06 |
| fire_5 | 0 | 0 | 0 | 0 | 0.07 |
| fire_6 | 0 | 0 | 0 | 0 | 0.07 |
| operator_fix | 15 | 152119 | 3342 | 0 | 56.71 |
| fire_7 | 0 | 0 | 0 | 0 | 0.05 |
| fire_8 | 0 | 0 | 0 | 0 | 0.05 |
| fire_9 | 0 | 0 | 0 | 0 | 0.05 |
| fire_10 | 0 | 0 | 0 | 0 | 0.05 |

| fire | drifted | mode | delivered | correct |
|---|---|---|---|---|
| 1 | False | script:process_orders.py | 1 | True |
| 2 | False | script:process_orders.py | 1 | True |
| 3 | False | script:process_orders.py | 1 | True |
| 4 | False | script:process_orders.py | 1 | True |
| 5 | True | script:process_orders.py | 0 | False |
| 6 | True | script:process_orders.py | 0 | False |
| 7 | True | script:process_orders.py | 1 | True |
| 8 | True | script:process_orders.py | 1 | True |
| 9 | True | script:process_orders.py | 1 | True |
| 10 | True | script:process_orders.py | 1 | True |
