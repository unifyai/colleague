# semantic_triage (unify-cm arm) — 2026-08-21T21-36-07Z-unify-cm

- items_per_fire: `12`

| phase | LLM calls | prompt tok | completion tok | planning | verification | repair | wall (s) | provider USD | human active (s) | labour USD |
|---|---|---|---|---|---|---|---|---|---|---|
| setup | 31 | 811071 | 6046 | 817117 | 0 | 0 | 327.28 | — | 0 | 0 |
| fire_1 | 31 | 1118735 | 10942 | 1129677 | 0 | 0 | 441.6 | — | 0 | 0 |
| fire_2 | 12 | 191504 | 4586 | 196090 | 0 | 0 | 368.5 | 0.178403 | 0 | 0 |
| fire_3 | 2 | 26757 | 256 | 27013 | 0 | 0 | 212.39 | 0.021878 | 0 | 0 |
| fire_4 | 2 | 27623 | 206 | 27829 | 0 | 0 | 211.94 | 0.0236 | 0 | 0 |
| fire_5 | 2 | 28496 | 251 | 28747 | 0 | 0 | 216.5 | 0.026325 | 0 | 0 |
| fire_6 | 2 | 29361 | 211 | 29572 | 0 | 0 | 211.47 | 0.028013 | 0 | 0 |
| fire_7 | 2 | 30248 | 184 | 30432 | 0 | 0 | 212.01 | 0.0773 | 0 | 0 |
| fire_8 | 2 | 31101 | 201 | 31302 | 0 | 0 | 212.35 | 0.03225 | 0 | 0 |

| fire | events | outcome | score | batches_delivered | accuracy | tokens | cost |
|---|---|---|---|---|---|---|---|
| 1 | - | correct | 2 | 1 | 1.00 | 1129677 (p1129677/v0/r0) | 441.6s |
| 2 | - | correct | 2 | 1 | 1.00 | 196090 (p196090/v0/r0) | $0.178403 provider |
| 3 | - | correct | 2 | 1 | 1.00 | 27013 (p27013/v0/r0) | $0.021878 provider |
| 4 | - | correct | 2 | 1 | 1.00 | 27829 (p27829/v0/r0) | $0.0236 provider |
| 5 | - | correct | 2 | 1 | 1.00 | 28747 (p28747/v0/r0) | $0.026325 provider |
| 6 | - | correct | 2 | 1 | 1.00 | 29572 (p29572/v0/r0) | $0.028013 provider |
| 7 | - | correct | 2 | 1 | 1.00 | 30432 (p30432/v0/r0) | $0.0773 provider |
| 8 | - | correct | 2 | 1 | 1.00 | 31302 (p31302/v0/r0) | $0.03225 provider |

Total score: 16 / 16 (8 correct, 0 held, 0 wrong)
