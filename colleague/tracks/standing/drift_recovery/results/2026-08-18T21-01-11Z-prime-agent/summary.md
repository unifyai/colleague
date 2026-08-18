# drift_recovery (prime-agent arm) — 2026-08-18T21-01-11Z-prime-agent

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter
- drift_after_fire: `4`
- orders_per_fire: `37`
- drift: `unit_price_cents -> unit_price_minor`

| phase | LLM calls | prompt tok | completion tok | planning | verification | repair | wall (s) |
|---|---|---|---|---|---|---|---|
| setup | 3 | 16110 | 1295 | 17405 | 0 | 0 | 32.15 |
| fire_1 | 2 | 14930 | 1566 | 16496 | 0 | 0 | 27.76 |
| fire_2 | 2 | 18012 | 1482 | 19494 | 0 | 0 | 23.69 |
| fire_3 | 2 | 20902 | 1310 | 22212 | 0 | 0 | 22.27 |
| fire_4 | 2 | 23762 | 1436 | 25198 | 0 | 0 | 23.22 |
| fire_5 | 2 | 26713 | 1348 | 28061 | 0 | 0 | 24.88 |
| fire_6 | 2 | 29467 | 1351 | 30818 | 0 | 0 | 19.42 |
| operator_fix | 22 | 458642 | 4557 | 463199 | 0 | 0 | 152.35 |
| fire_7 | 2 | 55796 | 1322 | 57118 | 0 | 0 | 21.56 |
| fire_8 | 2 | 58715 | 1433 | 60148 | 0 | 0 | 23.48 |
| fire_9 | 2 | 61656 | 1333 | 62989 | 0 | 0 | 20.58 |
| fire_10 | 2 | 64591 | 1406 | 65997 | 0 | 0 | 21.03 |

| fire | events | outcome | score | drifted | batches_delivered | tokens |
|---|---|---|---|---|---|---|
| 1 | - | correct | 2 | no | 1 | 16496 (p16496/v0/r0) |
| 2 | - | correct | 2 | no | 1 | 19494 (p19494/v0/r0) |
| 3 | - | correct | 2 | no | 1 | 22212 (p22212/v0/r0) |
| 4 | - | correct | 2 | no | 1 | 25198 (p25198/v0/r0) |
| 5 | drift:unit_price_cents->unit_price_minor | held | 1 | yes | 0 | 28061 (p28061/v0/r0) |
| 6 | - | held | 1 | yes | 0 | 30818 (p30818/v0/r0) |
| 7 | - | correct | 2 | yes | 1 | 520317 (p520317/v0/r0) |
| 8 | - | correct | 2 | yes | 1 | 60148 (p60148/v0/r0) |
| 9 | - | correct | 2 | yes | 1 | 62989 (p62989/v0/r0) |
| 10 | - | correct | 2 | yes | 1 | 65997 (p65997/v0/r0) |

Total score: 18 / 20 (8 correct, 2 held, 0 wrong)
