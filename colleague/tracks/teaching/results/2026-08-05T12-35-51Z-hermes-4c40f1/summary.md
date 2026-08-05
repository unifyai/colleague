# teaching — hermes arm — 2026-08-05T12-35-51Z-hermes-4c40f1

Derived from proxy_ledger.jsonl / results.json in this directory.

## Outcomes
| scenario | outcome | reason | recipients (got) | expected |
|---|---|---|---|---|
| week_31_taught | pass | - | ['amanda.reyes@northwind.example', 'ap@ostrava.example'] | ['amanda.reyes@northwind.example', 'ap@ostrava.example'] |
| week_32_replay | pass | - | ['amanda.reyes@northwind.example', 'ap@ostrava.example'] | ['amanda.reyes@northwind.example', 'ap@ostrava.example'] |
| untaught_control | unsupported | as designed: the exceptions are not discoverable without being told | ['ap@bergen.example', 'ap@cardinal.example', 'ap@halden.example', 'ap@ostrava.example', 'ap@trellis.example'] | ['amanda.reyes@northwind.example', 'ap@ostrava.example'] |

## Cost (recording proxy, chat completions only)
| session | LLM calls | prompt tok | completion tok | cost USD |
|---|---|---|---|---|
| week_31 + week_32 (shared session) | 9 | 320848 | 1354 | 0.6247 |
| untaught_control (own session) | 2 | 68643 | 791 | 0.2589 |
| TOTAL | 11 | 389491 | 2145 | 0.8836 |

Raw evidence: results.json (outcomes/evidence), proxy_ledger.jsonl (every model call),
hermes_cli.log (the agent's own terminal output).
