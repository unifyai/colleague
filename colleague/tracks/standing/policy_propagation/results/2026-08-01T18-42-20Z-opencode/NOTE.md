# Conclusive result: the experiment is not reachable for OpenCode

Three attempts were made to obtain a clean OpenCode run of this
experiment, with the harness hardened after each. All three failed the
same way, and the failure is a property of the system under test, not of
the harness. **The conclusive finding is that OpenCode does not produce
three separable automations from three requests in one workspace — it
consistently ends with two, and triage is always the casualty.**

| attempt | what the three setups produced | result |
|---|---|---|
| `18-05-15Z` | triage never built; digests + audits built | 4/15 |
| `18-32-38Z` | a command *named* `triage-support` that reads and posts to `/digests`; triage sink unimplemented | 4/15 |
| `18-42-20Z` (this one) | `triage-support` created correctly at its own setup, then **deleted** by a later setup — the command directory ends with only `digest-support.md` and `audit-escalations.md` | 4/15 |

The identical 4/15 in all three is audits' five fires (four exact, one
accuracy miss) and nothing else: the other two automations can never
deliver, because at most one of them exists at fire time.

## Why this is the system's behaviour and not the harness's

The harness was tightened twice specifically to rule itself out:

1. **Name-based gate** — abort unless each setup declares an artifact
   matching its automation. Attempt 2 passed it falsely (the string
   "digests" appeared inside the *triage* cron file), which is how the
   mis-implemented `triage-support` slipped through.
2. **Content-based gate + content-based firing** — an artifact only
   counts for an automation if it references that automation's own sink
   endpoint (`/triage`, `/digests`, `/audits`); the three must be
   disjoint; and `_fire_named` resolves the artifact the same way, so a
   fire cannot be mis-assigned to a sibling. Validated against attempt 2,
   which it correctly rejects.

Attempt 3 passed the content gate at every individual setup — the record
in `results.json` shows `setup_triage.declared == ['command:triage-support']`
— and the artifact was gone by the time fires began. The deletion happens
*between* setups, so a per-setup gate cannot catch it; only a re-validation
after all three setups would, and that would simply abort every run.

## What this costs the comparison

The propagation question ("does one verbal change reach every automation?")
cannot be asked of OpenCode here, because the family never exists. The
cost figures are ledger sums and remain valid: setups 437k, change 204k,
steady state ~121k per round. The change session did correctly rewrite
both automations that existed.

OpenCode is deliberately excluded from `policy_propagation.svg`. The
suite's other three arms all answer this experiment; this arm answers a
different question instead, and the answer is about workspace-shared
automation families rather than about policy propagation.

## Related evidence

The semantic_triage arm independently found OpenCode's setup to be
bimodal (2 of 3 runs produced a working automation). Taken together the
picture is consistent: **OpenCode handles one automation per workspace
well and degrades as several share one.**
