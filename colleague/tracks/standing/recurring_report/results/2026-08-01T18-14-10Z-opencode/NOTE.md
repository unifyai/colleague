# Reading this arm's runs table — supersedes the earlier OpenCode run

This is the OpenCode weekly-report run under the final environment (agent
has its own CLI on PATH) and the final firing rule (execute the command
the agent's own crontab spec names). It **supersedes**
`2026-08-01T17-41-25Z-opencode`, which ran before both.

**Result: 0/4 delivered when fired as declared.** The agent wrote a
correct stdlib script plus a test for it, and a crontab spec whose own
comment states the design:

```
# Trigger hourly; the script exits unless it is Monday 09:00 UTC.
0 * * * * python3 .../weekly_orders_report.py --scheduled >> ... 2>&1
```

Fired on a Saturday, `--scheduled` makes the script exit before doing
anything: zero tokens, zero deliveries, four times over.

**This independently reproduces the hermes finding.** Hermes encoded the
same shape in this experiment — hourly cron plus an in-script wall-clock
gate — and was likewise inert when fired on demand. Two of the four arms,
given the same sentence, chose to implement "every Monday at 09:00" as
"run hourly and check the clock inside the job", which fires 24× a Monday
to deliver once and cannot be exercised off-schedule at all.

**Why the earlier run showed 4/4.** That run predated the cron-spec rule,
so the harness executed the script *bare* — without the `--scheduled`
flag, bypassing the gate — which is more generous than the treatment
hermes received (fired through its own cron job, gate active). The current
rule fires what each agent declared, so the arms are now treated alike.
The earlier run remains useful evidence that the compute logic is exactly
right: run without the gate, the same script produced four byte-exact
reports.

Setup cost was 84,885 tokens (10 calls), consistent with the earlier run's
82,719 — still by far the cheapest setup of any arm, and it now includes
the agent writing its own unit test for the report logic.
