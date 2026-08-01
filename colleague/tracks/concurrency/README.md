# Track: concurrency

**Two corrections, three pieces of work, no labels.**

Three digests are created in one turn. After the first and second creations —
while the third is still being written — two corrections arrive, each naming
its target the way a person would: "the support one", "finance". Neither
names an id.

| Scenario | |
|---|---|
| `route_corrections` | Both corrections must land on the digest they name, and the untouched one must stay untouched. |

Scoring is the fixture's final state. Five checks, and two of them are about
what did *not* change — `sales_untouched` and `finance_frequency_unchanged`
catch the failure where corrections are applied to whatever the loop happened
to be holding.

```bash
python -m colleague.run concurrency --arm unify
```

**What to expect.** unify tracks each running action separately and generates
a per-action steering tool named after it, so routing a correction is an
ordinary tool call rather than an inference. The comparison arms have one
undifferentiated turn, so a correction that arrives mid-batch has no
addressable target.

**Honest limit.** This is one scenario, and it is the thinnest track in the
suite. It models concurrency as a batch within a single turn rather than as
genuinely independent in-flight tasks with their own lifetimes, because the
runner drives one turn per scenario. Real concurrent dispatch — three
separate `act` calls, corrections arriving against each — needs a runner that
can hold several handles at once, and that is the obvious next thing to build
here.
