# Reading this arm's fires table — supersedes the earlier OpenCode run

Rerun under the final environment (agent has its own CLI on PATH) and the
final firing rule (execute the command the agent's crontab spec names).
Supersedes `2026-08-01T17-43-45Z-opencode`, which reached the same
conclusion under the earlier rule — the two agree, which is the useful
part.

- **8/10 with a human, 4/10 without.** The agent wrote a standalone stdlib
  script plus a cron spec. Fires 1-4 exact at **zero tokens**. The field
  rename broke it, fires 5-6 delivered nothing, and one operator message
  ("it's been failing, fix it") repaired it for 225k tokens; fires 7-10
  exact and free again, catching up the pending cursor range.
- **Cheapest series of any arm: 290k tokens total** (hermes 1.42M, unify
  1.51M, openclaw 0.40M) — its setup is 65k and even its repair session is
  a third of hermes's.
- **Structurally identical to hermes.** A script steady state has no model
  in the loop, so nothing observes the failure and it flatlines at 4/10
  forever without a human. This is the clean pairing in the suite: script
  steady states (hermes, opencode) are free per fire and cannot self-heal;
  model-in-loop steady states (unify's repair path, openclaw's agent turn)
  recover unattended and pay for it.
