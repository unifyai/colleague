# drift_recovery (prime-agent arm) — 2026-08-18T20-54-01Z-prime-agent

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter
- drift_after_fire: `4`
- orders_per_fire: `37`
- drift: `unit_price_cents -> unit_price_minor`

| phase | LLM calls | prompt tok | completion tok | planning | verification | repair | wall (s) |
|---|---|---|---|---|---|---|---|
| setup | 3 | 15041 | 619 | 15660 | 0 | 0 | 20.55 |
| fire_1 | 3 | 18376 | 576 | 18952 | 0 | 0 | 17.74 |
| fire_2 | 2 | 13547 | 460 | 14007 | 0 | 0 | 13.57 |
| fire_3 | 2 | 14703 | 452 | 15155 | 0 | 0 | 18.06 |
| fire_4 | 2 | 15885 | 478 | 16363 | 0 | 0 | 16.12 |
| fire_5 | 3 | 27595 | 605 | 28200 | 0 | 0 | 20.31 |
| fire_6 | 2 | 21689 | 578 | 22267 | 0 | 0 | 14.98 |
| operator_fix | 6 | 75831 | 1844 | 77675 | 0 | 0 | 54.82 |
| fire_7 | 4 | 50949 | 1328 | 52277 | 0 | 0 | 33.91 |
| fire_8 | 2 | 30576 | 620 | 31196 | 0 | 0 | 16.76 |
| fire_9 | 2 | 32102 | 620 | 32722 | 0 | 0 | 14.45 |
| fire_10 | 2 | 33639 | 631 | 34270 | 0 | 0 | 19.55 |

| fire | events | outcome | score | drifted | batches_delivered | tokens |
|---|---|---|---|---|---|---|
| 1 | - | correct | 2 | no | 1 | 18952 (p18952/v0/r0) |
| 2 | - | correct | 2 | no | 1 | 14007 (p14007/v0/r0) |
| 3 | - | correct | 2 | no | 1 | 15155 (p15155/v0/r0) |
| 4 | - | correct | 2 | no | 1 | 16363 (p16363/v0/r0) |
| 5 | drift:unit_price_cents->unit_price_minor | wrong | 0 | yes | 0 | 28200 (p28200/v0/r0) |
| 6 | - | wrong | 0 | yes | 0 | 22267 (p22267/v0/r0) |
| 7 | - | correct | 2 | yes | 1 | 129952 (p129952/v0/r0) |
| 8 | - | correct | 2 | yes | 1 | 31196 (p31196/v0/r0) |
| 9 | - | correct | 2 | yes | 1 | 32722 (p32722/v0/r0) |
| 10 | - | correct | 2 | yes | 1 | 34270 (p34270/v0/r0) |

Total score: 16 / 20 (8 correct, 0 held, 2 wrong)
