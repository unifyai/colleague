# Track: interruption

**Does a correction reach the work before the irreversible step?**

The correction is injected when the fixture sees the agent read the recipient
list, and scoring compares two recorder sequence numbers. No wall clock is
involved, so a cached run and a live one order identically.

| Scenario | The correction |
|---|---|
| `wrong_recipients` | Use their work addresses, not the personal ones |
| `scope_reduction` | Only the EU vendors, skip the US ones |
| `abort` | Stop — legal has not signed off |

```bash
python -m colleague.run interruption --arm unify
```

**What to expect, by mechanism.** The arms' declared steering capabilities
differ sharply enough that this result is close to predictable:

- **unify** pushes into the running loop and races the in-flight generation,
  so the correction should land before the first send.
- **OpenClaw** has a session but no mid-turn channel. It will read the
  correction — after the mail has gone. Expect `DEGRADED`: the right end
  state, reached too late to matter for something irreversible.
- **hermes** and **OpenCode** have no running loop to address. Expect
  `UNSUPPORTED`, reported separately and kept out of the accuracy
  denominator. They are not failing; there is nowhere for the message to go.

A predictable result is still worth measuring, because the claim is
architectural rather than behavioural. What would be surprising, and worth
chasing, is unify failing to land a correction in time.
