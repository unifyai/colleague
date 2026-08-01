# policy_propagation (unify arm) — 2026-07-31T18-14-10Z-unify

| phase | LLM calls | prompt tok | completion tok | cost (USD) | wall (s) |
|---|---|---|---|---|---|
| setup_triage | 12 | 737548 | 2510 | 2.114696 | 265.83 |
| setup_digests | 12 | 731238 | 2899 | 2.133244 | 288.75 |
| setup_audits | 12 | 730937 | 2233 | 2.112234 | 254.09 |
| fire_round1_triage | 6 | 249785 | 3137 | 1.14479 | 68.13 |
| fire_round1_triage_review | 7 | 570669 | 4500 | 1.100937 | 281.96 |
| fire_round1_digests | 7 | 347863 | 3414 | 1.223487 | 76.29 |
| fire_round1_digests_review | 7 | 611831 | 4743 | 1.181772 | 290.25 |
| fire_round1_audits | 6 | 261558 | 3058 | 1.182486 | 60.28 |
| fire_round1_audits_review | 7 | 628273 | 4704 | 1.210707 | 278.38 |
| fire_round2_triage | 1 | 629 | 134 | 0.007165 | 11.68 |
| fire_round2_triage_review | 0 | 0 | 0 | 0.0 | 180.09 |
| fire_round2_digests | 1 | 608 | 134 | 0.00706 | 10.71 |
| fire_round2_digests_review | 0 | 0 | 0 | 0.0 | 180.09 |
| fire_round2_audits | 1 | 588 | 429 | 0.01581 | 11.59 |
| fire_round2_audits_review | 0 | 0 | 0 | 0.0 | 180.09 |
| policy_change | 31 | 2620521 | 13303 | 10.131996 | 429.47 |
| fire_round3_triage | 1 | 636 | 134 | 0.0072 | 12.46 |
| fire_round3_triage_review | 0 | 0 | 0 | 0.0 | 180.09 |
| fire_round3_digests | 1 | 615 | 134 | 0.007095 | 19.39 |
| fire_round3_digests_review | 0 | 0 | 0 | 0.0 | 180.1 |
| fire_round3_audits | 1 | 595 | 308 | 0.012215 | 10.5 |
| fire_round3_audits_review | 0 | 0 | 0 | 0.0 | 180.1 |
| fire_round4_triage | 1 | 637 | 134 | 0.007205 | 11.0 |
| fire_round4_triage_review | 0 | 0 | 0 | 0.0 | 180.1 |
| fire_round4_digests | 1 | 616 | 134 | 0.0071 | 10.67 |
| fire_round4_digests_review | 0 | 0 | 0 | 0.0 | 180.09 |
| fire_round4_audits | 1 | 596 | 314 | 0.0124 | 10.98 |
| fire_round4_audits_review | 0 | 0 | 0 | 0.0 | 180.09 |
| fire_round5_triage | 1 | 638 | 134 | 0.00721 | 11.59 |
| fire_round5_triage_review | 0 | 0 | 0 | 0.0 | 180.09 |
| fire_round5_digests | 1 | 617 | 134 | 0.007105 | 13.81 |
| fire_round5_digests_review | 0 | 0 | 0 | 0.0 | 180.09 |
| fire_round5_audits | 1 | 597 | 322 | 0.012645 | 9.95 |
| fire_round5_audits_review | 0 | 0 | 0 | 0.0 | 180.09 |

| round | automation | threshold | delivered | contract | accuracy |
|---|---|---|---|---|---|
| 1 | triage | $500 | 1 | True | 1.0 |
| 1 | digests | $500 | 1 | True | 1.0 |
| 1 | audits | $500 | 1 | True | 1.0 |
| 2 | triage | $500 | 1 | True | 1.0 |
| 2 | digests | $500 | 1 | True | 1.0 |
| 2 | audits | $500 | 1 | True | 1.0 |
| 3 | triage | $250 | 1 | True | 1.0 |
| 3 | digests | $250 | 1 | True | 1.0 |
| 3 | audits | $250 | 1 | True | 1.0 |
| 4 | triage | $250 | 1 | True | 1.0 |
| 4 | digests | $250 | 1 | True | 1.0 |
| 4 | audits | $250 | 1 | True | 1.0 |
| 5 | triage | $250 | 1 | True | 1.0 |
| 5 | digests | $250 | 1 | True | 1.0 |
| 5 | audits | $250 | 1 | True | 1.0 |
