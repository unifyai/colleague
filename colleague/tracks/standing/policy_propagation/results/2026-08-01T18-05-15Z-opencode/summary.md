# policy_propagation (opencode arm) — 2026-08-01T18-05-15Z-opencode

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter

| phase | LLM calls | prompt tok | completion tok | usage-missing | wall (s) |
|---|---|---|---|---|---|
| setup_triage | 13 | 233540 | 5081 | 0 | 86.77 |
| setup_digests | 8 | 95281 | 3258 | 0 | 46.02 |
| setup_audits | 9 | 134625 | 3408 | 0 | 44.44 |
| fire_round1_triage | 13 | 82548 | 2382 | 0 | 39.46 |
| fire_round1_digests | 4 | 6709 | 251 | 0 | 8.83 |
| fire_round1_audits | 5 | 9384 | 527 | 0 | 12.04 |
| fire_round2_triage | 12 | 70675 | 2413 | 0 | 42.22 |
| fire_round2_digests | 4 | 6722 | 253 | 0 | 7.8 |
| fire_round2_audits | 5 | 9311 | 502 | 0 | 12.5 |
| policy_change | 12 | 180478 | 2408 | 0 | 42.12 |
| fire_round3_triage | 12 | 72245 | 2229 | 0 | 39.57 |
| fire_round3_digests | 4 | 6722 | 259 | 0 | 8.62 |
| fire_round3_audits | 5 | 9312 | 507 | 0 | 16.37 |
| fire_round4_triage | 13 | 86184 | 2358 | 0 | 40.99 |
| fire_round4_digests | 4 | 6695 | 239 | 0 | 14.38 |
| fire_round4_audits | 5 | 9326 | 481 | 0 | 11.81 |
| fire_round5_triage | 13 | 79830 | 2260 | 0 | 40.71 |
| fire_round5_digests | 4 | 6702 | 245 | 0 | 8.26 |
| fire_round5_audits | 5 | 9974 | 432 | 0 | 10.95 |

| round | automation | threshold | mode | delivered | contract | accuracy |
|---|---|---|---|---|---|---|
| 1 | triage | $500 | wake_prompt | 0 | False | 0.0 |
| 1 | digests | $500 | command:support-digest | 0 | False | 0.0 |
| 1 | audits | $500 | command:escalation-audit | 1 | True | 1.0 |
| 2 | triage | $500 | wake_prompt | 0 | False | 0.0 |
| 2 | digests | $500 | command:support-digest | 0 | False | 0.0 |
| 2 | audits | $500 | command:escalation-audit | 1 | False | 0.0 |
| 3 | triage | $250 | wake_prompt | 0 | False | 0.0 |
| 3 | digests | $250 | command:support-digest | 0 | False | 0.0 |
| 3 | audits | $250 | command:escalation-audit | 1 | True | 1.0 |
| 4 | triage | $250 | wake_prompt | 0 | False | 0.0 |
| 4 | digests | $250 | command:support-digest | 0 | False | 0.0 |
| 4 | audits | $250 | command:escalation-audit | 1 | True | 1.0 |
| 5 | triage | $250 | wake_prompt | 0 | False | 0.0 |
| 5 | digests | $250 | command:support-digest | 0 | False | 0.0 |
| 5 | audits | $250 | command:escalation-audit | 1 | True | 1.0 |
