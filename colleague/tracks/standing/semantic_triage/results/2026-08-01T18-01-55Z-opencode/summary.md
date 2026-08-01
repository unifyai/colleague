# semantic_triage (opencode arm) — 2026-08-01T18-01-55Z-opencode

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter

| phase | LLM calls | prompt tok | completion tok | usage-missing | wall (s) |
|---|---|---|---|---|---|
| setup | 10 | 121952 | 2774 | 0 | 100.08 |
| fire_1 | 4 | 18392 | 486 | 0 | 14.23 |
| fire_2 | 4 | 18434 | 512 | 0 | 10.38 |
| fire_3 | 4 | 18460 | 492 | 0 | 15.92 |
| fire_4 | 4 | 18421 | 493 | 0 | 10.59 |
| fire_5 | 4 | 18474 | 520 | 0 | 12.77 |
| fire_6 | 4 | 18359 | 485 | 0 | 11.81 |
| fire_7 | 4 | 18383 | 479 | 0 | 10.31 |
| fire_8 | 4 | 18368 | 488 | 0 | 12.78 |

| fire | mode | delivered | correct | accuracy |
|---|---|---|---|---|
| 1 | cron_spec | 1 | True | 1.0 |
| 2 | cron_spec | 1 | True | 1.0 |
| 3 | cron_spec | 1 | True | 1.0 |
| 4 | cron_spec | 1 | True | 1.0 |
| 5 | cron_spec | 1 | True | 1.0 |
| 6 | cron_spec | 1 | True | 1.0 |
| 7 | cron_spec | 1 | True | 1.0 |
| 8 | cron_spec | 1 | True | 1.0 |
