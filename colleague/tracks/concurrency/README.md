# Track: concurrency

**Two corrections, three pieces of work, no labels.**

Three digests are created in one turn. After the first and second creations —
while the third is still being written — two corrections arrive, each naming
its target the way a person would: "the support one", "finance". Neither
names an id.

| Scenario | |
|---|---|
| `route_corrections` | Both corrections must land on the digest they name, and the untouched one must stay untouched. |
| `three_senders` | Three people, three digests, and each corrects "mine". Routing needs the sender, not just the words. |

`three_senders` is the concurrent shape. Daniel asks for one digest; while it
is being created, Priya and Bob each arrive with a request of their own; once
all three exist, each corrects *their own* digest without naming it. Two
requests from two more people are delivered through the same channel as a
correction — an arm with no way for a second person to reach the running
assistant resolves to UNSUPPORTED rather than being scored as having routed
nothing. Three of the six checks are about what did not change.

Scoring is the fixture's final state. Five checks, and two of them are about
what did *not* change — `sales_untouched` and `finance_frequency_unchanged`
catch the failure where corrections are applied to whatever the loop happened
to be holding.

```bash
python -m colleague.run concurrency --arm unify
```

**What to expect.** unify tracks each running action separately and exposes
handle-addressed steering tools (`interject`, `stop`, `pause`, `resume`, `ask`
with a handle id), so routing a correction is a tool call with an argument
rather than an inference from the text. Every comparison harness now has
live steering of some kind, but each addresses "the current run": OpenClaw's
own docs say steering does not split messages by sender, and hermes and
prime-agent steer one session. `three_senders` is where that difference is
observable.

**Honest limit.** `route_corrections` models concurrency as a batch within a
single turn. `three_senders` gets closer — three requests from three people,
each becoming its own piece of work — but still arrives through one session
handle, so what is measured is whether the arm keeps three in-flight things
distinct enough to address one by sender. Genuinely independent lifetimes
(three separate dispatches, corrections against each while a fourth thing
runs) still want a runner that holds several handles at once.

## Human protocol

Run `python -m colleague.run concurrency --arm human`. Named requests and
corrections arrive live at existing progress waypoints. The fixture scores the
same final state and untouched controls; elapsed time, active labour and labour
cost are also recorded.
