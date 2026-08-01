# semantic_triage (opencode arm) — 2026-08-01T17-58-45Z-opencode

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter

| phase | LLM calls | prompt tok | completion tok | usage-missing | wall (s) |
|---|---|---|---|---|---|
| setup | 9 | 111558 | 3434 | 0 | 67.35 |
| fire_1 | 4 | 8213 | 539 | 0 | 12.38 |
| fire_2 | 4 | 8219 | 560 | 0 | 13.3 |
| fire_3 | 4 | 8333 | 634 | 0 | 12.12 |
| fire_4 | 4 | 8196 | 539 | 0 | 16.0 |
| fire_5 | 4 | 8234 | 538 | 0 | 12.72 |
| fire_6 | 4 | 8246 | 555 | 0 | 14.84 |
| fire_7 | 4 | 8181 | 519 | 0 | 23.33 |
| fire_8 | 4 | 8223 | 617 | 0 | 16.82 |

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
