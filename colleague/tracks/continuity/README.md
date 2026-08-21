# Track: continuity

**Is a follow-up a warm turn or a cold restart?**

Not a correctness track. Every arm should get February right; the measurement
is what getting it right cost the second time. Authentication is deliberately
slow and deliberately observable, so a cold restart is a fact the fixture
witnessed rather than an inference from token counts.

| Scenario | |
|---|---|
| `january` | The expensive first pass. Authenticate, pull the ledger, report the top three vendors. |
| `february_followup` | "Now do the same for February." Nothing is restated — not the API, not the task, not the credentials. |

The session is held across both scenarios (`SESSION_SCOPE = "track"`), and so
is the fixture — a warm session must not be penalised for remembering a base
URL the harness moved.

```bash
python -m colleague.run continuity --arm unify
```

**What to expect.** A correct answer that re-authenticates scores `DEGRADED`
rather than `FAIL`, because it is correct and the cost is the finding.
unify's `persist=True` keeps the sandbox and its variables; OpenClaw keeps
the session; hermes and OpenCode start each turn from nothing. The number to
watch is `auth_calls` in the February evidence.

**Honest limit.** Authentication is a cheap stand-in for the real thing,
which is any working state a task built and never wrote down — a parsed
dataframe, a mapping derived from four calls. The fixture cannot see those.
It can see the one that costs a round trip, and that is what it counts.

## Human protocol

Run `python -m colleague.run continuity --arm human`. The same participant and
persistent notes carry the warm condition. A cold comparison uses a
counterbalanced participant with only the declared cold context; human memory
cannot be reset in place. Re-authentication, time and labour cost are recorded.
