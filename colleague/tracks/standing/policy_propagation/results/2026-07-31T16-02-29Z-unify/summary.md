# policy_propagation (unify arm) — 2026-07-31T16-02-29Z-unify

| phase | LLM calls | prompt tok | completion tok | cost (USD) | wall (s) |
|---|---|---|---|---|---|
| setup_triage | 12 | 928548 | 2934 | 4.110146 | 283.7 |
| setup_digests | 12 | 756649 | 2586 | 2.220205 | 356.0 |
| setup_audits | 13 | 717318 | 2459 | 2.105977 | 377.07 |
| fire_round1_triage | 6 | 250768 | 3368 | 1.157554 | 65.51 |
| fire_round1_triage_review | 7 | 581738 | 5353 | 1.146017 | 284.79 |
| fire_round1_digests | 6 | 432985 | 2963 | 2.266682 | 70.01 |
| fire_round1_digests_review | 7 | 606762 | 5250 | 1.190445 | 292.09 |
| fire_round1_audits | 6 | 352277 | 2951 | 1.741153 | 56.85 |
| fire_round1_audits_review | 7 | 640089 | 4785 | 1.231994 | 281.48 |
| fire_round2_triage | 1 | 546 | 256 | 0.01041 | 13.14 |
| fire_round2_triage_review | 0 | 0 | 0 | 0.0 | 180.09 |
| fire_round2_digests | 1 | 600 | 236 | 0.01008 | 13.37 |
| fire_round2_digests_review | 0 | 0 | 0 | 0.0 | 180.09 |
| fire_round2_audits | 1 | 513 | 192 | 0.008325 | 10.01 |
| fire_round2_audits_review | 0 | 0 | 0 | 0.0 | 180.09 |
| policy_change | 30 | 2396601 | 11092 | 10.502672 | 458.54 |
| fire_round3_triage | 1 | 581 | 409 | 0.015175 | 16.69 |
| fire_round3_triage_review | 0 | 0 | 0 | 0.0 | 180.08 |
| fire_round3_digests | 1 | 581 | 376 | 0.014185 | 17.41 |
| fire_round3_digests_review | 0 | 0 | 0 | 0.0 | 180.08 |
| fire_round3_audits | 1 | 581 | 316 | 0.012385 | 13.91 |
| fire_round3_audits_review | 0 | 0 | 0 | 0.0 | 180.11 |
| fire_round4_triage | 1 | 583 | 280 | 0.011315 | 13.81 |
| fire_round4_triage_review | 0 | 0 | 0 | 0.0 | 180.14 |
| fire_round4_digests | 1 | 583 | 316 | 0.012395 | 14.25 |
| fire_round4_digests_review | 0 | 0 | 0 | 0.0 | 180.1 |
| fire_round4_audits | 1 | 583 | 291 | 0.011645 | 12.51 |
| fire_round4_audits_review | 0 | 0 | 0 | 0.0 | 180.11 |
| fire_round5_triage | 1 | 583 | 287 | 0.011525 | 17.11 |
| fire_round5_triage_review | 0 | 0 | 0 | 0.0 | 180.17 |
| fire_round5_digests | 1 | 583 | 245 | 0.010265 | 16.29 |
| fire_round5_digests_review | 0 | 0 | 0 | 0.0 | 180.11 |
| fire_round5_audits | 1 | 583 | 277 | 0.011225 | 14.4 |
| fire_round5_audits_review | 0 | 0 | 0 | 0.0 | 180.1 |

| round | automation | threshold | delivered | contract | accuracy |
|---|---|---|---|---|---|
| 1 | triage | $500 | 1 | True | 0.8 |
| 1 | digests | $500 | 1 | False | 0.0 |
| 1 | audits | $500 | 1 | True | 1.0 |
| 2 | triage | $500 | 1 | True | 1.0 |
| 2 | digests | $500 | 1 | True | 1.0 |
| 2 | audits | $500 | 1 | True | 1.0 |
| 3 | triage | $250 | 1 | True | 1.0 |
| 3 | digests | $250 | 1 | True | 1.0 |
| 3 | audits | $250 | 1 | True | 1.0 |
| 4 | triage | $250 | 1 | True | 0.9 |
| 4 | digests | $250 | 1 | False | 0.0 |
| 4 | audits | $250 | 1 | True | 1.0 |
| 5 | triage | $250 | 1 | True | 1.0 |
| 5 | digests | $250 | 1 | True | 1.0 |
| 5 | audits | $250 | 1 | True | 1.0 |
