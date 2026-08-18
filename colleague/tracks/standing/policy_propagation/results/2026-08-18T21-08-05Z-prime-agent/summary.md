# policy_propagation (prime-agent arm) — 2026-08-18T21-08-05Z-prime-agent

- model: `openai/gpt-5.6-sol` via recording proxy -> OpenRouter
- prime-agent repo: `/Users/djl11/prime-agent`

| phase | LLM calls | prompt tok | completion tok | usage-missing | wall (s) |
|---|---|---|---|---|---|
| setup_triage | 3 | 15615 | 719 | 0 | 21.09 |
| setup_digests | 2 | 14181 | 618 | 0 | 16.16 |
| setup_audits | 3 | 26834 | 739 | 0 | 25.44 |
| fire_round1_triage | 3 | 30521 | 523 | 0 | 18.56 |
| fire_round1_digests | 3 | 32718 | 402 | 0 | 17.78 |
| fire_round1_audits | 3 | 34831 | 406 | 0 | 22.64 |
| fire_round2_triage | 3 | 37005 | 559 | 0 | 19.56 |
| fire_round2_digests | 3 | 39224 | 420 | 0 | 17.85 |
| fire_round2_audits | 5 | 63171 | 1497 | 0 | 38.98 |
| policy_change | 9 | 149298 | 758 | 0 | 47.71 |
| fire_round3_triage | 3 | 55915 | 557 | 0 | 17.75 |
| fire_round3_digests | 3 | 58166 | 418 | 0 | 16.94 |
| fire_round3_audits | 3 | 60235 | 381 | 0 | 16.04 |
| fire_round4_triage | 3 | 62321 | 428 | 0 | 16.68 |
| fire_round4_digests | 3 | 64381 | 296 | 0 | 15.41 |
| fire_round4_audits | 3 | 66213 | 295 | 0 | 16.61 |
| fire_round5_triage | 3 | 68182 | 414 | 0 | 16.7 |
| fire_round5_digests | 3 | 70254 | 327 | 0 | 19.1 |
| fire_round5_audits | 3 | 72098 | 301 | 0 | 17.78 |

| round | automation | threshold | mode | delivered | contract | accuracy |
|---|---|---|---|---|---|---|
| 1 | triage | $500 | wake_prompt | 1 | True | 1.0 |
| 1 | digests | $500 | wake_prompt | 1 | True | 1.0 |
| 1 | audits | $500 | wake_prompt | 1 | True | 1.0 |
| 2 | triage | $500 | wake_prompt | 1 | True | 1.0 |
| 2 | digests | $500 | wake_prompt | 1 | True | 1.0 |
| 2 | audits | $500 | wake_prompt | 1 | True | 1.0 |
| 3 | triage | $250 | wake_prompt | 1 | True | 1.0 |
| 3 | digests | $250 | wake_prompt | 1 | True | 1.0 |
| 3 | audits | $250 | wake_prompt | 1 | True | 1.0 |
| 4 | triage | $250 | wake_prompt | 1 | True | 1.0 |
| 4 | digests | $250 | wake_prompt | 1 | True | 1.0 |
| 4 | audits | $250 | wake_prompt | 1 | True | 1.0 |
| 5 | triage | $250 | wake_prompt | 1 | True | 1.0 |
| 5 | digests | $250 | wake_prompt | 1 | True | 1.0 |
| 5 | audits | $250 | wake_prompt | 1 | True | 1.0 |
