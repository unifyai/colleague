# drift_recovery (opencode arm) — 2026-08-01T18-15-11Z-opencode

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter
- drift after fire 4: `unit_price_cents -> unit_price_minor`

| phase | LLM calls | prompt tok | completion tok | usage-missing | wall (s) |
|---|---|---|---|---|---|
| setup | 9 | 62668 | 2631 | 0 | 49.18 |
| fire_1 | 0 | 0 | 0 | 0 | 0.05 |
| fire_2 | 0 | 0 | 0 | 0 | 0.05 |
| fire_3 | 0 | 0 | 0 | 0 | 0.05 |
| fire_4 | 0 | 0 | 0 | 0 | 0.05 |
| fire_5 | 0 | 0 | 0 | 0 | 0.06 |
| fire_6 | 0 | 0 | 0 | 0 | 0.06 |
| operator_fix | 14 | 220540 | 4405 | 0 | 73.99 |
| fire_7 | 0 | 0 | 0 | 0 | 0.06 |
| fire_8 | 0 | 0 | 0 | 0 | 0.05 |
| fire_9 | 0 | 0 | 0 | 0 | 0.05 |
| fire_10 | 0 | 0 | 0 | 0 | 0.05 |

| fire | drifted | mode | delivered | correct |
|---|---|---|---|---|
| 1 | False | cron_spec | 1 | True |
| 2 | False | cron_spec | 1 | True |
| 3 | False | cron_spec | 1 | True |
| 4 | False | cron_spec | 1 | True |
| 5 | True | cron_spec | 0 | False |
| 6 | True | cron_spec | 0 | False |
| 7 | True | cron_spec | 1 | True |
| 8 | True | cron_spec | 1 | True |
| 9 | True | cron_spec | 1 | True |
| 10 | True | cron_spec | 1 | True |
