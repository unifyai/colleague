# semantic_triage (prime-agent arm) — 2026-08-18T05-18-14Z-prime-agent

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter

| phase | LLM calls | prompt tok | completion tok | usage-missing | wall (s) |
|---|---|---|---|---|---|
| setup | 3 | 15336 | 648 | 0 | 26.32 |
| fire_1 | 3 | 19358 | 511 | 0 | 14.8 |
| fire_2 | 3 | 21873 | 407 | 0 | 14.42 |
| fire_3 | 3 | 24375 | 420 | 0 | 16.14 |
| fire_4 | 3 | 26903 | 426 | 0 | 13.07 |
| fire_5 | 3 | 29412 | 424 | 0 | 13.58 |
| fire_6 | 3 | 31893 | 420 | 0 | 13.49 |
| fire_7 | 3 | 34382 | 411 | 0 | 16.81 |
| fire_8 | 5 | 54694 | 1499 | 0 | 33.95 |

| fire | mode | delivered | correct | accuracy |
|---|---|---|---|---|
| 1 | wake_prompt | 1 | True | 1.0 |
| 2 | wake_prompt | 1 | True | 1.0 |
| 3 | wake_prompt | 1 | True | 1.0 |
| 4 | wake_prompt | 1 | True | 1.0 |
| 5 | wake_prompt | 1 | True | 1.0 |
| 6 | wake_prompt | 1 | True | 1.0 |
| 7 | wake_prompt | 1 | True | 1.0 |
| 8 | wake_prompt | 1 | True | 1.0 |
