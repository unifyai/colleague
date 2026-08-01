# Reading this arm's runs table

**OpenCode wins this experiment outright.**

What it produced from the single utterance: one standalone Python script,
`weekly_orders_report.py`, using only the stdlib, computing the week
boundaries itself, validating the response shape, and POSTing the report.
Setup cost 10 calls / 82,719 tokens. Every one of the four fires then ran
that script for **0 LLM calls and delivered an exact report** — the same
zero-token steady state unify reaches, at ~18× lower setup cost, and
without unify's wrong-week derivation run on the way there.

**It also closed the scheduling loop, using the host's scheduler.** Having
no cron surface of its own, the agent installed a real user `crontab`
entry pointing at the script, gated to Monday 09:00 UTC:

```
0 * * * * [ "$(TZ=UTC /bin/date +\%u-\%H)" = "1-09" ] && /usr/bin/python3 .../weekly_orders_report.py >> .../weekly_orders_report.log 2>&1
```

That is a genuine end-to-end automation, and it is the same
hourly-with-a-wall-clock-gate shape the hermes agent chose in this
experiment — arrived at independently, by a system with no scheduler, on
the same task. The harness fires the script directly (per the
pre-registered rule), which is exactly what that crontab line does.

**Host side effect, and why the driver now guards it.** Those entries are
live jobs on the machine running the suite, pointing into a throwaway
results directory. They were found and removed during the later triage
run; the driver now snapshots the user crontab before each run and
restores it afterwards (`defuse_host_artifacts`), reporting anything it
removed in `results.json`. Nothing ever fired here — the entries existed
from 17:41–17:47 UTC and cron triggers on minute 0.

Also worth recording: `small_model` is pinned to the benchmark model in
this arm's config. Left at its default OpenCode picks a cheaper model for
title generation (observed: `google/gemini-3.6-flash`), which would put
part of its real cost on a different provider and outside the comparison.
