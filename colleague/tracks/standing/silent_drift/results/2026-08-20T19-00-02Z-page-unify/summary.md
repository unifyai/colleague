# silent_drift-page (unify arm) — 2026-08-20T19-00-02Z-page-unify

- orchestra: `https://api.staging.internal.saas.unify.ai/v0`
- drift_after_fire: `4`
- orders_per_fire: `80`
- drift: `page cap 100 -> 50 under 'returns every pending order'`

| phase | LLM calls | prompt tok | completion tok | planning | verification | repair | wall (s) | provider USD | human active (s) | labour USD |
|---|---|---|---|---|---|---|---|---|---|---|
| setup | 34 | 1251059 | 7277 | 1258336 | 0 | 0 | 368.19 | — | 0 | 0 |
| fire_1 | 7 | 168044 | 4159 | 172203 | 0 | 0 | 64.89 | — | 0 | 0 |
| fire_1_review | 4 | 110886 | 237 | 111123 | 0 | 0 | 18.01 | — | 0 | 0 |
| fire_2 | 12 | 293801 | 5584 | 299385 | 0 | 0 | 57.77 | — | 0 | 0 |
| fire_2_review | 23 | 1201977 | 18212 | 1220189 | 0 | 0 | 342.32 | — | 0 | 0 |
| fire_3 | 15 | 57887 | 5071 | 21378 | 41580 | 0 | 136.97 | 0.231969 | 0 | 0 |
| fire_3_review | 0 | 0 | 0 | 0 | 0 | 0 | 164.16 | 0.0 | 0 | 0 |
| fire_4 | 11 | 49483 | 3596 | 20255 | 32824 | 0 | 115.37 | 0.156705 | 0 | 0 |
| fire_4_review | 0 | 0 | 0 | 0 | 0 | 0 | 158.08 | 0.0 | 0 | 0 |
| fire_5 | 3 | 10594 | 1108 | 9229 | 2473 | 0 | 35.77 | 0.026273 | 0 | 0 |
| fire_5_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.09 | 0.0 | 0 | 0 |
| fire_6 | 11 | 50458 | 3812 | 21296 | 32974 | 0 | 120.77 | 0.162989 | 0 | 0 |
| fire_6_review | 0 | 0 | 0 | 0 | 0 | 0 | 162.08 | 0.0 | 0 | 0 |
| fire_7 | 11 | 48621 | 3409 | 19368 | 32662 | 0 | 107.36 | 0.151203 | 0 | 0 |
| fire_7_review | 0 | 0 | 0 | 0 | 0 | 0 | 164.11 | 0.0 | 0 | 0 |
| fire_8 | 3 | 12570 | 1282 | 11376 | 2476 | 0 | 38.33 | 0.035058 | 0 | 0 |
| fire_8_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.16 | 0.0 | 0 | 0 |
| fire_9 | 11 | 49598 | 4286 | 20460 | 33424 | 0 | 118.36 | 0.167402 | 0 | 0 |
| fire_9_review | 0 | 0 | 0 | 0 | 0 | 0 | 164.13 | 0.0 | 0 | 0 |
| fire_10 | 3 | 10543 | 1375 | 9440 | 2478 | 0 | 37.44 | 0.030118 | 0 | 0 |
| fire_10_review | 0 | 0 | 0 | 0 | 0 | 0 | 180.15 | 0.0 | 0 | 0 |

| fire | events | outcome | score | drifted | batches_delivered | tokens | cost |
|---|---|---|---|---|---|---|---|
| 1 | - | correct | 2 | no | 1 | 283326 (p283326/v0/r0) | 82.9s |
| 2 | - | correct | 2 | no | 1 | 1519574 (p1519574/v0/r0) | 400.09s |
| 3 | - | correct | 2 | no | 1 | 62958 (p21378/v41580/r0) | $0.231969 provider |
| 4 | - | correct | 2 | no | 1 | 53079 (p20255/v32824/r0) | $0.156705 provider |
| 5 | drift:page | wrong | 0 | yes | 0 | 11702 (p9229/v2473/r0) | $0.026273 provider |
| 6 | - | wrong | 0 | yes | 1 | 54270 (p21296/v32974/r0) | $0.162989 provider |
| 7 | - | wrong | 0 | yes | 1 | 52030 (p19368/v32662/r0) | $0.151203 provider |
| 8 | - | wrong | 0 | yes | 0 | 13852 (p11376/v2476/r0) | $0.035058 provider |
| 9 | - | wrong | 0 | yes | 1 | 53884 (p20460/v33424/r0) | $0.167402 provider |
| 10 | - | wrong | 0 | yes | 0 | 11918 (p9440/v2478/r0) | $0.030118 provider |

Total score: 8 / 20 (4 correct, 0 held, 6 wrong)
