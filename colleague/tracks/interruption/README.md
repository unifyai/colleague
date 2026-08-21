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
| `resume_after_correction` | After two of four have gone: new subject for the rest, don't resend to anyone who has it |

`resume_after_correction` is about what happens to progress. Landing a
correction is one thing; landing it *without* throwing away the two sends
that were already right is the thing a colleague does and a restart does
not. Four checks: everyone reached, nobody mailed twice, the earlier sends
untouched, the later ones revised. A restart fails `nobody_mailed_twice`;
ignoring the correction fails `remainder_corrected`; sending everything
before the correction could arrive is DEGRADED, not FAIL. The correction is
keyed to the second send, and every send is held a few seconds so the third
cannot begin before the correction is in hand.

```bash
python -m colleague.run interruption --arm unify-cm
```

**What to expect, by mechanism.** The person-shaped surfaces all steer:
hermes's TUI gateway has `steer`/`redirect`, OpenClaw's default queue mode
is `steer` at tool-launch boundaries, prime-agent has a steering lane, and
the CM routes a correction into the in-flight action — all preserving the
run rather than restarting it. OpenCode's one-shot CLI is the exception:
there is nowhere to put a correction, and its cells resolve UNSUPPORTED.
What differentiates the rest is what the correction does to progress
already made, which is what `resume_after_correction` isolates. Expect the
timing scenarios to be close; read the progress scenario for the
difference.

## Human protocol

Run `python -m colleague.run interruption --arm human`. Corrections appear at
the same fixture waypoint used for agent arms, so ordering is event-relative,
not dependent on human speed. Outcomes, active labour and cost use the shared
result schema.
