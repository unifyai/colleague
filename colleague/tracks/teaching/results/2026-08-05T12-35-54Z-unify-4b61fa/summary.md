# teaching — unify arm — 2026-08-05T12-35-54Z-unify-4b61fa

Derived from unify_ledger.jsonl / results.json in this directory.

## Outcomes
| scenario | outcome | reason | recipients (got) | expected |
|---|---|---|---|---|
| week_31_taught | pass | - | ['amanda.reyes@northwind.example', 'ap@ostrava.example'] | ['amanda.reyes@northwind.example', 'ap@ostrava.example'] |
| week_32_replay | pass | - | ['amanda.reyes@northwind.example', 'ap@ostrava.example'] | ['amanda.reyes@northwind.example', 'ap@ostrava.example'] |
| untaught_control | unsupported | as designed: the exceptions are not discoverable without being told | ['ap@bergen.example', 'ap@cardinal.example', 'ap@halden.example', 'ap@ostrava.example', 'ap@trellis.example'] | ['amanda.reyes@northwind.example', 'ap@ostrava.example'] |

## Cost (in-process unillm hook)
| segment | LLM calls | prompt tok | completion tok | cost USD | wall s |
|---|---|---|---|---|---|
| turn_1 | 6 | 363304 | 1526 | 0.269134 | 62.67 |
| turn_2 | 11 | 652477 | 2181 | 0.480116 | 110.68 |
| untaught_control (own session) | 6 | 353045 | 1186 | 0.2388 | - |
| TOTAL | 23 | 1368826 | 4893 | 0.988 | - |

turn_1 = week_31_taught, turn_2 = week_32_replay (shared persistent session).
Raw evidence: results.json, unify_ledger.jsonl, untaught_control/unify_ledger.jsonl.
