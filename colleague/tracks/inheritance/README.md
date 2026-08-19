# Track: inheritance

**Does the assistant act on the right thing, without a round-trip?**

A conversation resolves two ambiguities that the eventual request does not
carry. Whether the harness still has that conversation when the work happens
decides whether it picks the right Sarah and the right report.

| Scenario | What it turns on |
|---|---|
| `ambiguous_recipient` | Two Sarahs, two reports. Both unambiguous inside the conversation, both ambiguous outside it. |
| `quiet_constraint` | A flight mentioned nine turns earlier and never restated. Nothing in the request hints at it. |
| `cold_control` | The conversation is withheld. Asking is correct; a lucky guess is scored as a failure. |
| `ask_the_owner` | The fact is missing and the conversation says who has it. Asking is right; asking the requester — who has just said he does not have it — is a round trip wasted. |

The control is the load-bearing one. Without it, an arm that guesses well
looks identical to an arm that remembers, and only one of those degrades
gracefully when it is wrong.

`ask_the_owner` is about *whom* you ask. Every arm with a clarification
channel can ask; two of the comparison harnesses now have a blocking one. But
a channel that reaches only "the user" can put the question to Daniel, hear
"Priya has it", and go no further. An arm that can address a question to a
named colleague asks Priya, and Priya answers as herself. The scorer reads
the `who` on each clarification: Priya first is PASS, Daniel then Priya is
DEGRADED, Daniel only is FAIL with the reason stated — and a channel that
names no addressee is reported as exactly that.

```bash
python -m colleague.run inheritance --arm unify
```

**What to expect.** At one hop, most arms should do well — a single loop with
the conversation in its context has the same information unify's fork
provides. The interesting result is the cold control, and the gap that opens
when work is delegated deeper. If every arm passes all three, that is a real
finding and should be reported as one.

Recorded run `2026-08-19T16-13-52Z-unify-cm-1af0c5`: `ambiguous_recipient`,
`quiet_constraint`, and `cold_control` passed — the cold control asked
Daniel through the CM's own channel and acted on the answer, which is the
clarification bridge working end to end. `ask_the_owner` failed as a
genuine choice: the actor found the report and missed the vendor contact,
and the brain reported the blocker back to Daniel as a statement rather
than asking anyone — the inherited conversation had named Priya, and a
question addressed to her would have been carried with its addressee.
