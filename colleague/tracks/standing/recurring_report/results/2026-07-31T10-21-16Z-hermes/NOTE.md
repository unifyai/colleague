# Reading this arm's runs table

The hermes agent's setup (26 LLM calls, 1.22M prompt tokens) converged to
its **zero-LLM** recurring mode: a `no_agent: true` cron job running a
standalone script (`hermes_home/scripts/weekly_orders_report.py`) — not a
per-firing agent boot. Two behavioral findings:

1. **Schedule encoding diverged from the ask.** The utterance said Monday
   09:00; the agent created `0 * * * 1` (hourly on Mondays) plus an
   in-script wall-clock gate (`weekday() != 0 or hour != 9 → return`),
   citing local-timezone/DST concerns. In production this fires 24×/Monday
   with 23 no-ops.
2. **The artifact is wall-clock-coupled.** All four manual fires (a Friday)
   exited "succeeded" in ~0.3s having done nothing — the gate returned
   before any fetch. Hence `reports = 0` in the runs table: the automation
   cannot be exercised on demand.

Post-hoc verification (script unmodified, clock patched to its designed
instant, Monday 2026-08-03 09:00 UTC): the script delivered **1 report,
exactly matching ground truth**. The compute/POST logic is correct; only
the firing semantics are off-spec and untriggerable off-schedule.

Net: hermes also reached a zero-marginal-token steady state for this task,
cheaper to set up than unify's (1.23M vs 1.52M total tokens) because unify's
policy defers function extraction to the first live run's review. The
measured differences are artifact quality and lifecycle: unify honored the
requested schedule in a typed task definition, its stored function runs
correctly whenever fired (3/3 exact), and the function lives in a
searchable registry; the hermes script is bound to one cron entry and
refuses execution outside one wall-clock hour.
