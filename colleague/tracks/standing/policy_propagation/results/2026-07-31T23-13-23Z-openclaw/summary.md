# policy_propagation (openclaw arm) — 2026-07-31T23-13-23Z-openclaw

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter

| phase | LLM calls | prompt tok | completion tok | usage-missing | wall (s) |
|---|---|---|---|---|---|
| setup_triage | 5 | 79056 | 2458 | 0 | 56.45 |
| setup_digests | 3 | 58017 | 1156 | 0 | 23.25 |
| setup_audits | 3 | 66221 | 987 | 0 | 21.1 |
| fire_round1_triage | 4 | 29431 | 888 | 0 | 21.07 |
| fire_round1_digests | 3 | 22817 | 904 | 0 | 21.14 |
| fire_round1_audits | 3 | 22713 | 1347 | 0 | 24.78 |
| fire_round2_triage | 3 | 22596 | 993 | 0 | 16.94 |
| fire_round2_digests | 4 | 30104 | 866 | 0 | 17.03 |
| fire_round2_audits | 4 | 30060 | 1401 | 0 | 24.45 |
| policy_change | 5 | 137012 | 5484 | 0 | 54.47 |
| fire_round3_triage | 4 | 29698 | 1204 | 0 | 23.82 |
| fire_round3_digests | 4 | 29948 | 850 | 0 | 20.13 |
| fire_round3_audits | 3 | 22622 | 1128 | 0 | 23.87 |
| fire_round4_triage | 4 | 29683 | 1134 | 0 | 27.66 |
| fire_round4_digests | 3 | 22877 | 1130 | 0 | 23.96 |
| fire_round4_audits | 4 | 29859 | 1415 | 0 | 72.29 |
| fire_round5_triage | 2 | 14954 | 1053 | 0 | 20.16 |
| fire_round5_digests | 3 | 23124 | 1195 | 0 | 20.15 |
| fire_round5_audits | 3 | 22706 | 1174 | 0 | 20.16 |

| round | automation | threshold | delivered | contract | accuracy |
|---|---|---|---|---|---|
| 1 | triage | $500 | 1 | True | 0.9 |
| 1 | digests | $500 | 1 | False | 0.0 |
| 1 | audits | $500 | 1 | True | 1.0 |
| 2 | triage | $500 | 1 | True | 0.8 |
| 2 | digests | $500 | 1 | True | 1.0 |
| 2 | audits | $500 | 1 | True | 1.0 |
| 3 | triage | $250 | 1 | True | 0.9 |
| 3 | digests | $250 | 1 | True | 1.0 |
| 3 | audits | $250 | 1 | True | 1.0 |
| 4 | triage | $250 | 1 | True | 1.0 |
| 4 | digests | $250 | 1 | True | 1.0 |
| 4 | audits | $250 | 1 | True | 1.0 |
| 5 | triage | $250 | 1 | True | 0.4 |
| 5 | digests | $250 | 1 | True | 1.0 |
| 5 | audits | $250 | 1 | True | 1.0 |
