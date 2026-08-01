# policy_propagation (hermes-agent arm) — 2026-07-31T17-29-22Z-hermes

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter

| phase | LLM calls | prompt tok | completion tok | usage-missing | wall (s) |
|---|---|---|---|---|---|
| setup_triage | 4 | 154160 | 869 | 0 | 26.89 |
| setup_digests | 6 | 237353 | 1821 | 0 | 47.77 |
| setup_audits | 13 | 535174 | 3284 | 0 | 89.27 |
| fire_round1_triage | 5 | 22556 | 1686 | 0 | 28.91 |
| fire_round1_digests | 7 | 32791 | 1726 | 0 | 53.03 |
| fire_round1_audits | 0 | 0 | 0 | 0 | 0.29 |
| fire_round2_triage | 5 | 23434 | 2382 | 0 | 41.03 |
| fire_round2_digests | 5 | 21234 | 1146 | 0 | 28.74 |
| fire_round2_audits | 0 | 0 | 0 | 0 | 0.4 |
| policy_change | 22 | 1131034 | 8253 | 0 | 180.02 |
| fire_round3_triage | 6 | 29694 | 2523 | 0 | 41.28 |
| fire_round3_digests | 5 | 21490 | 1233 | 0 | 32.1 |
| fire_round3_audits | 0 | 0 | 0 | 0 | 0.3 |
| fire_round4_triage | 8 | 45075 | 3404 | 0 | 53.84 |
| fire_round4_digests | 6 | 26129 | 1312 | 0 | 31.2 |
| fire_round4_audits | 0 | 0 | 0 | 0 | 0.3 |
| fire_round5_triage | 5 | 21629 | 1296 | 0 | 26.0 |
| fire_round5_digests | 6 | 26379 | 1245 | 0 | 26.2 |
| fire_round5_audits | 0 | 0 | 0 | 0 | 0.29 |

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
