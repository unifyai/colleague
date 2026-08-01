# policy_propagation (hermes-agent arm) — 2026-07-31T16-02-27Z-hermes

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter

| phase | LLM calls | prompt tok | completion tok | usage-missing | wall (s) |
|---|---|---|---|---|---|
| setup_triage | 4 | 154090 | 802 | 0 | 36.75 |
| setup_digests | 5 | 195645 | 1703 | 0 | 44.55 |
| setup_audits | 6 | 236083 | 2018 | 0 | 57.35 |
| fire_round1_triage | 6 | 21149 | 1056 | 1 | 574.24 |
| fire_round1_digests | 5 | 21235 | 970 | 0 | 37.85 |
| fire_round1_audits | 3 | 11850 | 867 | 0 | 631.66 |
| fire_round2_triage | 5 | 21549 | 1254 | 0 | 26.49 |
| fire_round2_digests | 5 | 21296 | 941 | 0 | 24.38 |
| fire_round2_audits | 5 | 20147 | 724 | 0 | 24.27 |
| policy_change | 6 | 265024 | 2610 | 0 | 55.44 |
| fire_round3_triage | 5 | 16021 | 707 | 1 | 19.8 |
| fire_round3_digests | 5 | 21894 | 1374 | 0 | 30.76 |
| fire_round3_audits | 5 | 20314 | 829 | 0 | 32.99 |
| fire_round4_triage | 5 | 21205 | 1071 | 0 | 29.08 |
| fire_round4_digests | 5 | 22401 | 1411 | 0 | 29.2 |
| fire_round4_audits | 5 | 20252 | 782 | 0 | 25.73 |
| fire_round5_triage | 5 | 21281 | 1101 | 0 | 24.78 |
| fire_round5_digests | 5 | 20912 | 884 | 0 | 23.47 |
| fire_round5_audits | 5 | 20379 | 851 | 0 | 23.82 |

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
