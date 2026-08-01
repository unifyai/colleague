# Reading this arm's runs table

OpenClaw's agent converged to a **prompt-driven isolated cron job**
(`payload.kind: agentTurn`) — no script, no zero-token mode. Its cron tool
has no direct-execution payload, so every fire boots an agent turn: 2 LLM
calls, ~16.8k tokens, ~20 s. Three observations:

1. **Cheapest setup of the three arms by an order of magnitude.** 4 calls /
   67k tokens (hermes 1.22M, unify 1.52M to steady state). The OpenClaw
   system prompt is small, and the agent did no exploratory scripting — it
   authored one cron job and stopped.
2. **The payload is a self-authored program in prose.** The agent wrote the
   week-boundary semantics into the job message at creation time ("the
   report week is the last full Monday-through-Sunday week before today's
   UTC date", inclusive-range fetches, per-field validation, the exact
   revenue formulas, and a no-POST-on-failure rule). Re-derivation per fire
   is therefore anchored: 4/4 on-demand fires delivered byte-exact reports
   — where unify's *description*-driven runs (before its entrypoint
   attached) picked the wrong week 3 of 4 times, and hermes's script was
   wall-clock-gated into delivering nothing.
3. **The tax is permanent.** ~16.8k tokens per fire forever. At this
   task's weekly cadence the cheap setup dominates for a long time (unify's
   one-time ~1.52M is not recouped until ~86 fires ≈ 1.7 years of Mondays);
   the hourly experiments invert that arithmetic quickly.

Schedule encoding: `0 9 * * 1` in `Europe/London` (utterance said Monday
09:00 without a timezone; the payload's computation rules are pinned to
UTC). Delivery mode `none` with the report POSTed by the agent itself —
fires work identically on demand and on schedule.
