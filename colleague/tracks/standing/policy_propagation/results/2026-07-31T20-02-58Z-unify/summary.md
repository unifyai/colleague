# policy_propagation (unify arm) — 2026-07-31T20-02-58Z-unify

| phase | LLM calls | prompt tok | completion tok | cost (USD) | wall (s) |
|---|---|---|---|---|---|
| setup_triage | 12 | 606900 | 3727 | 1.715789 | 285.7 |
| setup_digests | 13 | 825846 | 3372 | 2.225032 | 278.18 |
| setup_audits | 14 | 969497 | 3087 | 2.32688 | 276.98 |
| fire_round1_triage | 7 | 331203 | 4026 | 0.338485 | 78.84 |
| fire_round1_triage_review | 9 | 691135 | 6048 | 1.213133 | 289.54 |
| fire_round1_digests | 6 | 344119 | 3631 | 1.728089 | 68.44 |
| fire_round1_digests_review | 9 | 865854 | 5763 | 2.03929 | 321.93 |
| fire_round1_audits | 8 | 452192 | 3743 | 1.828774 | 67.24 |
| fire_round1_audits_review | 9 | 941937 | 5506 | 1.440904 | 301.24 |
| fire_round2_triage | 1 | 595 | 134 | 0.006995 | 9.61 |
| fire_round2_triage_review | 0 | 0 | 0 | 0.0 | 180.09 |
| fire_round2_digests | 1 | 565 | 134 | 0.006845 | 9.95 |
| fire_round2_digests_review | 0 | 0 | 0 | 0.0 | 180.09 |
| fire_round2_audits | 1 | 549 | 404 | 0.014865 | 10.21 |
| fire_round2_audits_review | 0 | 0 | 0 | 0.0 | 180.07 |
| policy_change | 13 | 1010379 | 8807 | 2.715115 | 329.83 |
| fire_round3_triage | 1 | 548 | 133 | 0.00673 | 9.83 |
| fire_round3_triage_review | 0 | 0 | 0 | 0.0 | 180.1 |
| fire_round3_digests | 1 | 542 | 133 | 0.0067 | 10.7 |
| fire_round3_digests_review | 0 | 0 | 0 | 0.0 | 180.09 |
| fire_round3_audits | 1 | 495 | 375 | 0.013725 | 10.88 |
| fire_round3_audits_review | 0 | 0 | 0 | 0.0 | 180.09 |
| fire_round4_triage | 1 | 549 | 133 | 0.006735 | 14.28 |
| fire_round4_triage_review | 0 | 0 | 0 | 0.0 | 180.09 |
| fire_round4_digests | 1 | 543 | 133 | 0.006705 | 11.42 |
| fire_round4_digests_review | 0 | 0 | 0 | 0.0 | 180.09 |
| fire_round4_audits | 1 | 496 | 305 | 0.01163 | 9.35 |
| fire_round4_audits_review | 0 | 0 | 0 | 0.0 | 180.08 |
| fire_round5_triage | 1 | 550 | 133 | 0.00674 | 9.76 |
| fire_round5_triage_review | 0 | 0 | 0 | 0.0 | 180.08 |
| fire_round5_digests | 1 | 544 | 133 | 0.00671 | 10.82 |
| fire_round5_digests_review | 0 | 0 | 0 | 0.0 | 180.07 |
| fire_round5_audits | 1 | 497 | 368 | 0.013525 | 11.07 |
| fire_round5_audits_review | 0 | 0 | 0 | 0.0 | 180.08 |

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
