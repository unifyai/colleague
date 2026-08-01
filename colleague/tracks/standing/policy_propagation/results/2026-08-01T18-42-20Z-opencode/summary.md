# policy_propagation (opencode arm) — 2026-08-01T18-42-20Z-opencode

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter

| phase | LLM calls | prompt tok | completion tok | usage-missing | wall (s) |
|---|---|---|---|---|---|
| setup_triage | 10 | 152660 | 3805 | 0 | 62.48 |
| setup_digests | 12 | 162908 | 4256 | 0 | 63.05 |
| setup_audits | 8 | 109309 | 3936 | 0 | 51.07 |
| fire_round1_triage | 11 | 71573 | 1750 | 0 | 32.47 |
| fire_round1_digests | 4 | 8981 | 237 | 0 | 8.78 |
| fire_round1_audits | 5 | 12393 | 462 | 0 | 13.16 |
| fire_round2_triage | 12 | 81849 | 1919 | 0 | 44.54 |
| fire_round2_digests | 4 | 8955 | 224 | 0 | 9.14 |
| fire_round2_audits | 5 | 12337 | 461 | 0 | 12.26 |
| policy_change | 13 | 201455 | 2612 | 0 | 43.22 |
| fire_round3_triage | 13 | 107103 | 2184 | 0 | 45.48 |
| fire_round3_digests | 4 | 8955 | 224 | 0 | 7.47 |
| fire_round3_audits | 5 | 12427 | 510 | 0 | 12.99 |
| fire_round4_triage | 13 | 106375 | 2217 | 0 | 42.98 |
| fire_round4_digests | 4 | 8983 | 238 | 0 | 7.16 |
| fire_round4_audits | 5 | 12357 | 442 | 0 | 13.08 |
| fire_round5_triage | 12 | 93916 | 2245 | 0 | 41.88 |
| fire_round5_digests | 4 | 8941 | 218 | 0 | 6.81 |
| fire_round5_audits | 5 | 12339 | 446 | 0 | 12.0 |

| round | automation | threshold | mode | delivered | contract | accuracy |
|---|---|---|---|---|---|---|
| 1 | triage | $500 | wake_prompt | 0 | False | 0.0 |
| 1 | digests | $500 | command:digest-support | 0 | False | 0.0 |
| 1 | audits | $500 | command:audit-escalations | 1 | True | 1.0 |
| 2 | triage | $500 | wake_prompt | 0 | False | 0.0 |
| 2 | digests | $500 | command:digest-support | 0 | False | 0.0 |
| 2 | audits | $500 | command:audit-escalations | 1 | False | 0.0 |
| 3 | triage | $250 | wake_prompt | 0 | False | 0.0 |
| 3 | digests | $250 | command:digest-support | 0 | False | 0.0 |
| 3 | audits | $250 | command:audit-escalations | 1 | True | 1.0 |
| 4 | triage | $250 | wake_prompt | 0 | False | 0.0 |
| 4 | digests | $250 | command:digest-support | 0 | False | 0.0 |
| 4 | audits | $250 | command:audit-escalations | 1 | True | 1.0 |
| 5 | triage | $250 | wake_prompt | 0 | False | 0.0 |
| 5 | digests | $250 | command:digest-support | 0 | False | 0.0 |
| 5 | audits | $250 | command:audit-escalations | 1 | True | 1.0 |
