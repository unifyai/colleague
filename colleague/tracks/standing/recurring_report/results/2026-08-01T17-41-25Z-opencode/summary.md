# recurring_weekly_report (opencode arm) — 2026-08-01T17-41-25Z-opencode

- model: `openai/gpt-5.6-sol` via local recording proxy -> OpenRouter
- opencode repo: `/Users/djl11/opencode`

| phase | LLM calls | prompt tok | completion tok | usage-missing | wall (s) |
|---|---|---|---|---|---|
| setup | 10 | 78805 | 3914 | 0 | 69.41 |
| run_1 | 0 | 0 | 0 | 0 | 0.07 |
| run_2 | 0 | 0 | 0 | 0 | 0.06 |
| run_3 | 0 | 0 | 0 | 0 | 0.06 |
| run_4 | 0 | 0 | 0 | 0 | 0.07 |

| run | fire mode | reports | correct |
|---|---|---|---|
| 1 | script:weekly_orders_report.py | 1 | True |
| 2 | script:weekly_orders_report.py | 1 | True |
| 3 | script:weekly_orders_report.py | 1 | True |
| 4 | script:weekly_orders_report.py | 1 | True |
