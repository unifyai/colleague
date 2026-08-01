# drift_recovery (openclaw arm) — 2026-07-31T22-47-50Z-openclaw

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter
- drift after fire 4: `unit_price_cents -> unit_price_minor`

| phase | LLM calls | prompt tok | completion tok | usage-missing | wall (s) |
|---|---|---|---|---|---|
| setup | 6 | 93032 | 3685 | 0 | 71.37 |
| fire_1 | 2 | 14830 | 1008 | 0 | 16.59 |
| fire_2 | 4 | 38255 | 2477 | 0 | 31.36 |
| fire_3 | 2 | 14964 | 1174 | 0 | 20.35 |
| fire_4 | 2 | 14939 | 1102 | 0 | 20.23 |
| fire_5 | 2 | 15085 | 1376 | 0 | 20.2 |
| fire_6 | 5 | 43998 | 3364 | 0 | 42.77 |
| fire_7 | 4 | 32436 | 2395 | 0 | 35.3 |
| fire_8 | 4 | 35777 | 2414 | 0 | 31.38 |
| fire_9 | 4 | 40346 | 2273 | 0 | 35.26 |
| fire_10 | 4 | 32572 | 2656 | 0 | 35.27 |

| fire | drifted | delivered | correct | fire status |
|---|---|---|---|---|
| 1 | False | 1 | True | ok |
| 2 | False | 1 | True | ok |
| 3 | False | 1 | True | ok |
| 4 | False | 1 | True | ok |
| 5 | True | 0 | False | ok |
| 6 | True | 1 | True | ok |
| 7 | True | 1 | True | ok |
| 8 | True | 1 | True | ok |
| 9 | True | 1 | True | ok |
| 10 | True | 1 | True | ok |
