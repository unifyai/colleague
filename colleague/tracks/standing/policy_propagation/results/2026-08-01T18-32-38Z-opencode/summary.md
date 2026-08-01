# policy_propagation (opencode arm) — 2026-08-01T18-32-38Z-opencode

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter

| phase | LLM calls | prompt tok | completion tok | usage-missing | wall (s) |
|---|---|---|---|---|---|
| setup_triage | 12 | 222653 | 4817 | 0 | 85.28 |
| setup_digests | 7 | 73912 | 3140 | 0 | 43.53 |
| setup_audits | 8 | 106047 | 2776 | 0 | 38.79 |
| fire_round1_triage | 5 | 9639 | 542 | 0 | 11.34 |
| fire_round1_digests | 9 | 57485 | 1286 | 0 | 23.5 |
| fire_round1_audits | 5 | 9179 | 472 | 0 | 12.86 |
| fire_round2_triage | 5 | 9533 | 462 | 0 | 11.37 |
| fire_round2_digests | 12 | 92546 | 1742 | 0 | 33.41 |
| fire_round2_audits | 5 | 9167 | 523 | 0 | 12.81 |
| policy_change | 7 | 89196 | 1917 | 0 | 27.94 |
| fire_round3_triage | 5 | 9588 | 514 | 0 | 13.98 |
| fire_round3_digests | 8 | 44375 | 1053 | 0 | 24.54 |
| fire_round3_audits | 5 | 9167 | 493 | 0 | 12.15 |
| fire_round4_triage | 5 | 9599 | 500 | 0 | 10.1 |
| fire_round4_digests | 12 | 88099 | 1680 | 0 | 34.01 |
| fire_round4_audits | 5 | 9051 | 394 | 0 | 9.62 |
| fire_round5_triage | 5 | 9650 | 517 | 0 | 11.93 |
| fire_round5_digests | 11 | 95344 | 1285 | 0 | 26.54 |
| fire_round5_audits | 5 | 9113 | 439 | 0 | 9.77 |

| round | automation | threshold | mode | delivered | contract | accuracy |
|---|---|---|---|---|---|---|
| 1 | triage | $500 | command:triage-support | 0 | False | 0.0 |
| 1 | digests | $500 | wake_prompt | 0 | False | 0.0 |
| 1 | audits | $500 | command:audit-escalations | 1 | True | 1.0 |
| 2 | triage | $500 | command:triage-support | 0 | False | 0.0 |
| 2 | digests | $500 | wake_prompt | 0 | False | 0.0 |
| 2 | audits | $500 | command:audit-escalations | 1 | False | 0.0 |
| 3 | triage | $250 | command:triage-support | 0 | False | 0.0 |
| 3 | digests | $250 | wake_prompt | 0 | False | 0.0 |
| 3 | audits | $250 | command:audit-escalations | 1 | True | 1.0 |
| 4 | triage | $250 | command:triage-support | 0 | False | 0.0 |
| 4 | digests | $250 | wake_prompt | 0 | False | 0.0 |
| 4 | audits | $250 | command:audit-escalations | 1 | True | 1.0 |
| 5 | triage | $250 | command:triage-support | 0 | False | 0.0 |
| 5 | digests | $250 | wake_prompt | 0 | False | 0.0 |
| 5 | audits | $250 | command:audit-escalations | 1 | True | 1.0 |
